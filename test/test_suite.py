import os
import sys
import time
import unittest
from unittest.mock import patch

from langchain_ollama import OllamaLLM

# ----------------------------------------------------------------
# [경로 설정 수정] 프로젝트 루트를 찾아 sys.path에 추가
# ----------------------------------------------------------------
# 1. 현재 파일(test_suite.py)의 절대 경로를 구합니다. (예: .../aiOps/test)
current_dir = os.path.dirname(os.path.abspath(__file__))

# 2. 부모 디렉토리(프로젝트 루트)를 구합니다. (예: .../aiOps)
project_root = os.path.dirname(current_dir)

# 3. 프로젝트 루트가 sys.path에 없으면 추가합니다.
# 이렇게 해야 'agent'와 'MCPserver' 패키지를 찾을 수 있습니다.
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from agent.aiOps import ChatOpsClient
    from MCPserver.MCPserver import MCPServer
except ImportError as e:
    print(
        f"❌ Import Error: 모듈을 찾을 수 없습니다.\n프로젝트 루트: {project_root}\n에러 메시지: {e}"
    )
    sys.exit(1)


class TestAIOpsScenarios(unittest.TestCase):
    """
    AIOps 4단계 기능 검증 테스트 스위트
    Phase 1: 구축 (Context 유지)
    Phase 2: 관측 (강제 조회 로직)
    Phase 3: 운영 (FinOps 및 의도 보정)
    Phase 4: 안전 (Human-in-the-Loop 검증)
    """

    @classmethod
    def setUpClass(cls):
        print("\n[Setup] 시스템 초기화 중...")
        cls.server = MCPServer()
        cls.llm = OllamaLLM(model="llama2:7b")
        cls.agent = ChatOpsClient(cls.server, cls.llm)

        # 테스트 간 공유할 리소스 ID
        cls.vpc_id = None
        cls.subnet_id = None
        cls.instance_id = None

    def _log_step(self, step_name, user_input, response):
        print(f"\n--------------------------------------------------")
        print(f"[TEST] {step_name}")
        print(f'Input: "{user_input}"')
        print(f"Response:\n{response}")
        print(f"--------------------------------------------------")

    # =================================================================
    # Phase 1. Infrastructure Build (문맥 유지 테스트)
    # =================================================================
    def test_01_context_build(self):
        print("\n[Phase 1] 인프라 구축 및 문맥 유지 테스트 시작")

        # 1-1. VPC 생성
        query = "Create a new VPC with CIDR 10.20.0.0/16"
        res = self.agent.chat(query)
        self._log_step("Create VPC", query, res)

        # 메모리에 VPC ID가 저장되었는지 검증
        self.assertIsNotNone(
            self.agent.context_memory["vpc_id"],
            "❌ VPC ID가 메모리에 저장되지 않았습니다.",
        )
        self.vpc_id = self.agent.context_memory["vpc_id"]

        # 1-2. 서브넷 생성 (VPC ID 언급 없이 'that VPC'로 추론)
        query = "Add a subnet to that VPC with CIDR 10.20.1.0/24"
        res = self.agent.chat(query)
        self._log_step("Create Subnet (Context)", query, res)

        self.assertIsNotNone(
            self.agent.context_memory["subnet_id"],
            "❌ Subnet ID가 메모리에 저장되지 않았습니다.",
        )

        # 1-3. 인스턴스 생성
        query = "Launch a t2.nano instance named 'Test-Auto-Bot' in the subnet"
        res = self.agent.chat(query)
        self._log_step("Create Instance", query, res)

        self.assertIsNotNone(
            self.agent.context_memory["instance_id"],
            "❌ Instance ID가 메모리에 저장되지 않았습니다.",
        )
        self.instance_id = self.agent.context_memory["instance_id"]

        # 인스턴스 부팅 대기
        print("인스턴스 초기화 대기 중 (10초)...")
        time.sleep(10)

    # =================================================================
    # Phase 2. Observability & Status (강제 조회 로직 테스트)
    # =================================================================
    def test_02_observability(self):
        print("\n[Phase 2] 모니터링 및 강제 조회 로직 테스트 시작")

        # 2-1. 전체 조회 (running 키워드 없이도 전체가 나와야 함)
        query = "Show instances"
        res = self.agent.chat(query)
        self._log_step("List Instances (Force All)", query, res)

        # 검증: 결과에 'ID:' 또는 'Test-Auto-Bot'이 포함되어야 함
        self.assertTrue(
            "ID:" in res or "No instances" in res,
            "❌ 목록 조회가 실패했거나 포맷이 올바르지 않습니다.",
        )

        # 2-2. 토폴로지
        query = "Show me the current infrastructure topology"
        res = self.agent.chat(query)
        self._log_step("Topology", query, res)
        self.assertTrue("VPC:" in res, "❌ 토폴로지 트리가 출력되지 않았습니다.")

        # 2-3. 메트릭 조회 (이름으로 조회)
        query = "Check CPU utilization for 'Test-Auto-Bot'"
        res = self.agent.chat(query)
        self._log_step("Get Metric", query, res)
        self.assertTrue(
            "CPUUtilization" in res or "No data" in res, "❌ 메트릭 조회 실패"
        )

    # =================================================================
    # Phase 3. Operations & FinOps (기능 및 오타 보정 테스트)
    # =================================================================
    def test_03_operations(self):
        print("\n[Phase 3] 운영 및 FinOps 테스트 시작")

        # 3-1. 비용 조회
        query = "How much is my estimated cost this month?"
        res = self.agent.chat(query)
        self._log_step("Check Cost", query, res)
        self.assertTrue(
            "$" in res or "비용" in res or "fail" in res,
            "❌ 비용 조회 응답 형식이 아닙니다.",
        )

        # 3-2. 스냅샷 생성
        query = "Create a snapshot for Test-Auto-Bot"
        res = self.agent.chat(query)
        self._log_step("Create Snapshot", query, res)
        self.assertTrue("Snapshot Started" in res, "❌ 스냅샷 생성 실패")

    # =================================================================
    # Phase 4. Safety & Human-in-the-Loop (사용자 승인 테스트)
    # =================================================================
    @patch(
        "builtins.input", return_value="yes"
    )  # 사용자가 'yes'를 입력했다고 가정 (Mocking)
    def test_04_safety_checks(self, mock_input):
        print("\n[Phase 4] 안전장치(Human-in-the-Loop) 테스트 시작")

        # 4-1. 리사이징 (승인 필요)
        # 실제로는 input() 함수가 호출되지만, 위 데코레이터(@patch) 덕분에 자동으로 'yes'가 입력됨
        query = "Change the type of 'Test-Auto-Bot' to t3.small"
        res = self.agent.chat(query)
        self._log_step("Resize Instance (with Auto-Approve)", query, res)

        self.assertTrue(
            "Resized" in res or "stopped" in res, "❌ 리사이징이 수행되지 않았습니다."
        )

        # 4-2. 인스턴스 정지 (승인 필요)
        query = "Stop the instance 'Test-Auto-Bot'"
        res = self.agent.chat(query)
        self._log_step("Stop Instance (with Auto-Approve)", query, res)
        self.assertTrue("Stopping" in res, "❌ 인스턴스 정지가 수행되지 않았습니다.")

        # 4-3. 삭제 (승인 필요)
        # 마지막으로 리소스를 정리합니다.
        query = "Delete the resource 'Test-Auto-Bot'"
        res = self.agent.chat(query)
        self._log_step("Delete Instance (with Auto-Approve)", query, res)
        self.assertTrue(
            "Terminating" in res or "Deleted" in res,
            "❌ 인스턴스 삭제가 수행되지 않았습니다.",
        )

    @classmethod
    def tearDownClass(cls):
        print("\n[Finish] 모든 테스트 시나리오 종료")
        print("남은 리소스(VPC, Subnet)는 'cleanup_aws.py'를 통해 정리해주세요.")


if __name__ == "__main__":
    # unittest 실행
    unittest.main()
