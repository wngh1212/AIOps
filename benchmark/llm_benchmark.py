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

# 테스트 케이스 93개


TEST_CASES = [
    # Instance 관리 15개
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
    (
        "test_006",
        "instance",
        "Terminate i-0123456789abcdef",
        "terminate_resource",
        ["instance_id"],
    ),
    (
        "test_007",
        "instance",
        "Delete the web-server instance",
        "terminate_resource",
        ["name"],
    ),
    (
        "test_008",
        "instance",
        "Resize i-0123456789abcdef to t2.large",
        "resize_instance",
        ["instance_id", "instance_type"],
    ),
    (
        "test_009",
        "instance",
        "Change instance type of my-server to t3.xlarge",
        "resize_instance",
        ["name", "instance_type"],
    ),
    ("test_010", "instance", "Start web-server", "execute_aws_action", ["action_name"]),
    (
        "test_011",
        "instance",
        "Stop the database instance",
        "execute_aws_action",
        ["action_name"],
    ),
    (
        "test_012",
        "instance",
        "Reboot i-abcd1234",
        "execute_aws_action",
        ["action_name"],
    ),
    (
        "test_013",
        "instance",
        "Create a snapshot of i-0123456789abcdef",
        "create_snapshot",
        ["instance_id"],
    ),
    ("test_014", "instance", "Backup my-app-server", "create_snapshot", ["name"]),
    (
        "test_015",
        "instance",
        "Terminate resource i-xyz123",
        "terminate_resource",
        ["instance_id"],
    ),
    #  네트워크 관리 12개
    (
        "test_016",
        "network",
        "Create a VPC with CIDR 10.0.0.0/16",
        "create_vpc",
        ["cidr"],
    ),
    ("test_017", "network", "Create a new VPC", "create_vpc", []),
    (
        "test_018",
        "network",
        "Create a subnet in vpc-12345678 with CIDR 10.0.1.0/24",
        "create_subnet",
        ["vpc_id", "cidr"],
    ),
    ("test_019", "network", "Add a subnet to my VPC", "create_subnet", []),
    ("test_020", "network", "Show network topology", "generate_topology", []),
    ("test_021", "network", "Generate VPC topology", "generate_topology", []),
    (
        "test_022",
        "network",
        "Display the infrastructure layout",
        "generate_topology",
        [],
    ),
    ("test_023", "network", "Create VPC with name production-vpc", "create_vpc", []),
    ("test_024", "network", "Set up subnet in default VPC", "create_subnet", []),
    ("test_025", "network", "What is the network structure", "generate_topology", []),
    ("test_026", "network", "Create CIDR 172.16.0.0/16 VPC", "create_vpc", ["cidr"]),
    (
        "test_027",
        "network",
        "Make subnet 172.16.0.0/24 in vpc-abc",
        "create_subnet",
        ["vpc_id", "cidr"],
    ),
    # 모니터링 및 메트릭 15개
    (
        "test_028",
        "monitoring",
        "What is the CPU usage of i-0123456789abcdef",
        "get_metric",
        ["instance_id"],
    ),
    (
        "test_029",
        "monitoring",
        "Get CPU utilization for my-server",
        "get_metric",
        ["name"],
    ),
    ("test_030", "monitoring", "Check memory usage", "get_metric", []),
    (
        "test_031",
        "monitoring",
        "Show metrics for i-abc123",
        "get_metric",
        ["instance_id"],
    ),
    (
        "test_032",
        "monitoring",
        "Monitor web-server performance",
        "get_metric",
        ["name"],
    ),
    ("test_033", "monitoring", "Instance CPU usage", "get_metric", []),
    (
        "test_034",
        "monitoring",
        "Get performance metrics of web server",
        "get_metric",
        ["name"],
    ),
    (
        "test_035",
        "monitoring",
        "What is i-0123456789abcdef doing",
        "get_metric",
        ["instance_id"],
    ),
    ("test_036", "monitoring", "Check instance health", "get_metric", []),
    ("test_037", "monitoring", "Get logs from instance", "get_recent_logs", []),
    (
        "test_038",
        "monitoring",
        "Show recent logs of i-xyz",
        "get_recent_logs",
        ["instance_id"],
    ),
    (
        "test_039",
        "monitoring",
        "Retrieve logs from web-server",
        "get_recent_logs",
        ["name"],
    ),
    ("test_040", "monitoring", "Display instance logs", "get_recent_logs", []),
    (
        "test_041",
        "monitoring",
        "Get metrics CPUUtilization from i-12345",
        "get_metric",
        ["instance_id", "metric_name"],
    ),
    (
        "test_042",
        "monitoring",
        "Check NetworkIn for my-app-instance",
        "get_metric",
        ["metric_name"],
    ),
    # 비용 관리 12개
    ("test_043", "cost", "What is my monthly cost", "get_cost", []),
    ("test_044", "cost", "Show AWS billing", "get_cost", []),
    ("test_045", "cost", "How much have I spent", "get_cost", []),
    ("test_046", "cost", "Get cost estimate", "get_cost", []),
    ("test_047", "cost", "Calculate my bill", "get_cost", []),
    ("test_048", "cost", "Cost difference between regions", "analyze_cost_trend", []),
    ("test_049", "cost", "Analyze cost trends", "analyze_cost_trend", []),
    ("test_050", "cost", "Compare costs", "analyze_cost_trend", []),
    ("test_051", "cost", "Resource usage analysis", "analyze_resource_usage", []),
    (
        "test_052",
        "cost",
        "Which instance uses the most resources",
        "analyze_resource_usage",
        [],
    ),
    ("test_053", "cost", "Optimize resource usage", "analyze_resource_usage", []),
    ("test_054", "cost", "High CPU alert", "analyze_high_cpu", []),
    # 복합 명령 15개
    (
        "test_055",
        "complex",
        "Launch t2.micro, show topology, and get cost",
        "create_instance",
        ["instance_type"],
    ),
    ("test_056", "complex", "Create production VPC and subnet", "create_vpc", []),
    (
        "test_057",
        "complex",
        "Setup infrastructure with t2.small instance",
        "create_instance",
        ["instance_type"],
    ),
    ("test_058", "complex", "Monitor and backup web server", "get_metric", ["name"]),
    ("test_059", "complex", "Create snapshot and check cost", "create_snapshot", []),
    (
        "test_060",
        "complex",
        "Resize instance and monitor performance",
        "resize_instance",
        ["instance_type"],
    ),
    ("test_061", "complex", "Setup new VPC with instance", "create_vpc", []),
    (
        "test_062",
        "complex",
        "Terminate old instance and create new one",
        "terminate_resource",
        [],
    ),
    ("test_063", "complex", "Review logs and check CPU usage", "get_recent_logs", []),
    ("test_064", "complex", "Compare instance types and costs", "get_cost", []),
    (
        "test_065",
        "complex",
        "Create instance for testing then generate topology",
        "create_instance",
        ["instance_type"],
    ),
    (
        "test_066",
        "complex",
        "Scale infrastructure: list instances then resize",
        "list_instances",
        [],
    ),
    ("test_067", "complex", "Get metrics, logs, and cost report", "get_metric", []),
    (
        "test_068",
        "complex",
        "Audit: list all, show topology, analyze cost",
        "list_instances",
        [],
    ),
    (
        "test_069",
        "complex",
        "Emergency: stop high-cpu instance and alert",
        "execute_aws_action",
        ["action_name"],
    ),
    # 엣지 케이스 및 에러 24개
    ("test_070", "edge", "", None, []),
    ("test_071", "edge", "   ", None, []),
    ("test_072", "edge", "what", None, []),
    ("test_073", "edge", "unknown command xyz abc", None, []),
    ("test_074", "edge", "blah blah blah", None, []),
    ("test_075", "edge", "123456789", None, []),
    ("test_076", "edge", "!@#$%^&*()", None, []),
    (
        "test_077",
        "edge",
        "Create instance with invalid type xxx99",
        "create_instance",
        [],
    ),
    (
        "test_078",
        "edge",
        "Resize i-notreal to t2.micro",
        "resize_instance",
        ["instance_id", "instance_type"],
    ),
    ("test_079", "edge", "Get metric for nonexistent-server", "get_metric", ["name"]),
    ("test_080", "edge", "Terminate invalid-id", "terminate_resource", []),
    (
        "test_081",
        "edge",
        "Create VPC with invalid CIDR 999.999.999.999",
        "create_vpc",
        ["cidr"],
    ),
    ("test_082", "edge", "create subnet without vpc", "create_subnet", []),
    ("test_083", "edge", "AWS what", None, []),
    ("test_084", "edge", "Can you help me please", None, []),
    ("test_085", "edge", "I want to", None, []),
    ("test_086", "edge", "Maybe create instance", "create_instance", []),
    ("test_087", "edge", "Possibly list instances", "list_instances", []),
    (
        "test_088",
        "edge",
        "Very long prompt: " + "create instance " * 20,
        "create_instance",
        [],
    ),
    ("test_089", "edge", "Create-Instance (with hyphens)", "create_instance", []),
    (
        "test_090",
        "edge",
        "LAUNCH T2.MICRO UPPERCASE",
        "create_instance",
        ["instance_type"],
    ),
    (
        "test_091",
        "edge",
        "terminate_resource i-123",
        "terminate_resource",
        ["instance_id"],
    ),
    ("test_092", "edge", "list_instances status=running", "list_instances", []),
    (
        "test_093",
        "edge",
        'JSON format: {"tool": "create_instance", "args": {"instance_type": "t2.nano"}}',
        "create_instance",
        ["instance_type"],
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
        self.api_url = f"{base_url}/api/generate"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # 성능 메트릭
        self.latencies = []
        self.results = []
        self.category_results = defaultdict(list)

        logger.info(f"LLM 벤치마크 초기화: {model_name}")
        self._check_connectivity()

    def _check_connectivity(self):
        try:
            response = requests.post(
                self.api_url,
                json={"model": self.model_name, "prompt": "test", "stream": False},
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(f"O {self.model_name} 연결 성공")
            else:
                logger.error(f"X LLM 오류: {response.status_code}")
        except Exception as e:
            logger.error(f"X LLM 연결 실패: {e}")

    def _generate_prompt(self, user_input: str) -> str:
        """서비스와 동일한 프롬프트 생성"""
        return f"""[INST] <>
You are an AWS Operations Agent. Analyze the user request and respond ONLY in JSON format.

Available Tools:
- create_instance: Launch a new EC2 instance (args: name, instance_type)
- terminate_resource: Terminate an instance (args: instance_id)
- execute_aws_action: Execute AWS EC2 actions (args: action_name, params)
- resize_instance: Change instance type (args: instance_id, instance_type)
- list_instances: Show all instances (args: status='all')
- get_cost: Get monthly cost
- get_metric: Get instance metrics (args: instance_id)
- generate_topology: Show VPC topology
- create_vpc: Create a new VPC
- create_subnet: Create a subnet in VPC (args: vpc_id, cidr)
- create_snapshot: Create a snapshot
- analyze_cost_trend: Analyze cost trends
- analyze_resource_usage: Analyze resource usage
- analyze_high_cpu: Analyze high CPU instances
- get_recent_logs: Get recent logs

Format:
{{"tool": "tool_name", "args": {{key: value}}}}

Examples:
- "Launch a t2.micro" -> {{"tool": "create_instance", "args": {{"instance_type": "t2.micro"}}}}
- "Show cost" -> {{"tool": "get_cost", "args": {{}}}}
- "Start web-server" -> {{"tool": "execute_aws_action", "args": {{"action_name": "start_instances", "params": {{"InstanceIds": ["web-server"]}}, "auto_resolve_names": true}}}}

<>
User: {user_input}
[/INST]"""

    def measure_response(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        """LLM 응답 측정"""
        full_prompt = self._generate_prompt(prompt)

        start_time = time.perf_counter()
        try:
            payload = {
                "model": self.model_name,
                "prompt": full_prompt,
                "stream": False,
                "temperature": 0.3,
                "top_p": 0.9,
            }

            response = requests.post(self.api_url, json=payload, timeout=60)
            total_latency = (time.perf_counter() - start_time) * 1000

            if response.status_code != 200:
                logger.error(f"LLM 오류: {response.status_code}")
                return "", {
                    "latency_ms": total_latency,
                    "tokens_per_sec": 0,
                    "success": False,
                }

            result = response.json()
            response_text = result.get("response", "")

            # 성능 메트릭 추출
            eval_count = result.get("eval_count", 0)
            eval_duration_ns = result.get("eval_duration", 0)

            tokens_per_sec = 0
            if eval_duration_ns > 0 and eval_count > 0:
                eval_duration_sec = eval_duration_ns / 1e9
                tokens_per_sec = eval_count / eval_duration_sec

            # JSON 유효성 검사
            json_valid = self._is_json_valid(response_text)

            self.latencies.append(total_latency)

            return response_text, {
                "latency_ms": total_latency,
                "tokens_per_sec": tokens_per_sec,
                "json_valid": json_valid,
                "response_length": len(response_text),
            }

        except requests.Timeout:
            total_latency = (time.perf_counter() - start_time) * 1000
            return "", {
                "latency_ms": total_latency,
                "tokens_per_sec": 0,
                "success": False,
                "error": "Timeout",
            }

        except Exception as e:
            total_latency = (time.perf_counter() - start_time) * 1000
            logger.error(f"측정 실패: {e}")
            return "", {
                "latency_ms": total_latency,
                "tokens_per_sec": 0,
                "success": False,
                "error": str(e),
            }

    def _is_json_valid(self, response: str) -> bool:
        """JSON 유효성 검사"""
        try:
            match = re.search(r"\{.*\}", response or "", re.DOTALL)
            if match:
                json.loads(match.group(0))
                return True
        except:
            pass
        return False

    def extract_tool_and_args(self, response: str) -> Tuple[str, Dict[str, Any]]:
        # 응답에서 도구명과 인자 추출
        try:
            match = re.search(r"\{.*\}", response or "", re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                tool = data.get("tool", "UNKNOWN")
                args = data.get("args", {})
                return tool if tool else "UNKNOWN", args
        except:
            pass
        return "UNKNOWN", {}

    def run_benchmark(self, num_tests: int = None):
        """벤치마크 실행"""
        test_cases = TEST_CASES if num_tests is None else TEST_CASES[:num_tests]
        total = len(test_cases)

        logger.info(f"\n{'=' * 80}")
        logger.info(f"AIOps LLM 벤치마크 시작 - {total}개 테스트")
        logger.info(f"모델: {self.model_name}")
        logger.info(f"{'=' * 80}\n")

        for idx, test_case in enumerate(test_cases, 1):
            test_id, category, prompt, expected_tool, expected_args = test_case

            logger.info(
                f"[{idx:3d}/{total}] ({category:10s}) {test_id:10s} | {prompt[:50]:50s}"
            )

            # LLM 응답 측정
            response, metrics = self.measure_response(prompt)

            # 도구 추출
            extracted_tool, extracted_args = self.extract_tool_and_args(response)

            # 정확도 계산
            tool_correct = extracted_tool == (expected_tool or "UNKNOWN")
            args_correct = self._check_args_correctness(
                extracted_args, expected_args, extracted_tool
            )

            # 결과 저장
            result = {
                "test_id": test_id,
                "category": category,
                "prompt": prompt[:100],
                "expected_tool": expected_tool,
                "extracted_tool": extracted_tool,
                "tool_correct": tool_correct,
                "expected_args": expected_args,
                "extracted_args": str(list(extracted_args.keys()))
                if extracted_args
                else "None",
                "args_correct": args_correct,
                "json_valid": metrics.get("json_valid", False),
                "latency_ms": metrics.get("latency_ms", 0),
                "tokens_per_sec": metrics.get("tokens_per_sec", 0),
                "response_length": metrics.get("response_length", 0),
                "timestamp": datetime.now().isoformat(),
            }

            self.results.append(result)

            # 로그 출력
            status = "O" if tool_correct else "X"
            logger.info(
                f"{status} Tool: {str(extracted_tool):20s} | "
                f"Latency: {metrics.get('latency_ms', 0):.0f}ms | "
                f"JSON: {'O' if metrics.get('json_valid') else 'X'}"
            )

            # 카테고리별 결과 저장
            self.category_results[category].append(tool_correct)

            # 과도한 요청 방지
            if idx % 20 == 0:
                time.sleep(2)

        logger.info(f"\n{'=' * 80}")
        logger.info("벤치마크 완료")
        logger.info(f"{'=' * 80}\n")

    def _check_args_correctness(
        self, extracted_args: Dict[str, Any], expected_args: List[str], tool: str
    ) -> bool:
        # 인자 정확도 검사
        if not expected_args:
            return True

        extracted_arg_keys = set(extracted_args.keys()) if extracted_args else set()
        expected_arg_set = set(expected_args)

        return bool(extracted_arg_keys & expected_arg_set)

    def generate_report(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV 저장
        csv_file = self.output_dir / f"benchmark_results_{timestamp}.csv"
        self._save_csv(csv_file)

        # JSON 저장
        json_file = self.output_dir / f"benchmark_results_{timestamp}.json"
        self._save_json(json_file)

        summary_file = self.output_dir / f"benchmark_summary_{timestamp}.txt"
        self._save_summary(summary_file)

        logger.info(f"\n결과 저장:")
        logger.info(f"  - CSV: {csv_file}")
        logger.info(f"  - JSON: {json_file}")
        logger.info(f"  - Summary: {summary_file}")

    def _save_csv(self, filepath: Path):
        # CSV 형식으로 저장
        if not self.results:
            logger.warning("저장할 결과가 없습니다.")
            return

        keys = self.results[0].keys()
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.results)

    def _save_json(self, filepath: Path):
        # JSON 형식으로 저장
        summary = {
            "total_tests": len(self.results),
            "tool_accuracy": sum(1 for r in self.results if r["tool_correct"])
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
            f.write("AIOps LLM 성능 벤치마크 결과 요약\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"모델: {self.model_name}\n")
            f.write(f"테스트 일시: {datetime.now().isoformat()}\n\n")

            f.write("─" * 80 + "\n")
            f.write("성능 메트릭\n")
            f.write("─" * 80 + "\n")
            f.write(f"총 테스트: {summary['total_tests']}\n")
            f.write(f"도구 선택 정확도: {summary['tool_accuracy']:.2f}%\n")
            f.write(f"JSON 유효성: {summary['json_valid_rate']:.2f}%\n\n")

            f.write("─" * 80 + "\n")
            f.write("레이턴시 (milliseconds)\n")
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
        sorted_data = sorted(data)
        index = int((percentile / 100) * len(sorted_data))
        return sorted_data[min(index, len(sorted_data) - 1)]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AIOps LLM 성능 벤치마크")
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
        help="실행할 테스트 개수 (기본값: 전체 93개)",
    )

    args = parser.parse_args()

    # 벤치마크 실행
    benchmark = LLMBenchmark(
        model_name=args.model, base_url=args.base_url, output_dir=args.output_dir
    )

    benchmark.run_benchmark(args.num_tests)
    benchmark.generate_report()

    print("\n" + "=" * 80)
    print("최종 결과")
    print("=" * 80)

    total = len(benchmark.results)
    tool_correct = sum(1 for r in benchmark.results if r["tool_correct"])
    json_valid = sum(1 for r in benchmark.results if r["json_valid"])

    print(
        f"✓ 도구 선택 정확도: {tool_correct}/{total} ({tool_correct / total * 100:.2f}%)"
    )
    print(f"✓ JSON 유효성: {json_valid}/{total} ({json_valid / total * 100:.2f}%)")
    print(
        f"평균 레이턴시: {mean(benchmark.latencies) if benchmark.latencies else 0:.2f}ms"
    )
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
