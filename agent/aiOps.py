import ast
import json
import re


class ChatOpsClient:
    def __init__(self, mcp_server, llm):
        self.server = mcp_server
        self.llm = llm

        # 컨텍스트 메모리 최근 작업한 자원 ID를 기억하여 생략된 대화 처리
        self.context_memory = {
            "vpc_id": None,
            "subnet_id": None,
            "sg_id": None,
            "instance_id": None,
        }
        self.history = []
        self.max_history = 5

    def _extract_flexible_intent(self, text):
        """
        LLM 출력에서 JSON 데이터만 정밀 추출합니다.
        """
        try:
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                candidate = match.group(1)
                try:
                    data = json.loads(candidate)
                    return data.get("tool"), data.get("args", {})
                except json.JSONDecodeError:
                    try:
                        # 완벽한 JSON이 아닐 경우 Python 리터럴로 변환 시도
                        data = ast.literal_eval(candidate)
                        return data.get("tool"), data.get("args", {})
                    except:
                        pass
        except Exception:
            pass
        return None, {}

    def _rule_based_routing(self, user_input):
        """
        인프라 상태를 변경하지 않는 조회 명령은 즉시 실행하여 Latency를 최소화
        """
        text = user_input.lower()

        if any(w in text for w in ["cpu", "metric", "utilization"]):
            return "get_metric", {}
        if any(w in text for w in ["cost", "price", "billing"]):
            return "get_cost", {}
        if "topology" in text:
            return "generate_topology", {}
        if any(w in text for w in ["list", "show", "check", "inventory"]):
            return "list_instances", {"status": "all"}

        return None, {}

    def _finalize_args(self, user_input, tool, args):
        """
        [Arg Normalization]
        입력문에서 ID, 타입 등을 추출하고 불필요한 문장이 ID로 들어가는 것을 방지합니다. [cite: 117]
        """
        text = user_input.lower()

        # 인스턴스 타입 추출
        type_match = re.search(r"\b[tcmr][1-7][a-z]?\.\w+\b", text)
        if type_match:
            args["instance_type"] = type_match.group(0)

        # ID 및 이름 추출할 때 단순히 문장 전체를 가져오지 않도록 필터링 강화
        if not args.get("instance_id") and not args.get("name"):
            id_match = re.search(r"(i-[a-z0-9]+)", text)
            if id_match:
                args["instance_id"] = id_match.group(1)
            else:
                # 불용어 제거 후 남는 핵심 단어만 추출
                clean = re.sub(r"[,\'\"]", "", text)
                ignore_words = {
                    "create",
                    "launch",
                    "make",
                    "stop",
                    "start",
                    "resize",
                    "delete",
                    "terminate",
                    "instance",
                    "server",
                    "a",
                    "new",
                    "named",
                    "with",
                    "type",
                    "the",
                    "check",
                    "inventory",
                }
                words = [w for w in clean.split() if w not in ignore_words]
                val = " ".join(words).strip()

                if tool == "create_instance":
                    args["name"] = val if val else "new-instance"
                else:
                    args["instance_id"] = val if val else None

        # 문맥 주입 ID가 생략된 경우 메모리 활용
        if not args.get("instance_id") and self.context_memory["instance_id"]:
            if tool not in ["create_instance", "list_instances", "get_cost"]:
                args["instance_id"] = self.context_memory["instance_id"]

        return args

    def _check_safety(self, tool, args):
        # 삭제등 위험?한 액션 전 엔지니어의 승인을 확인
        critical_tools = ["stop_instance", "delete_resource", "resize_instance"]

        if tool in critical_tools:
            target = args.get("instance_id", "Unknown")
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

    def _update_internal_state(self, result):
        """성공한 작업의 리소스 ID를 메모리에 저장합니다."""
        if isinstance(result, dict) and result.get("status") == "success":
            res_id = result.get("resource_id")
            res_type = result.get("type")
            if res_type == "instance":
                self.context_memory["instance_id"] = res_id
            elif res_type in ["vpc", "subnet"]:
                self.context_memory[f"{res_type}_id"] = res_id

    def chat(self, user_input):
        # Read-Only 처리
        tool, args = self._rule_based_routing(user_input)

        # Action 처리 저수준 LLM 최적화
        if not tool:
            # MCP 도구 명칭을 명시적으로 학습시킴
            prompt = f"""[INST] <<SYS>>
You are an AWS Operations Agent. Respond ONLY in JSON. [cite: 66]
Available Tools: create_instance, stop_instance, start_instance, delete_resource, resize_instance.
Note: Use 'create_instance' instead of 'launch'.
Example: "Launch server" -> {{"tool": "create_instance", "args": {{"name": "server"}}}}
<</SYS>>
User: {user_input} [/INST]"""

            raw_response = self.llm.invoke(prompt)
            tool, llm_args = self._extract_flexible_intent(raw_response)
            if tool:
                args = llm_args

        if not tool:
            return "[System] Error: I couldn't identify the appropriate action."

        # 파라미터 보정 및 안전 검사
        args = self._finalize_args(user_input, tool, args)
        if not self._check_safety(tool, args):
            return "[System] Operation aborted."

        print(f"[System] Calling {tool} with {args}")
        result = self.server.call_tool(tool, args)
        self._update_internal_state(result)

        # 능동형 어시스트 (Proactive Assist)
        output = f"[Execution Success]\n{result}"

        # 생성 제안
        if "No instances found" in str(result):
            output += "\n\n[Proactive Assist] No instances detected. Would you like to 'create a new instance'?"

        # 대상 ID가 불명확할 때 가이드 제공
        elif "Target 'None' not found" in str(result) or not args.get("instance_id"):
            if tool not in ["create_instance", "list_instances"]:
                output += "\n\n[Proactive Assist] I need a specific Instance ID or Name to proceed. Please try: 'Stop [Instance Name]'"

        return output
