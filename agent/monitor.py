import json
import logging
import re
import time
from datetime import datetime

from Utils.slack import SlackNotifier
from Utils.sop_manager import SOPManager

logger = logging.getLogger(__name__)


class MonitorAgent:
    def __init__(self, mcp_server, llm, slack_url=None, sop_file="SOP/sop.yaml"):
        self.server = mcp_server
        self.llm = llm
        self.slack = SlackNotifier(slack_url)
        self.sop_manager = SOPManager(sop_file)
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
                logger.error(f"스캔 오류: {e}", exc_info=True)

            for _ in range(interval):
                if not self.is_running:
                    break
                time.sleep(1)

    def stop_monitoring(self):
        self.is_running = False
        print("\n모니터링 종료")

    def _run_scan(self):
        inventory = self.server.call_tool("list_instances", {})

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
            except Exception as e:
                logger.warning(f"Failed to parse inventory line: {e}")
                continue

    def _handle_incident(self, tier, instance_id, name, trigger, impact):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n장애 감지: {name} ({trigger}) -> AI 분석 시작...")

        logs = self.server.call_tool("get_recent_logs", {"id": instance_id})

        # LLM 분석 및 의도 추출
        action, cause, reason = self._analyze_with_llm(name, trigger, logs)

        # 분석 결과가 없으면 중단 -> 억지로 규칙 적용 X
        if not action:
            logger.info(f"AI가 {name}에 대해 대응 불필요 또는 판단 보류를 결정")
            print("AI가 대응 불필요 또는 판단 보류를 결정")
            return

        # 장애 전파!!
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
        # SOP 검색 + LLM 분석
        try:
            # YAML 기반 SOP 검색
            related_sops = self.sop_manager.search_guideline(
                f"{trigger} {name}", n_results=3
            )

            # 복수 결과를 문맥에 포함시키기
            sop_context = ""
            if related_sops and isinstance(related_sops, list):
                sop_context = "\n[RELATED SOPs]\n"
                for idx, sop in enumerate(related_sops, 1):
                    rule_id = sop.get("rule_id", "Unknown")
                    content = sop.get("content", "")
                    confidence = sop.get("confidence", 0.0)
                    sop_context += (
                        f"{idx}. [{rule_id}] (신뢰도: {confidence:.2f})\n{content}\n\n"
                    )

            prompt = f"""[ROLE] Senior AWS SRE.
[GOAL] Recover service based on logs and SOP guidelines.
[INCIDENT] {name}, {trigger}
[LOGS] {logs[-500:] if logs else "No logs available"}
{sop_context}

[AVAILABLE ACTIONS]
1. START_INSTANCE (If stopped and safe to start)
2. REBOOT_INSTANCE (If hung/stuck/high cpu)
3. ADVISE_SCALE_UP (If OOM/Memory error)
4. MANUAL_CHECK (If logs show critical data corruption or unknown error)

[OUTPUT]
JSON format: {{"action": "ACTION_NAME", "root_cause": "summary", "reason": "logic"}}
"""

            raw_response = self.llm.invoke(prompt)

            # JSON 파싱 시도 실패 시 텍스트 내 키워드 검색
            try:
                clean_json = (
                    raw_response.replace("```json", "").replace("```", "").strip()
                )
                match = re.search(r"(\{.*\})", clean_json, re.DOTALL)

                if match:
                    data = json.loads(match.group(1))
                    return (
                        data.get("action"),
                        data.get("root_cause"),
                        data.get("reason"),
                    )

            except json.JSONDecodeError as e:
                logger.warning(f"JSON 파싱 실패: {e}")
                logger.debug(f"Raw response: {raw_response[:100]}...")

            # 텍스트 분석으로 의도 추출
            action = self._extract_action_from_text(raw_response)
            if action:
                # 원인과 근거는 추출하기 어려워서 Raw 텍스트의 앞부분을 사용
                return (
                    action,
                    "AI 텍스트 분석됨 (JSON 포맷 에러)",
                    "텍스트 내 키워드 감지",
                )

            return None, None, None

        except Exception as e:
            logger.error(f"LLM 분석 실패: {e}", exc_info=True)
            return None, None, None

    def _extract_action_from_text(self, raw_response):
        """더 정교한 텍스트 기반 의도 추출"""
        text = raw_response.upper()

        # 부정형 제거 (예: "DON'T START" -> None 반환)
        if any(w in text for w in ["NOT", "SHOULD NOT", "DONT", "CANNOT", "DO NOT"]):
            if "START" in text:
                return None

        # 긍정형 액션 추출
        action_keywords = {
            "START_INSTANCE": ["START", "BEGIN", "BOOT", "LAUNCH"],
            "REBOOT_INSTANCE": ["REBOOT", "RESTART", "RESTARTING"],
            "ADVISE_SCALE_UP": ["SCALE", "UPGRADE", "INCREASE", "RESIZE"],
            "MANUAL_CHECK": ["CHECK", "INVESTIGATE", "REVIEW", "MANUAL"],
        }

        for action, keywords in action_keywords.items():
            if any(kw in text for kw in keywords):
                return action

        return None

    def _execute_action(self, action, instance_id):
        """결정된 액션 실행"""
        try:
            if action == "START_INSTANCE":
                self.server.call_tool(
                    "execute_aws_action",
                    {
                        "action_name": "start_instances",
                        "params": {"InstanceIds": [instance_id]},
                    },
                )
                logger.info(f"Started instance: {instance_id}")
                return "인스턴스 시작됨"

            elif action == "REBOOT_INSTANCE":
                self.server.call_tool(
                    "execute_aws_action",
                    {
                        "action_name": "reboot_instances",
                        "params": {"InstanceIds": [instance_id]},
                    },
                )
                logger.info(f"Rebooted instance: {instance_id}")
                return "인스턴스 재부팅됨"

            elif action == "ADVISE_SCALE_UP":
                logger.info(f"Scale-up advised for: {instance_id}")
                return "스케일업 권고 (자동 조치 없음)"

            elif action == "MANUAL_CHECK":
                logger.warning(f"Manual check required for: {instance_id}")
                return "수동 점검 필요 (자동 조치 위험)"

            else:
                return f"알 수 없는 액션: {action}"

        except Exception as e:
            logger.error(f"액션 실행 실패 ({action}): {e}", exc_info=True)
            return f"액션 실행 오류: {str(e)}"
