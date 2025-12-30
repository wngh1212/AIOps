import json
import re
import time
from datetime import datetime

from Utils.slack import SlackNotifier


class MonitorAgent:
    def __init__(self, mcp_server, llm, slack_url=None):
        self.server = mcp_server
        self.llm = llm
        self.slack = SlackNotifier(slack_url)
        self.is_running = False

    def start_monitoring(self, interval=30):
        self.is_running = True
        msg = f"[AIOps] 지능형 인프라 감시 가동 (주기: {interval}초)\n"
        print(f"\n{msg}")
        if self.slack.webhook_url:
            self.slack.send("System Notification", msg)

        while self.is_running:
            try:
                self._run_scan()
            except Exception as e:
                print(f"스캔 오류: {e}")

            for _ in range(interval):
                if not self.is_running:
                    break
                time.sleep(1)

    def stop_monitoring(self):
        self.is_running = False
        print("\n모니터링 종료")

    def _run_scan(self):
        inventory = self.server.call_tool("list_instances")
        if "No instances" in inventory or "Error" in inventory:
            return

        for line in inventory.split("\n"):
            if "ID:" not in line:
                continue
            try:
                inst_id = re.search(r"ID: (i-[\w]+)", line).group(1)
                name = re.search(r"Name: ([\w\-\s]+) \|", line).group(1).strip()
                state = re.search(r"State: (\w+)", line).group(1)
                cpu_match = re.search(r"CPU: ([\d\.]+)%", line)
                cpu_val = float(cpu_match.group(1)) if cpu_match else 0.0

                if state == "stopped":
                    self._handle_incident(
                        0, inst_id, name, f"Stopped ({state})", "Service Outage"
                    )
                elif state == "running" and cpu_val > 80.0:
                    self._handle_incident(
                        1, inst_id, name, f"High CPU ({cpu_val}%)", "Latency Risk"
                    )
            except:
                continue

    def _handle_incident(self, tier, instance_id, name, trigger, impact):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n장애 감지: {name} ({trigger}) -> AI 분석 시작...")

        logs = self.server.call_tool("get_recent_logs", {"id": instance_id})

        #  LLM 분석 및 의도 추출
        action, cause, reason = self._analyze_with_llm(name, trigger, logs)

        # 분석 결과가 없으면 중단 -> 억지로 규칙 적용 X
        if not action:
            print("AI가 대응 불필요 또는 판단 보류를 결정했습니다.")
            return

        # 4. 장애 전파 (분석 결과 포함)
        emoji = "!!!" if tier == 0 else "!!!"
        detect_msg = (
            f"[{emoji} 장애 감지 & 분석] {name}\n"
            f"- 트리거: {trigger}\n"
            f"- AI 판단: `{action}`\n"
            f"- 추정 원인: {cause}\n"
            f"- 근거: {reason}\n"
            f"- 상태: 조치 실행 중..."
        )
        self.slack.send(f"{emoji} 장애 감지", detect_msg)

        # 조치 실행
        result_msg = self._execute_action(action, instance_id)

        self.slack.send("조치 완료", f"대상: {name}\n결과: {result_msg}")
        print(f"조치 완료: {result_msg}")

    def _analyze_with_llm(self, name, trigger, logs):
        related_sop = self.sop_manager.search_guideline(f"{trigger} {name}")
        """
        LLM에게 상황을 판단하게 하고, JSON 파싱 실패 시 텍스트에서 의도를 추출합니다.
        """
        prompt = f"""
        [ROLE] Senior AWS SRE.
        [GOAL] Recover service based on logs.
        [INCIDENT] {name}, {trigger}
        [LOGS] {logs[-500:]}

        [AVAILABLE ACTIONS]
        1. START_INSTANCE (If stopped and safe to start)
        2. REBOOT_INSTANCE (If hung/stuck/high cpu)
        3. ADVISE_SCALE_UP (If OOM/Memory error)
        4. MANUAL_CHECK (If logs show critical data corruption or unknown error)

        [OUTPUT]
        JSON format: {{ "action": "ACTION_NAME", "root_cause": "summary", "reason": "logic" }}
        """

        raw_response = self.llm.invoke(prompt)

        # JSON 파싱 시도 실패 시 텍스트 내 키워드 검색

        try:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r"(\{.*\})", clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                return data.get("action"), data.get("root_cause"), data.get("reason")
        except:
            pass

        print(
            f"JSON 파싱 실패. 답변 텍스트에서 의도를 추출합니다.\nRaw: {raw_response[:100]}..."
        )

        action = None
        if "START_INSTANCE" in raw_response:
            action = "START_INSTANCE"
        elif "REBOOT_INSTANCE" in raw_response:
            action = "REBOOT_INSTANCE"
        elif "ADVISE_SCALE_UP" in raw_response:
            action = "ADVISE_SCALE_UP"
        elif "MANUAL_CHECK" in raw_response:
            action = "MANUAL_CHECK"

        if action:
            # 원인과 근거는 추출하기 어려우니 Raw 텍스트의 앞부분을  사용
            return action, "AI 텍스트 분석됨 (JSON 포맷 에러)", "텍스트 내 키워드 감지"

        return None, None, None

    def _execute_action(self, action, instance_id):
        if action == "START_INSTANCE":
            self.server.call_tool(
                "execute_aws_action",
                {
                    "action_name": "start_instances",
                    "params": {"InstanceIds": [instance_id]},
                },
            )
            return "인스턴스 시작됨"
        elif action == "REBOOT_INSTANCE":
            self.server.call_tool(
                "execute_aws_action",
                {
                    "action_name": "reboot_instances",
                    "params": {"InstanceIds": [instance_id]},
                },
            )
            return "인스턴스 재부팅됨"
        elif action == "ADVISE_SCALE_UP":
            return "스케일업 권고 (자동 조치 없음)"
        elif action == "MANUAL_CHECK":
            return "수동 점검 필요 (자동 조치 위험)"
        return f"알 수 없는 액션: {action}"
