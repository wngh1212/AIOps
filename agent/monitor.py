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
        # SOP Manager 초기화
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
                logger.error(f"scan error: {e}", exc_info=True)
                print(f"scan error: {e}")

            for _ in range(interval):
                if not self.is_running:
                    break
                time.sleep(1)

    def stop_monitoring(self):
        self.is_running = False
        print("\n모니터링 종료")
        logger.info("Monitoring stopped")

    def _run_scan(self):
        """인스턴스 목록 조회 및 모니터링"""
        try:
            inventory = self.server.call_tool("list_instances", {})

            # 빈 결과 검사
            if not inventory or "No instances" in inventory or "Error" in inventory:
                logger.debug("No instances found or error occurred")
                return

            # 파싱할 라인이 있는지 확인
            lines = inventory.split("\n")
            if not lines:
                logger.debug("Empty inventory response")
                return

            logger.debug(f"[Scan] Processing {len(lines)} lines")

            # 인스턴스별 처리
            found_any = False
            for line in lines:
                if "ID:" not in line:
                    continue

                try:
                    # 안전한 정규식 파싱
                    inst_id_match = re.search(r"ID: (i-[\w]+)", line)
                    name_match = re.search(r"Name: ([\w\-\s]+) \|", line)
                    state_match = re.search(r"State: (\w+)", line)
                    cpu_match = re.search(r"CPU: ([\d\.]+)%", line)

                    # 필수 값 확인
                    if not (inst_id_match and name_match and state_match):
                        logger.warning(f"Failed to parse line: {line}")
                        continue

                    inst_id = inst_id_match.group(1)
                    name = name_match.group(1).strip()
                    state = state_match.group(1)
                    cpu_val = float(cpu_match.group(1)) if cpu_match else 0.0

                    found_any = True
                    logger.debug(
                        f"[Scan] Found instance: {name} ({inst_id}) - State: {state}, CPU: {cpu_val}%"
                    )

                    # 임계값 기반 장애 감지
                    if state == "stopped":
                        logger.warning(f"[Incident] Instance stopped: {name}")
                        self._handle_incident(
                            0, inst_id, name, f"Stopped ({state})", "Service Outage"
                        )

                    elif state == "running" and cpu_val > 80.0:
                        logger.warning(
                            f"[Incident] High CPU detected: {name} ({cpu_val}%)"
                        )
                        self._handle_incident(
                            1, inst_id, name, f"High CPU ({cpu_val}%)", "Latency Risk"
                        )

                except Exception as e:
                    logger.error(f"Error processing line '{line}': {e}")
                    continue

            if not found_any:
                logger.debug("No valid instances found in inventory")

        except Exception as e:
            logger.error(f"[_run_scan] Critical error: {e}", exc_info=True)

    def _handle_incident(self, tier, instance_id, name, trigger, impact):
        """장애 감지 및 처리"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            f"[Incident Handler] {name} ({trigger}) detected - starting AI analysis"
        )
        print(f"\n장애 감지: {name} ({trigger}) -> AI 분석 시작...")

        try:
            logs = self.server.call_tool("get_recent_logs", {"id": instance_id})
        except Exception as e:
            logger.error(f"Failed to get logs for {instance_id}: {e}")
            logs = None

        # LLM 분석 및 의도 추출
        action, cause, reason = self._analyze_with_llm(name, trigger, logs)

        # 분석 결과가 없으면 중단
        if not action:
            logger.info(f"AI decided no action needed for {name}")
            print("AI has decided not to respond or withhold judgment.")
            return

        # 장애 전파
        emoji = "red" if tier == 0 else "orange"
        detect_msg = (
            f"[{emoji} 장애 감지 & 분석] {name}\n"
            f"- 트리거: {trigger}\n"
            f"- AI 판단: `{action}`\n"
            f"- 추정 원인: {cause}\n"
            f"- 근거: {reason}\n"
            f"- 상태: 조치 실행 중..."
        )

        self.slack.send(f"{emoji} 장애 감지", detect_msg)
        logger.info(f"[Slack] Incident alert sent for {name}")

        # 조치 실행
        result_msg = self._execute_action(action, instance_id)

        self.slack.send("조치 완료", f"대상: {name}\n결과: {result_msg}")
        logger.info(f"[Action Executed] {name}: {result_msg}")
        print(f"조치 완료: {result_msg}")

    def _analyze_with_llm(self, name, trigger, logs):
        """SOP 검색 + LLM 분석"""
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
            logger.debug(f"[LLM Response] {raw_response[:100]}...")

            # JSON 파싱 시도
            try:
                clean_json = (
                    raw_response.replace("```json", "").replace("```", "").strip()
                )
                match = re.search(r"(\{.*\})", clean_json, re.DOTALL)

                if match:
                    data = json.loads(match.group(1))
                    action = data.get("action")
                    root_cause = data.get("root_cause")
                    reason = data.get("reason")
                    logger.info(f"[JSON Parsed] Action: {action}")
                    return action, root_cause, reason

            except json.JSONDecodeError as e:
                logger.warning(f"JSON 파싱 실패: {e}")
                logger.debug(f"Raw response: {raw_response[:200]}...")

            # 텍스트 분석으로 의도 추출
            action = self._extract_action_from_text(raw_response)
            if action:
                logger.info(f"[Text Analysis] Action extracted: {action}")
                return (
                    action,
                    "AI Text Analyzed (JSON Format Error)",
                    "Detect keywords in text",
                )

            logger.warning(f"[LLM Analysis] No action determined")
            return None, None, None

        except Exception as e:
            logger.error(f"LLM 분석 실패: {e}", exc_info=True)
            return None, None, None

    def _extract_action_from_text(self, raw_response):
        """더 정교한 텍스트 기반 의도 추출"""
        text = raw_response.upper()

        # 부정형 제거
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
                logger.info(f"[Action] Started instance: {instance_id}")
                return "인스턴스 시작됨"

            elif action == "REBOOT_INSTANCE":
                self.server.call_tool(
                    "execute_aws_action",
                    {
                        "action_name": "reboot_instances",
                        "params": {"InstanceIds": [instance_id]},
                    },
                )
                logger.info(f"[Action] Rebooted instance: {instance_id}")
                return "인스턴스 재부팅됨"

            elif action == "ADVISE_SCALE_UP":
                logger.info(f"[Action] Scale-up advised for: {instance_id}")
                return "스케일업 권고 (자동 조치 없음)"

            elif action == "MANUAL_CHECK":
                logger.warning(f"[Action] Manual check required for: {instance_id}")
                return "수동 점검 필요 (자동 조치 위험)"

            else:
                return f"알 수 없는 액션: {action}"

        except Exception as e:
            logger.error(f"액션 실행 실패 ({action}): {e}", exc_info=True)
            return f"액션 실행 오류: {str(e)}"
