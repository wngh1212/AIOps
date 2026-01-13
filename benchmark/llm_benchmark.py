import csv
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, List, Tuple

import requests

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# 테스트 케이스 135개
TEST_CASES = [
    # ===== Instance 상태 관리 (18개) - 명시적 도구 사용 =====
    (
        "test_001",
        "instance",
        "Launch a t2.micro instance",
        "create_instance",
        ["instance_type"],
    ),
    (
        "test_002",
        "instance",
        "Create a new instance named web-server with t2.small",
        "create_instance",
        ["name", "instance_type"],
    ),
    (
        "test_003",
        "instance",
        "Make an instance for production",
        "create_instance",
        ["name"],
    ),
    ("test_004", "instance", "Show all instances", "list_instances", []),
    ("test_005", "instance", "List running instances", "list_instances", []),
    # 명시적 start_instances 도구
    ("test_006", "instance", "Start web-server", "start_instances", ["instance_id"]),
    (
        "test_007",
        "instance",
        "Start the database instance",
        "start_instances",
        ["name"],
    ),
    (
        "test_008",
        "instance",
        "Start i-0123456789abcdef",
        "start_instances",
        ["instance_id"],
    ),
    # 명시적 stop_instances 도구
    ("test_009", "instance", "Stop web-server", "stop_instances", ["instance_id"]),
    ("test_010", "instance", "Stop the database instance", "stop_instances", ["name"]),
    ("test_011", "instance", "Stop i-abcd1234", "stop_instances", ["instance_id"]),
    # 명시적 reboot_instances 도구
    ("test_012", "instance", "Reboot web-server", "reboot_instances", ["instance_id"]),
    ("test_013", "instance", "Reboot the app server", "reboot_instances", ["name"]),
    (
        "test_014",
        "instance",
        "Reboot i-xyz123 instance",
        "reboot_instances",
        ["instance_id"],
    ),
    # terminate_resource 도구
    (
        "test_015",
        "instance",
        "Terminate i-0123456789abcdef",
        "terminate_resource",
        ["instance_id"],
    ),
    (
        "test_016",
        "instance",
        "Delete the web-server instance",
        "terminate_resource",
        ["name"],
    ),
    (
        "test_017",
        "instance",
        "Terminate the old-app instance",
        "terminate_resource",
        ["name"],
    ),
    (
        "test_018",
        "instance",
        "Terminate resource i-xyz123",
        "terminate_resource",
        ["instance_id"],
    ),
    # Instance 크기 조정 6개
    (
        "test_019",
        "instance",
        "Resize i-0123456789abcdef to t2.large",
        "resize_instance",
        ["instance_id", "instance_type"],
    ),
    (
        "test_020",
        "instance",
        "Change instance type of my-server to t3.xlarge",
        "resize_instance",
        ["name", "instance_type"],
    ),
    (
        "test_021",
        "instance",
        "Scale up AIOpsmake to t3.large",
        "resize_instance",
        ["name", "instance_type"],
    ),
    (
        "test_022",
        "instance",
        "Resize web-server instance to t2.medium",
        "resize_instance",
        ["name", "instance_type"],
    ),
    (
        "test_023",
        "instance",
        "Change i-abc123 type to t3.small",
        "resize_instance",
        ["instance_id", "instance_type"],
    ),
    (
        "test_024",
        "instance",
        "Upgrade prod-db to t3.xlarge",
        "resize_instance",
        ["name", "instance_type"],
    ),
    # 스냅샷 관ㅣㄹ 6개
    (
        "test_025",
        "instance",
        "Create a snapshot of i-0123456789abcdef",
        "create_snapshot",
        ["instance_id"],
    ),
    ("test_026", "instance", "Backup my-app-server", "create_snapshot", ["name"]),
    (
        "test_027",
        "instance",
        "Create snapshot of web-server",
        "create_snapshot",
        ["name"],
    ),
    (
        "test_028",
        "instance",
        "Take snapshot from i-xyz789",
        "create_snapshot",
        ["instance_id"],
    ),
    (
        "test_029",
        "instance",
        "Backup the database instance",
        "create_snapshot",
        ["name"],
    ),
    (
        "test_030",
        "instance",
        "Create snapshot of AIOpsmake",
        "create_snapshot",
        ["name"],
    ),
    # 네트워크 관리 12개
    (
        "test_031",
        "network",
        "Create a VPC with CIDR 10.0.0.0/16",
        "create_vpc",
        ["cidr"],
    ),
    ("test_032", "network", "Create a new VPC", "create_vpc", []),
    (
        "test_033",
        "network",
        "Create production-vpc with 172.16.0.0/16",
        "create_vpc",
        ["cidr"],
    ),
    (
        "test_034",
        "network",
        "Create a subnet in vpc-12345678 with CIDR 10.0.1.0/24",
        "create_subnet",
        ["vpc_id", "cidr"],
    ),
    ("test_035", "network", "Add a subnet to my VPC", "create_subnet", []),
    (
        "test_036",
        "network",
        "Create subnet 10.0.2.0/24 in vpc-abc123",
        "create_subnet",
        ["vpc_id", "cidr"],
    ),
    ("test_037", "network", "Show network topology", "generate_topology", []),
    ("test_038", "network", "Generate VPC topology", "generate_topology", []),
    (
        "test_039",
        "network",
        "Display the infrastructure layout",
        "generate_topology",
        [],
    ),
    ("test_040", "network", "What is the network structure", "generate_topology", []),
    ("test_041", "network", "Create VPC with name production-vpc", "create_vpc", []),
    ("test_042", "network", "Set up subnet in default VPC", "create_subnet", []),
    # 모니터링 및 메트릭 18개
    (
        "test_043",
        "monitoring",
        "What is the CPU usage of i-0123456789abcdef",
        "get_metric",
        ["instance_id"],
    ),
    (
        "test_044",
        "monitoring",
        "Get CPU utilization for my-server",
        "get_metric",
        ["name"],
    ),
    (
        "test_045",
        "monitoring",
        "Check CPU metric for web-server",
        "get_metric",
        ["name"],
    ),
    (
        "test_046",
        "monitoring",
        "Get metrics for i-abc123",
        "get_metric",
        ["instance_id"],
    ),
    (
        "test_047",
        "monitoring",
        "Get CPUUtilization metric from i-12345",
        "get_metric",
        ["instance_id", "metric_name"],
    ),
    (
        "test_048",
        "monitoring",
        "Check NetworkIn for my-app-instance",
        "get_metric",
        ["name", "metric_name"],
    ),
    (
        "test_049",
        "monitoring",
        "Monitor web-server performance",
        "get_metric",
        ["name"],
    ),
    ("test_050", "monitoring", "Instance CPU usage", "get_metric", []),
    (
        "test_051",
        "monitoring",
        "Show recent logs of i-xyz",
        "get_recent_logs",
        ["instance_id"],
    ),
    (
        "test_052",
        "monitoring",
        "Retrieve logs from web-server",
        "get_recent_logs",
        ["name"],
    ),
    (
        "test_053",
        "monitoring",
        "Get logs from database instance",
        "get_recent_logs",
        ["name"],
    ),
    ("test_054", "monitoring", "Display instance logs", "get_recent_logs", []),
    (
        "test_055",
        "monitoring",
        "Fetch logs from i-prod123",
        "get_recent_logs",
        ["instance_id"],
    ),
    ("test_056", "monitoring", "Check instance health", "get_metric", []),
    ("test_057", "monitoring", "Monitor instances", "list_instances", []),
    (
        "test_058",
        "monitoring",
        "Get performance metrics of web server",
        "get_metric",
        ["name"],
    ),
    (
        "test_059",
        "monitoring",
        "What is i-0123456789abcdef doing",
        "get_metric",
        ["instance_id"],
    ),
    ("test_060", "monitoring", "Get instance info", "list_instances", []),
    # 비용 관리 20개 Cost Trend 포함
    ("test_061", "cost", "What is my monthly cost", "get_cost", []),
    ("test_062", "cost", "Show AWS billing", "get_cost", []),
    ("test_063", "cost", "How much have I spent", "get_cost", []),
    ("test_064", "cost", "Get cost estimate", "get_cost", []),
    ("test_065", "cost", "Calculate my bill", "get_cost", []),
    # Cost Trend 분석
    (
        "test_066",
        "cost",
        "analyze cost trend for last 3 months",
        "analyze_cost_trend",
        [],
    ),
    (
        "test_067",
        "cost",
        "analyze cost trend for last 3 month",
        "analyze_cost_trend",
        [],
    ),
    (
        "test_068",
        "cost",
        "Cost difference between January and December",
        "analyze_cost_trend",
        [],
    ),
    ("test_069", "cost", "Cost comparison for last quarter", "analyze_cost_trend", []),
    ("test_070", "cost", "Analyze cost trends for Q4", "analyze_cost_trend", []),
    (
        "test_071",
        "cost",
        "Cost trend analysis for the last 6 months",
        "analyze_cost_trend",
        [],
    ),
    # Resource Usage 분석
    ("test_072", "cost", "Resource usage analysis", "analyze_resource_usage", []),
    (
        "test_073",
        "cost",
        "Which instance uses the most resources",
        "analyze_resource_usage",
        [],
    ),
    ("test_074", "cost", "Optimize resource usage", "analyze_resource_usage", []),
    ("test_075", "cost", "Analyze resource utilization", "analyze_resource_usage", []),
    # High CPU 분석
    ("test_076", "cost", "High CPU alert", "analyze_high_cpu", []),
    ("test_077", "cost", "Analyze high cpu instances", "analyze_high_cpu", []),
    ("test_078", "cost", "Which instances have high CPU usage", "analyze_high_cpu", []),
    ("test_079", "cost", "Check for CPU spikes", "analyze_high_cpu", []),
    ("test_080", "cost", "Monitor high CPU utilization", "analyze_high_cpu", []),
    # 이름 기반 참조 12개 실제 인스턴스 이름 사용
    ("test_081", "naming", "Stop AIOpsmake", "stop_instances", ["name"]),
    ("test_082", "naming", "Start newserver", "start_instances", ["name"]),
    (
        "test_083",
        "naming",
        "Terminate AIOpsmake instance",
        "terminate_resource",
        ["name"],
    ),
    (
        "test_084",
        "naming",
        "Resize AIOpsmake to t3.large",
        "resize_instance",
        ["name", "instance_type"],
    ),
    ("test_085", "naming", "Get metrics for AIOpsmake", "get_metric", ["name"]),
    (
        "test_086",
        "naming",
        "Create snapshot of new-instance",
        "create_snapshot",
        ["name"],
    ),
    ("test_087", "naming", "Reboot web-server", "reboot_instances", ["name"]),
    ("test_088", "naming", "Get logs from newserver", "get_recent_logs", ["name"]),
    (
        "test_089",
        "naming",
        "Check CPU for AIOpsmake",
        "get_metric",
        ["name", "metric_name"],
    ),
    ("test_090", "naming", "Backup test instance", "create_snapshot", ["name"]),
    ("test_091", "naming", "Monitor production-db", "get_metric", ["name"]),
    ("test_092", "naming", "Stop old-app server", "stop_instances", ["name"]),
    # 복합 명령 개선 23개
    (
        "test_093",
        "complex",
        "Launch t2.micro and show topology",
        "create_instance",
        ["instance_type"],
    ),
    ("test_094", "complex", "Create VPC and subnet for production", "create_vpc", []),
    (
        "test_095",
        "complex",
        "Setup infrastructure: create VPC, subnet, instance",
        "create_vpc",
        [],
    ),
    (
        "test_096",
        "complex",
        "Start web-server and get CPU metrics",
        "start_instances",
        ["name"],
    ),
    (
        "test_097",
        "complex",
        "Stop old-app and create snapshot",
        "stop_instances",
        ["name"],
    ),
    (
        "test_098",
        "complex",
        "Resize AIOpsmake to t3.large then monitor",
        "resize_instance",
        ["name", "instance_type"],
    ),
    (
        "test_099",
        "complex",
        "List instances, show topology, and get cost",
        "list_instances",
        [],
    ),
    (
        "test_100",
        "complex",
        "Create snapshot of web-server and check logs",
        "create_snapshot",
        ["name"],
    ),
    (
        "test_101",
        "complex",
        "Get metrics for AIOpsmake and analyze cost trend",
        "get_metric",
        ["name"],
    ),
    (
        "test_102",
        "complex",
        "Audit: list all instances, topology, cost",
        "list_instances",
        [],
    ),
    (
        "test_103",
        "complex",
        "Emergency: stop high-cpu instance and alert",
        "stop_instances",
        [],
    ),
    (
        "test_104",
        "complex",
        "Scale: list instances then resize multiple",
        "list_instances",
        [],
    ),
    (
        "test_105",
        "complex",
        "Backup production: snapshot all instances",
        "create_snapshot",
        [],
    ),
    (
        "test_106",
        "complex",
        "Setup: create VPC, subnet, instance, monitor",
        "create_vpc",
        [],
    ),
    (
        "test_107",
        "complex",
        "Disaster recovery: terminate old, create new",
        "terminate_resource",
        [],
    ),
    (
        "test_108",
        "complex",
        "Performance review: logs, metrics, cost trend",
        "get_recent_logs",
        [],
    ),
    (
        "test_109",
        "complex",
        "Cost optimization: analyze usage and resources",
        "analyze_resource_usage",
        [],
    ),
    (
        "test_110",
        "complex",
        "Infrastructure as Code: create VPC with subnets",
        "create_vpc",
        [],
    ),
    (
        "test_111",
        "complex",
        "Monitoring dashboard: list, metrics, topology",
        "list_instances",
        [],
    ),
    (
        "test_112",
        "complex",
        "Incident response: check logs and CPU, stop if needed",
        "get_recent_logs",
        ["name"],
    ),
    (
        "test_113",
        "complex",
        "Capacity planning: analyze resources and cost trends",
        "analyze_resource_usage",
        [],
    ),
    (
        "test_114",
        "complex",
        "Maintenance window: stop servers, backup, restart",
        "stop_instances",
        [],
    ),
    (
        "test_115",
        "complex",
        "Multi-region setup: create VPCs in multiple regions",
        "create_vpc",
        [],
    ),
    # 엣지 케이스 20개
    (
        "test_116",
        "edge",
        "start instance named test-server-001",
        "start_instances",
        ["name"],
    ),
    ("test_117", "edge", "stop i-12345 and i-67890", "stop_instances", ["instance_id"]),
    (
        "test_118",
        "edge",
        "Create instance with special chars name@prod#1",
        "create_instance",
        ["name"],
    ),
    (
        "test_119",
        "edge",
        "resize to instance type t2.micro.nano",
        "resize_instance",
        ["instance_type"],
    ),
    (
        "test_120",
        "edge",
        "Get metric DiskReadBytes for web-server",
        "get_metric",
        ["name", "metric_name"],
    ),
    ("test_121", "edge", "Cost trend for year 2025", "analyze_cost_trend", []),
    (
        "test_122",
        "edge",
        "Cost trend January 2025 to December 2025",
        "analyze_cost_trend",
        [],
    ),
    ("test_123", "edge", "Create VPC 0.0.0.0/0", "create_vpc", ["cidr"]),
    ("test_124", "edge", "Create subnet 10.0.0.0/32", "create_subnet", ["cidr"]),
    ("test_125", "edge", "List terminated instances", "list_instances", []),
    ("test_126", "edge", "Reboot all instances", "reboot_instances", []),
    ("test_127", "edge", "Terminate all old instances", "terminate_resource", []),
    ("test_128", "edge", "Snapshot all production instances", "create_snapshot", []),
    ("test_129", "edge", "Get logs for multiple instances", "get_recent_logs", []),
    ("test_130", "edge", "Monitor high memory usage", "analyze_high_cpu", []),
    (
        "test_131",
        "edge",
        "cost trend for January to February",
        "analyze_cost_trend",
        [],
    ),
    (
        "test_132",
        "edge",
        "Resource usage by instance type",
        "analyze_resource_usage",
        [],
    ),
    ("test_133", "edge", "CPU utilization above 90%", "analyze_high_cpu", []),
    ("test_134", "edge", "Network in/out metrics", "get_metric", ["metric_name"]),
    (
        "test_135",
        "edge",
        "Overall infrastructure analysis",
        "analyze_resource_usage",
        [],
    ),
]


