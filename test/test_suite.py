import csv
import os
import re
import sys
import time
import unittest
import uuid
from datetime import datetime

from langchain_ollama import OllamaLLM

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from agent.aiOps import ChatOpsClient
    from MCPserver.MCPserver import MCPServer
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

# 파일 경로 설정
REPORT_FILE = os.path.join(current_dir, "comprehensive_test_report.txt")
METRIC_FILE = os.path.join(current_dir, "performance_metrics.csv")


class TestComprehensiveE2E(unittest.TestCase):
    test_results = []
    shared_resources = {
        "vpc_id": None,
        "subnet_id": None,
        "sg_id": None,
        "instance_id": None,
    }

    @classmethod
    def setUpClass(cls):
        print("\nInitializing System for E2E Test...")
        cls.server = MCPServer()
        cls.llm = OllamaLLM(model="llama2:7b")
        cls.agent = ChatOpsClient(cls.server, cls.llm)

        # CSV 헤더 초기화 (파일이 없으면 생성)
        if not os.path.exists(METRIC_FILE):
            with open(METRIC_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "Step", "Duration(s)", "Status"])

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(f"Test Report - {datetime.now()}\n{'=' * 60}\n")

    def _record_metric(self, step_name, duration, success):
        """성능 지표를 CSV에 누적 기록"""
        status = "PASS" if success else "FAIL"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(METRIC_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, step_name, duration, status])

    def _record_result(self, step_name, success, message):
        status = "PASS" if success else "FAIL"
        print(f"\n{status} [{step_name}] -> {message}")
        self.test_results.append(
            {"step": step_name, "status": status, "message": message}
        )

    def _ask_agent(self, prompt, step_name):
        print(f"\n[Command] {prompt}")
        start_time = time.time()

        try:
            response = self.agent.chat(prompt)
            success = "Error" not in response and "Exception" not in response
        except Exception:
            response = "System Error"
            success = False

        duration = round(time.time() - start_time, 2)

        # 지표 기록
        self._record_metric(step_name, duration, success)

        log_entry = f"Step: {step_name}\nTime: {duration}s\nPrompt: {prompt}\nResponse: {response}\n{'-' * 40}\n"
        with open(REPORT_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)

        return response

    def test_01_sop_search(self):
        step = "SOP Search"
        prompt = "What to do if a server has high CPU usage? Find SOP."
        response = self._ask_agent(prompt, step)

        if "high cpu" in response.lower() or "snapshot" in response.lower():
            self._record_result(step, True, "SOP found.")
        else:
            self._record_result(step, False, "SOP not found.")

    def test_02_create_vpc(self):
        step = "Create VPC"
        # 프롬프트 단순화 (오류 감소 유도)
        prompt = "Create a VPC with cidr 10.50.0.0/16. Print the vpc id."
        response = self._ask_agent(prompt, step)

        match = re.search(r"(vpc-[a-z0-9]+)", response)
        if match:
            self.shared_resources["vpc_id"] = match.group(1)
            self._record_result(step, True, f"ID: {match.group(1)}")
        else:
            self._record_result(step, False, "VPC ID missing.")
            self.fail("Critical: VPC creation failed.")

    def test_03_create_subnet(self):
        step = "Create Subnet"
        vpc_id = self.shared_resources["vpc_id"]
        prompt = f"Create a subnet in '{vpc_id}' with cidr 10.50.1.0/24. Print the subnet id."
        response = self._ask_agent(prompt, step)

        match = re.search(r"(subnet-[a-z0-9]+)", response)
        if match:
            self.shared_resources["subnet_id"] = match.group(1)
            self._record_result(step, True, f"ID: {match.group(1)}")
        else:
            self._record_result(step, False, "Subnet ID missing.")

    def test_04_create_security_group(self):
        step = "Create SG"
        vpc_id = self.shared_resources["vpc_id"]
        prompt = (
            f"Create a security group in '{vpc_id}' named 'E2E-SG'. Print the group id."
        )
        response = self._ask_agent(prompt, step)

        match = re.search(r"(sg-[a-z0-9]+)", response)
        if match:
            self.shared_resources["sg_id"] = match.group(1)
            self._record_result(step, True, f"ID: {match.group(1)}")
        else:
            self._record_result(step, False, "SG ID missing.")

    def test_05_create_s3(self):
        step = "Create S3"
        bucket_name = f"e2e-test-{uuid.uuid4().hex[:6]}"
        prompt = f"Create an S3 bucket named '{bucket_name}' in ap-northeast-2. Print 'Success'."
        response = self._ask_agent(prompt, step)

        if "Success" in response or "created" in response.lower():
            self._record_result(step, True, "Bucket created.")
        else:
            self._record_result(step, False, "Bucket creation unconfirmed.")


if __name__ == "__main__":
    unittest.main(failfast=False)
