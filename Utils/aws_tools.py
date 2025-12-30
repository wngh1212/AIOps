import sys
import time
from datetime import datetime, timedelta, timezone
from io import StringIO

import boto3


class AWSTools:
    def __init__(self, region="ap-northeast-2"):
        self.region = region

        # 자주 쓰는 클라이언트 미리 로드 (코드 실행 시 사용)
        self.ec2 = boto3.client("ec2", region_name=region)
        self.cw = boto3.client("cloudwatch", region_name=region)
        self.logs = boto3.client("logs", region_name=region)
        self.rds = boto3.client("rds", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)

        # 리소스 객체 (편의성)
        self.ec2_res = boto3.resource("ec2", region_name=region)

    def execute_python_code(self, code_str):
        """
        [Universal Executor]
        LLM이 생성한 Python 코드를 샌드박스(제한적) 환경에서 실행하고 결과 출력값을 반환
        """
        # 표준 출력 캡처 준비
        old_stdout = sys.stdout
        redirected_output = sys.stdout = StringIO()

        # 코드 내에서 사용할 수 있는 전역 객체 정의
        exec_globals = {
            "boto3": boto3,
            "ec2": self.ec2,
            "rds": self.rds,
            "s3": self.s3,
            "cw": self.cw,
            "print": print,
            "time": time,
            "datetime": datetime,
        }

        try:
            print(f"\n[System] Executing Generated Code...\n")
            # 코드 실행
            exec(code_str, exec_globals)

            # 결과 캡처
            sys.stdout = old_stdout
            output = redirected_output.getvalue()
            return output if output.strip() else "Success (No output printed)."

        except Exception as e:
            sys.stdout = old_stdout
            return f"❌ Code Execution Error: {str(e)}"

    def get_inventory(self):
        # 기존 모니터링용 로직 유지
        try:
            response = self.ec2.describe_instances()
            inventory = []
            now = datetime.now(timezone.utc)

            if not response["Reservations"]:
                return "No instances found."

            for resv in response["Reservations"]:
                for inst in resv["Instances"]:
                    instance_id = inst["InstanceId"]
                    # Name 태그 추출
                    name = "Unknown"
                    if "Tags" in inst:
                        for t in inst["Tags"]:
                            if t["Key"] == "Name":
                                name = t["Value"]
                                break

                    state = inst["State"]["Name"]

                    # CPU 메트릭 조회 (최근 5분)
                    cpu_val = 0.0
                    if state == "running":
                        try:
                            stats = self.cw.get_metric_statistics(
                                Namespace="AWS/EC2",
                                MetricName="CPUUtilization",
                                Dimensions=[
                                    {"Name": "InstanceId", "Value": instance_id}
                                ],
                                StartTime=now - timedelta(minutes=10),
                                EndTime=now,
                                Period=300,
                                Statistics=["Average"],
                            )
                            if stats["Datapoints"]:
                                cpu_val = round(stats["Datapoints"][0]["Average"], 2)
                        except:
                            pass

                    inventory.append(
                        f"ID: {instance_id} | Name: {name} | State: {state} | CPU: {cpu_val}%"
                    )

            return "\n".join(inventory)
        except Exception as e:
            return f"Error getting inventory: {e}"

    def get_recent_logs(self, instance_id, lines=50):
        # 더미 로그 혹은 CloudWatch Logs 연동
        # 여기서는 단순 예시 텍스트 반환 (실제 구현 시 SSM이나 CW Logs 호출)
        return f"[Mock Log] System logs for {instance_id}: No critical errors found."
