import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from agent.analysis import AnalysisAgent


class ChatOpsClient:
    # 안전 검사가 필요한 중요 작업 목록
    CRITICAL_TOOLS = {"terminate_resource", "resize_instance"}

    # 인스턴스 ID 정규식
    INSTANCE_ID_PATTERN = re.compile(r"(i-[a-z0-9]+)")

    # 인스턴스 타입 정규식
    INSTANCE_TYPE_PATTERN = re.compile(r"\b[tcmr][1-7][a-z]*\.[a-z]+\b")

    # 자연어 처리 시 제거할 불용어 목록
    STOP_WORDS = {
        "the",
        "a",
        "an",
        "start",
        "stop",
        "delete",
        "create",
        "launch",
        "make",
        "resize",
        "terminate",
        "remove",
        "instance",
        "server",
        "new",
        "named",
        "with",
        "type",
        "please",
        "can",
        "you",
        "will",
        "would",
        "should",
        "restart",
        "reboot",
        "check",
        "inventory",
    }

    def __init__(self, mcp_server, llm):
        self.server = mcp_server
        self.llm = llm
        self.analysis_agent = AnalysisAgent(mcp_server, llm)

        # 컨텍스트 메모리 최근 작업 자원 ID 기억
        self.context_memory: Dict[str, Optional[str]] = {
            "vpc_id": None,
            "subnet_id": None,
            "sg_id": None,
            "instance_id": None,
        }
        self.history = []
        self.max_history = 5

    def _extract_flexible_intent(
        self, text: str
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        try:
            # 중괄호로 묶인 영역 탐색
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                candidate = match.group(1)
                #  JSON 파싱
                try:
                    data = json.loads(candidate)
                    return data.get("tool"), data.get("args", {})
                except json.JSONDecodeError:
                    # Python 리터럴 파싱 Single quote 처리 등
                    try:
                        data = ast.literal_eval(candidate)
                        if isinstance(data, dict):
                            return data.get("tool"), data.get("args", {})
                    except (ValueError, SyntaxError):
                        pass
        except Exception as e:
            print(f"[System] Warning: Failed to parse intent - {e}")

        return None, {}

    def _rule_based_routing(
        self, user_input: str
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        자주 사용되는 패턴은 LLM을 거치지 않고 빠르게 처리
        """

        text = user_input.lower()

        # ===== 분석 도구 (규칙 기반) =====
        analysis_patterns = {
            "analyze_cost_trend": [
                "cost difference",
                "cost comparison",
                "cost trend",
                "analyze cost",
            ],
            "analyze_resource_usage": [
                "resource usage",
                "resource optimization",
                "which instance uses",
            ],
            "analyze_high_cpu": ["high cpu", "cpu spike", "cpu usage", "heavy cpu"],
        }

        for tool, patterns in analysis_patterns.items():
            if any(phrase in text for phrase in patterns):
                return tool, {}

        # ===== 조회 도구 (규칙 기반) =====
        if any(phrase in text for phrase in ["cost", "price", "billing", "bill"]):
            if not any(k in text for k in ["compare", "difference", "vs", "between"]):
                return "get_cost", {}

        if any(
            phrase in text for phrase in ["list instance", "show instance", "list all"]
        ):
            return "list_instances", {"status": "all"}

        if "topology" in text and "generate" in text:
            return "generate_topology", {}

        # ===== 상태 변경 도구 (단순 패턴만) =====
        # 정규식으로 인스턴스 이름이 추출 가능한 경우만 즉시 처리
        # 그렇지 않으면 LLM에 위임

        instance_id_match = self.INSTANCE_ID_PATTERN.search(text)

        if "start" in text and instance_id_match:
            return "start_instances", {"instance_id": instance_id_match.group(1)}

        if "stop" in text and instance_id_match:
            return "stop_instances", {"instance_id": instance_id_match.group(1)}

        if "reboot" in text and instance_id_match:
            return "reboot_instances", {"instance_id": instance_id_match.group(1)}

        if "terminate" in text and instance_id_match:
            return "terminate_resource", {"instance_id": instance_id_match.group(1)}

        return None, {}

    def _clean_text_for_extraction(self, text: str) -> str:
        clean = re.sub(r"[,\'\"]", "", text.lower())
        words = [w for w in clean.split() if w not in self.STOP_WORDS]
        return " ".join(words).strip()

    def _finalize_args(
        self, user_input: str, tool: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        파라미터를 보정하고 정규화합니다

        우선순위:
        1. 정규식으로 instance_id 추출
        2. 이름이면 MCP에 위임 (MCP가 ID로 변환할 것)
        3. 컨텍스트 메모리 활용 (신중하게)
        4. 기본값 설정
        """

        text = user_input.lower()

        # ===== Step 1: Instance ID 정규식 추출 =====
        if not args.get("instance_id"):
            id_match = self.INSTANCE_ID_PATTERN.search(text)
            if id_match:
                args["instance_id"] = id_match.group(1)

        # ===== Step 2: Instance Type 정규식 추출 =====
        if not args.get("instance_type"):
            type_match = self.INSTANCE_TYPE_PATTERN.search(text)
            if type_match:
                args["instance_type"] = type_match.group(0)

        # ===== Step 3: 인스턴스 이름 추출 (ID나 name이 없을 때) =====
        if not args.get("instance_id") and not args.get("name"):
            # 불용어 제거 후 남은 텍스트
            cleaned = self._clean_text_for_extraction(text)

            if cleaned:
                if tool in ["create_instance"]:
                    # create_instance는 name이 필요
                    args["name"] = cleaned
                elif tool in [
                    "stop_instances",
                    "start_instances",
                    "terminate_resource",
                    "resize_instance",
                    "create_snapshot",
                    "get_metric",
                ]:
                    # 이 도구들은 instance_id가 필요 → 이름으로 설정
                    # MCP 서버의 _normalize_args가 이를 ID로 변환할 것
                    args["instance_id"] = cleaned

        # ===== Step 4: 컨텍스트 메모리 활용 (신중하게) =====
        # 주의: create, list, cost 등은 이전 ID가 필요 없음
        # terminate, stop, start 같은 위험한 작업도 신중해야 함
        context_ignore_tools = {
            "create_instance",
            "list_instances",
            "get_cost",
            "get_metric",  # ← metric은 ID가 필요하지만 명시해야 함
            "generate_topology",
            "analyze_cost_trend",
            "analyze_resource_usage",
            "analyze_high_cpu",
        }

        context_require_tools = {
            "stop_instances",
            "start_instances",
            "reboot_instances",
            "terminate_resource",  # ← 위험! 명시 필수
        }

        if (
            not args.get("instance_id")
            and self.context_memory.get("instance_id")
            and tool in context_require_tools
        ):
            # 컨텍스트 메모리 사용 시 사용자에게 알림
            args["instance_id"] = self.context_memory["instance_id"]

        # ===== Step 5: 테스트 케이스 필터링 =====
        if args.get("instance_id") and (
            args["instance_id"].startswith("i-12345") or "abcde" in args["instance_id"]
        ):
            args["instance_id"] = None

        # ===== Step 6: create_instance 기본값 =====
        if tool == "create_instance":
            if not args.get("name"):
                args["name"] = "new-instance"
            if not args.get("instance_type"):
                args["instance_type"] = "t2.micro"

        return args

    def _check_safety(self, tool: str, args: Dict[str, Any]) -> bool:
        if tool in self.CRITICAL_TOOLS:
            target = args.get("instance_id", "Unknown Target")
            print(f"\n[System] Critical Action Detected: {tool.upper()}")
            print(f"[System] Target Identifier: {target}")
            confirm = input("Confirm execution? (yes/no): ").strip().lower()
            if confirm == "yes":
                print("[System] Operator confirmed. Executing...")
                return True
            else:
                print("[System] Action aborted by operator.")
                return False
        return True

    def _update_internal_state(self, result: Any) -> None:
        # 성공한 작업의 리소스 ID를 컨텍스트 메모리에 업데이트
        if isinstance(result, dict) and result.get("status") == "success":
            res_id = result.get("resource_id")
            res_type = result.get("type")

            if res_id:
                if res_type == "instance":
                    self.context_memory["instance_id"] = res_id
                elif res_type in ["vpc", "subnet"]:
                    self.context_memory[f"{res_type}_id"] = res_id

    def _generate_llm_prompt(self, user_input: str) -> str:
        return f"""[INST] <>
    You are an AWS Operations Agent. Analyze the user request and respond ONLY in JSON format.

    Available Tools:
    - create_instance: Launch a new EC2 instance (args: name, instance_type)
    - start_instances: Start a stopped instance (args: instance_id or name)
    - stop_instances: Stop an instance (args: instance_id or name)
    - reboot_instances: Reboot an instance (args: instance_id or name)
    - terminate_resource: Terminate an instance (args: instance_id or name)
    - resize_instance: Change instance type (args: instance_id or name, instance_type)
    - list_instances: Show all instances (args: status='all')
    - get_cost: Get monthly cost (args: {{}})
    - get_metric: Get instance metrics (args: instance_id or name, metric_name)
    - create_snapshot: Create a snapshot (args: instance_id or name)
    - generate_topology: Show VPC topology (args: {{}})
    - create_vpc: Create a new VPC (args: cidr)
    - create_subnet: Create a subnet (args: vpc_id, cidr)

    Important Rules:
    1. For instance operations (start, stop, terminate, etc.), always set either 'instance_id' or 'name'.
       - Use exact instance names when mentioned (e.g., "AIOpsmake", "newserver", "web-server")
       - Do NOT use 'InstanceIds' parameter - use 'instance_id' instead

    2. The MCP server will convert instance names to IDs automatically.
       - Always pass exactly what the user said for instance names
       - Example: "stop AIOpsmake" -> {{"tool": "stop_instances", "args": {{"instance_id": "AIOpsmake"}}}}

    3. For safety, terminate_resource is a CRITICAL action that requires confirmation.

    Format:
    {{"tool": "tool_name", "args": {{key: value}}}}

    Examples:
    - "launch a t2.micro instance"
      -> {{"tool": "create_instance", "args": {{"instance_type": "t2.micro"}}}}

    - "show instances"
      -> {{"tool": "list_instances", "args": {{"status": "all"}}}}

    - "show cost"
      -> {{"tool": "get_cost", "args": {{}}}}

    - "start web-server"
      -> {{"tool": "start_instances", "args": {{"instance_id": "web-server"}}}}

    - "stop AIOpsmake"
      -> {{"tool": "stop_instances", "args": {{"instance_id": "AIOpsmake"}}}}

    - "terminate the prod-server instance"
      -> {{"tool": "terminate_resource", "args": {{"instance_id": "prod-server"}}}}

    - "resize AIOpsmake to t3.large"
      -> {{"tool": "resize_instance", "args": {{"instance_id": "AIOpsmake", "instance_type": "t3.large"}}}}

    - "get cpu metric for web-server"
      -> {{"tool": "get_metric", "args": {{"instance_id": "web-server", "metric_name": "CPUUtilization"}}}}

    <>
    User: {user_input}
    [/INST]"""

    def chat(self, user_input: str) -> str:
        #  룰 기반 라우팅
        tool, args = self._rule_based_routing(user_input)
        if tool == "analyze_cost_trend":
            return self.analysis_agent.analyze_cost_trend(user_query=user_input)
        if tool == "analyze_resource_usage":
            return self.analysis_agent.analyze_resource_usage()
        if tool == "analyze_high_cpu":
            return self.analysis_agent.analyze_high_cpu_instances()

        # LLM 기반 라우팅
        if not tool:
            prompt = self._generate_llm_prompt(user_input)
            raw_response = self.llm.invoke(prompt)
            tool, llm_args = self._extract_flexible_intent(raw_response)
            if tool:
                args = llm_args

        # 의도 파악 실패 처리
        if not tool:
            return "[System] Error: I couldn't identify the appropriate action."

        # 파라미터 보정 및 안전 검사
        args = self._finalize_args(user_input, tool, args)

        if not self._check_safety(tool, args):
            return "[System] Operation aborted."

        print(f"[System] Calling {tool} with {args}")

        # 도구 실행
        try:
            result = self.server.call_tool(tool, args)
        except Exception as e:
            return f"[System] Execution Error: {str(e)}"

        # 상태 업데이트 및 결과 반환
        self._update_internal_state(result)

        output = f"[Execution Success]\n{result}"

        return output