class LLMBenchmark:
    def __init__(
        self,
        model_name: str = "llama3.2:3b",
        base_url: str = "http://localhost:11434",
        output_dir: str = "benchmark_results",
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.results = []
        self.latencies = []
        self.category_results = defaultdict(list)
        self.skip_errors = False  # 에러 계속 진행 플래그

    def run_benchmark(self, num_tests: int = None):
        """벤치마크 실행"""
        test_list = TEST_CASES[:num_tests] if num_tests else TEST_CASES
        total = len(test_list)

        logger.info(f"\n{'=' * 80}")
        logger.info(f"AIOps LLM 성능 벤치마크")
        logger.info(f"{'=' * 80}")
        logger.info(f"모델: {self.model_name}")
        logger.info(f"테스트 케이스: {total}개")
        logger.info(f"{'=' * 80}\n")

        for idx, (test_id, category, prompt, expected_tool, expected_args) in enumerate(
            test_list, 1
        ):
            self._run_single_test(
                idx, total, test_id, category, prompt, expected_tool, expected_args
            )

        logger.info(f"\n{'=' * 80}")
        logger.info("벤치마크 완료")
        logger.info(f"{'=' * 80}\n")

    def _run_single_test(
        self,
        idx: int,
        total: int,
        test_id: str,
        category: str,
        prompt: str,
        expected_tool: str,
        expected_args: List[str],
    ) -> None:
        """개별 테스트 실행"""

        # LLM 프롬프트 생성
        llm_prompt = self._generate_improved_prompt(prompt)

        # LLM 호출 및 성능 측정
        start_time = time.time()
        try:
            response = self._call_llm(llm_prompt)
            latency_ms = (time.time() - start_time) * 1000
        except Exception as e:
            logger.error(f"LLM 호출 실패 ({test_id}): {str(e)}")
            return

        # 응답 파싱
        extracted_tool, extracted_args = self._extract_intent(response)

        # 정확도 평가
        tool_correct = extracted_tool == expected_tool
        args_correct = self._check_args_correctness(
            extracted_args, expected_args, extracted_tool
        )

        # 메트릭 수집
        metrics = {
            "latency_ms": latency_ms,
            "json_valid": self._is_valid_json(response),
            "response_length": len(response),
            "tokens_per_sec": len(response.split()) / (latency_ms / 1000)
            if latency_ms > 0
            else 0,
        }

        self.latencies.append(latency_ms)

        # 결과 저장
        result = {
            "test_id": test_id,
            "category": category,
            "prompt": prompt[:100],
            "expected_tool": expected_tool,
            "extracted_tool": extracted_tool,
            "tool_correct": tool_correct,
            "expected_args": expected_args,
            "extracted_args": list(extracted_args.keys()) if extracted_args else [],
            "args_correct": args_correct,
            "json_valid": metrics.get("json_valid", False),
            "latency_ms": metrics.get("latency_ms", 0),
            "tokens_per_sec": metrics.get("tokens_per_sec", 0),
            "response_length": metrics.get("response_length", 0),
            "timestamp": datetime.now().isoformat(),
        }

        self.results.append(result)

        # 로그 출력
        status = "✓" if tool_correct else "✗"
        args_status = "✓" if args_correct else "✗"
        json_status = "✓" if metrics.get("json_valid") else "✗"

        tool_display = extracted_tool if extracted_tool else "UNKNOWN"

        logger.info(
            f"[{idx:3d}/{total}] {status} Tool:{tool_display:25s} {args_status} Args "
            f"| Latency:{metrics.get('latency_ms', 0):6.0f}ms | JSON:{json_status} "
            f"| {test_id}"
        )

        # 카테고리별 결과 저장
        self.category_results[category].append(tool_correct)

        # 과도한 요청 방지
        if idx % 20 == 0:
            time.sleep(2)

    def _generate_improved_prompt(self, user_input: str) -> str:
        return f"""[INST] <>
You are an AWS Operations Agent. Analyze the user request and respond ONLY in JSON format.

Available Tools (Explicit):
- create_instance: Launch a new EC2 instance (args: name, instance_type)
- start_instances: Start a stopped instance (args: instance_id or name)
- stop_instances: Stop an instance (args: instance_id or name)
- reboot_instances: Reboot an instance (args: instance_id or name)
- terminate_resource: Terminate an instance (args: instance_id or name)
- resize_instance: Change instance type (args: instance_id or name, instance_type)
- list_instances: Show all instances (args: status='all')
- get_cost: Get monthly cost (args: {{}})
- get_metric: Get instance metrics (args: instance_id or name, metric_name)
- get_recent_logs: Get logs from instance (args: instance_id or name)
- create_snapshot: Create a snapshot (args: instance_id or name)
- create_vpc: Create a new VPC (args: cidr)
- create_subnet: Create a subnet (args: vpc_id, cidr)
- generate_topology: Show VPC topology (args: {{}})
- analyze_cost_trend: Analyze cost trends over time (args: {{}})
- analyze_resource_usage: Analyze resource utilization (args: {{}})
- analyze_high_cpu: Analyze high CPU instances (args: {{}})

Important Rules:
1. For instance operations, use 'instance_id' parameter (NOT 'InstanceIds')
   - Use exact instance names when mentioned (e.g., "AIOpsmake", "web-server", "new-instance")
   - The MCP server will convert names to IDs automatically

2. For cost trend analysis:
   - "last 3 months" -> use analyze_cost_trend
   - "cost comparison" -> use analyze_cost_trend
   - "resource optimization" -> use analyze_resource_usage
   - "high cpu" -> use analyze_high_cpu

3. Tool selection priority:
   - Use specific tools (start_instances, stop_instances) NOT execute_aws_action
   - Always prefer explicit tool over generic execute_aws_action

Format:
{{"tool": "tool_name", "args": {{key: value}}}}

Examples:
- "start web-server"
  -> {{"tool": "start_instances", "args": {{"instance_id": "web-server"}}}}

- "stop AIOpsmake"
  -> {{"tool": "stop_instances", "args": {{"instance_id": "AIOpsmake"}}}}

- "resize web-server to t3.large"
  -> {{"tool": "resize_instance", "args": {{"instance_id": "web-server", "instance_type": "t3.large"}}}}

- "analyze cost trend for last 3 months"
  -> {{"tool": "analyze_cost_trend", "args": {{}}}}

- "get cpu metric for web-server"
  -> {{"tool": "get_metric", "args": {{"instance_id": "web-server", "metric_name": "CPUUtilization"}}}}

<>
User: {user_input}
[/INST]"""

    def _call_llm(self, prompt: str) -> str:
        """LLM 호출"""
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.1,
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()["response"]
        except requests.exceptions.RequestException as e:
            logger.error(f"LLM 호출 실패: {str(e)}")
            raise

    def _extract_intent(self, response: str) -> Tuple[str, Dict[str, Any]]:
        """응답에서 의도 추출"""
        try:
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                tool = data.get("tool")
                args = data.get("args", {})
                return tool, args if isinstance(args, dict) else {}
        except (json.JSONDecodeError, AttributeError):
            pass

        return None, {}

    def _is_valid_json(self, response: str) -> bool:
        """응답이 유효한 JSON인지 확인"""
        try:
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                json.loads(match.group(0))
                return True
        except json.JSONDecodeError:
            pass
        return False

    def _check_args_correctness(
        self, extracted_args: Dict[str, Any], expected_args: List[str], tool: str
    ) -> bool:
        if not expected_args:
            return True

        extracted_arg_keys = set(extracted_args.keys()) if extracted_args else set()
        expected_arg_set = set(expected_args)

        if "instance_id" in expected_arg_set or "name" in expected_arg_set:
            has_instance_ref = (
                "instance_id" in extracted_arg_keys or "name" in extracted_arg_keys
            )
            if has_instance_ref:
                remaining_expected = expected_arg_set - {"instance_id", "name"}
                remaining_extracted = extracted_arg_keys - {"instance_id", "name"}
                if not remaining_expected:
                    return True
                return bool(remaining_extracted & remaining_expected)

        return bool(extracted_arg_keys & expected_arg_set)

    def generate_report(self):
        """결과 리포트 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_file = self.output_dir / f"benchmark_results_{timestamp}.csv"
        self._save_csv(csv_file)

        json_file = self.output_dir / f"benchmark_results_{timestamp}.json"
        self._save_json(json_file)

        summary_file = self.output_dir / f"benchmark_summary_{timestamp}.txt"
        self._save_summary(summary_file)

        logger.info(f"\n결과 저장:")
        logger.info(f" - CSV: {csv_file}")
        logger.info(f" - JSON: {json_file}")
        logger.info(f" - Summary: {summary_file}")

    def _save_csv(self, filepath: Path):
        """CSV 저장"""
        if not self.results:
            logger.warning("저장할 결과가 없습니다.")
            return

        keys = self.results[0].keys()
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.results)

    def _save_json(self, filepath: Path):
        """JSON 저장"""
        summary = {
            "total_tests": len(self.results),
            "tool_accuracy": sum(1 for r in self.results if r["tool_correct"])
            / len(self.results)
            * 100
            if self.results
            else 0,
            "args_accuracy": sum(1 for r in self.results if r["args_correct"])
            / len(self.results)
            * 100
            if self.results
            else 0,
            "json_valid_rate": sum(1 for r in self.results if r["json_valid"])
            / len(self.results)
            * 100
            if self.results
            else 0,
            "avg_latency_ms": mean(self.latencies) if self.latencies else 0,
            "median_latency_ms": median(self.latencies) if self.latencies else 0,
            "p95_latency_ms": self._percentile(self.latencies, 95)
            if self.latencies
            else 0,
            "p99_latency_ms": self._percentile(self.latencies, 99)
            if self.latencies
            else 0,
            "std_dev_ms": stdev(self.latencies) if len(self.latencies) > 1 else 0,
        }

        data = {
            "timestamp": datetime.now().isoformat(),
            "model": self.model_name,
            "summary": summary,
            "category_accuracy": {
                cat: sum(results) / len(results) * 100
                for cat, results in self.category_results.items()
                if results
            },
            "results": self.results,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _save_summary(self, filepath: Path) -> None:
        summary = {
            "total_tests": len(self.results),
            "tool_accuracy": sum(1 for r in self.results if r["tool_correct"])
            / len(self.results)
            * 100
            if self.results
            else 0,
            "args_accuracy": sum(1 for r in self.results if r["args_correct"])
            / len(self.results)
            * 100
            if self.results
            else 0,
            "json_valid_rate": sum(1 for r in self.results if r["json_valid"])
            / len(self.results)
            * 100
            if self.results
            else 0,
            "avg_latency_ms": mean(self.latencies) if self.latencies else 0,
            "median_latency_ms": median(self.latencies) if self.latencies else 0,
            "p95_latency_ms": self._percentile(self.latencies, 95)
            if self.latencies
            else 0,
            "p99_latency_ms": self._percentile(self.latencies, 99)
            if self.latencies
            else 0,
            "std_dev_ms": stdev(self.latencies) if len(self.latencies) > 1 else 0,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("AIOps LLM 성능 벤치마크 v2.0 결과 요약\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"모델: {self.model_name}\n")
            f.write(f"테스트 일시: {datetime.now().isoformat()}\n")
            f.write(f"총 테스트: {summary['total_tests']}개\n\n")

            f.write("─" * 80 + "\n")
            f.write("정확도 메트릭\n")
            f.write("─" * 80 + "\n")
            f.write(f"도구 선택 정확도: {summary['tool_accuracy']:.2f}%\n")
            f.write(f"파라미터 정확도: {summary['args_accuracy']:.2f}%\n")
            f.write(f"JSON 유효성: {summary['json_valid_rate']:.2f}%\n\n")

            f.write("─" * 80 + "\n")
            f.write("성능 메트릭 (ms)\n")
            f.write("─" * 80 + "\n")
            f.write(f"평균: {summary['avg_latency_ms']:.2f}ms\n")
            f.write(f"중앙값: {summary['median_latency_ms']:.2f}ms\n")
            f.write(f"P95: {summary['p95_latency_ms']:.2f}ms\n")
            f.write(f"P99: {summary['p99_latency_ms']:.2f}ms\n")
            f.write(f"표준편차: {summary['std_dev_ms']:.2f}ms\n\n")

            f.write("─" * 80 + "\n")
            f.write("카테고리별 정확도\n")
            f.write("─" * 80 + "\n")

            for category, accuracy in sorted(
                self.category_results.items(),
                key=lambda x: sum(x[1]) / len(x[1]) * 100 if x[1] else 0,
                reverse=True,
            ):
                if accuracy:
                    pct = sum(accuracy) / len(accuracy) * 100
                    f.write(
                        f"{category:20s}: {pct:6.2f}% ({sum(accuracy)}/{len(accuracy)})\n"
                    )

            f.write("\n" + "=" * 80 + "\n")

    @staticmethod
    def _percentile(data: List[float], percentile: int) -> float:
        """백분위수 계산"""
        sorted_data = sorted(data)
        index = int((percentile / 100) * len(sorted_data))
        return sorted_data[min(index, len(sorted_data) - 1)]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AIOps LLM 성능 벤치마크 v2.0")
    parser.add_argument(
        "--model",
        default="llama3.2:3b",
        help="LLM 모델 (기본값: llama3.2:3b)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434",
        help="Ollama 서버 URL (기본값: http://localhost:11434)",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results",
        help="결과 저장 디렉토리 (기본값: benchmark_results)",
    )
    parser.add_argument(
        "--num-tests",
        type=int,
        default=None,
        help="실행할 테스트 개수 (기본값: 전체 135개)",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="LLM 호출 실패 시 계속 진행 (기본값: False)",
    )

    args = parser.parse_args()

    benchmark = LLMBenchmark(
        model_name=args.model, base_url=args.base_url, output_dir=args.output_dir
    )

    benchmark.skip_errors = args.skip_errors
    benchmark.run_benchmark(args.num_tests)
    benchmark.generate_report()

    print("\n" + "=" * 80)
    print("최종 결과")
    print("=" * 80)

    total = len(benchmark.results)
    tool_correct = sum(1 for r in benchmark.results if r["tool_correct"])
    args_correct = sum(1 for r in benchmark.results if r["args_correct"])
    json_valid = sum(1 for r in benchmark.results if r["json_valid"])

    print(
        f"도구 선택 정확도: {tool_correct}/{total} ({tool_correct / total * 100:.2f}%)"
    )
    print(
        f"파라미터 정확도: {args_correct}/{total} ({args_correct / total * 100:.2f}%)"
    )
    print(f"✓ JSON 유효성: {json_valid}/{total} ({json_valid / total * 100:.2f}%)")
    print(
        f"평균 레이턴시: {mean(benchmark.latencies) if benchmark.latencies else 0:.2f}ms"
    )
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
