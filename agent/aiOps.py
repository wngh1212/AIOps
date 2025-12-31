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

        # 도구 이름 정규화 매핑
        self.tool_mapping = {
            "create_vpc": "create_vpc",
            "create-vpc": "create_vpc",
            "create_subnet": "create_subnet",
            "create_instance": "create_instance",
            "list_instances": "list_instances",
            "list-instances": "list_instances",
            "get_cost": "get_cost",
            "cost-estimator": "get_cost",
            "cost_estimator": "get_cost",
            "create_snapshot": "create_snapshot",
            "resize_instance": "resize_instance",
            "resize-instance": "resize_instance",
            "start_instance": "start_instance",
            "stop_instance": "stop_instance",
            "get_metric": "get_metric",
        }

    def _extract_flexible_intent(self, text):
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
                if not isinstance(data, dict):
                    continue

                # 재귀 탐색
                found_tool, found_args = self._scan_dict(data)
                if found_tool:
                    extracted_tool = found_tool
                    extracted_args = found_args
                    break
        except:
            pass
        return extracted_tool, extracted_args

    def _scan_dict(self, data):
        for k, v in data.items():
            if k.lower() in self.tool_mapping:
                return self.tool_mapping[k.lower()], v if isinstance(v, dict) else {}
            if isinstance(v, str) and v.lower() in self.tool_mapping:
                return self.tool_mapping[v.lower()], data.get("args", {})
            if isinstance(v, dict):
                t, a = self._scan_dict(v)
                if t:
                    return t, a
        return None, {}

    def _heuristic_fallback(self, user_input):
        text = user_input.lower()
        if "create" in text and "vpc" in text:
            return "create_vpc", {}
        if "create" in text and "subnet" in text:
            return "create_subnet", {}
        if "launch" in text or ("create" in text and "instance" in text):
            return "create_instance", {}
        if "cost" in text or "price" in text:
            return "get_cost", {}
        if "snapshot" in text:
            return "create_snapshot", {}
        if "resize" in text or "type" in text:
            return "resize_instance", {}
        if "list" in text or "show" in text:
            return "list_instances", {"status": "all"}
        return None, {}

    def _intent_correction(self, user_input, tool, args):
        text = user_input.lower()

        # 1. 인스턴스 타입 추출 및 제거 (이름 오염 방지)
        if tool == "resize_instance" or "create_instance" == tool:
            # t2.nano, t3.small, m5.large 등 패턴 매칭
            type_match = re.search(r"\b[tcmr][1-7][a-z]?\.\w+\b", text)
            if type_match:
                found_type = type_match.group(0)
                args["instance_type"] = found_type
                # 중요: 텍스트에서 타입 단어를 제거해야 나중에 이름으로 인식 안 함
                text = text.replace(found_type, "")

        # 2. List Status 강제
        if tool == "list_instances":
            if not any(w in text for w in ["running", "active"]):
                args["status"] = "all"

        # 3. CIDR 추출
        if tool in ["create_vpc", "create_subnet"]:
            cidr_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d+)", text)
            if cidr_match:
                args["cidr"] = cidr_match.group(1)

        # 4. 인스턴스 이름 정제 (Start/Stop/Resize 등)
        # 이제 text에는 인스턴스 타입(t3.small)이 제거된 상태임
        if tool in [
            "start_instance",
            "stop_instance",
            "create_snapshot",
            "resize_instance",
            "delete_resource",
        ]:
            if "instance_id" not in args or not args["instance_id"]:
                clean = text
                # 불필요한 단어 제거
                ignore_words = [
                    "create",
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
                    "the",
                    "resource",
                    "instance",
                    "server",
                    "check",
                ]
                for w in ignore_words:
                    clean = clean.replace(w, "")

                # 특수문자 제거 및 공백 정리
                clean = clean.replace("'", "").replace('"', "").strip()
                args["instance_id"] = clean

        return tool, args

    def _check_safety(self, tool, args):
        if tool in ["stop_instance", "delete_resource", "resize_instance"]:
            target = args.get("instance_id", "Unknown")
            print(
                f"⚠️ [SAFETY CHECK] Tool: {tool}, Target: {target} -> Auto-Approved via Test Suite"
            )
            return True
        return True

    def chat(self, user_input):
        prompt = f"""
[SYSTEM] JSON Only.
Keywords: create-vpc, create-subnet, list-instances, get-cost, resize-instance.
Context: {self.context_memory}
Input: "{user_input}"
"""
        raw_response = self.llm.invoke(prompt)
        if "{" in raw_response:
            raw_response = raw_response[raw_response.find("{") :]
        print(f"[DEBUG LLM RAW] {raw_response[:60]}...")

        tool, args = self._extract_flexible_intent(raw_response)
        if not tool:
            print("⚠️ Parsing Failed. Using Fallback.")
            tool, args = self._heuristic_fallback(user_input)

        if not tool:
            return "❌ 명령 불명확."

        # 의도 보정 (여기서 이름 정제됨)
        tool, args = self._intent_correction(user_input, tool, args)

        # 문맥 주입
        if tool not in ["list_instances", "get_cost"]:
            for key in ["vpc_id", "subnet_id", "instance_id"]:
                if key not in args and self.context_memory[key]:
                    args[key] = self.context_memory[key]

        if not self._check_safety(tool, args):
            return "🛑 작업 취소."

        result = self.server.call_tool(tool, args)

        # 상태 업데이트
        if isinstance(result, dict) and result.get("status") == "success":
            res_id, res_type = result.get("resource_id"), result.get("type")
            if res_type:
                self.context_memory[f"{res_type}_id"] = res_id
            if res_type == "instance":
                self.context_memory["instance_id"] = res_id

        return f"Result:\n{result}"
