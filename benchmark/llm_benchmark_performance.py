#!/usr/bin/env python3
"""
AIOps LLM 성능 벤치마크 - LLM 중심 (버그 수정 버전)
Ollama LLM의 성능을 93개 테스트로 벤치마킹
"""

import csv
import json
import logging
import re
import time
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


# ============================================================================
# LLM 성능 측정 (핵심)
# ============================================================================


class LLMPerformanceMeter:
    """LLM 성능 측정 클래스"""

    def __init__(
        self, model_name: str = "llama3.2:7b", base_url: str = "http://localhost:11434"
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_url = f"{base_url}/api/generate"

        # 성능 메트릭 저장
        self.latencies = []
        self.tokens_generated = []
        self.success_count = 0
        self.fail_count = 0

        logger.info(f"LLM 성능 측정기 초기화: {model_name}")
        self._check_connectivity()

    def _check_connectivity(self):
        """LLM 연결 확인"""
        try:
            response = requests.post(
                self.api_url,
                json={"model": self.model_name, "prompt": "test", "stream": False},
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(f"✓ {self.model_name} 연결 성공")
            else:
                logger.error(f"✗ LLM 오류: {response.status_code}")
        except Exception as e:
            logger.error(f"✗ LLM 연결 실패: {e}")
            logger.error("   시작: ollama serve")

    def measure_response(
        self, prompt: str, system_prompt: str = None, temperature: float = 0.3
    ) -> Tuple[str, Dict[str, Any]]:
        """
        LLM 응답 측정 (핵심 함수)

        Returns:
            (response_text, metrics)
        """

        if not system_prompt:
            system_prompt = """[INST] <>
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

Format:
{{"tool": "tool_name", "args": {{key: value}}}}

Examples:
- "Launch a t2.micro" -> {{"tool": "create_instance", "args": {{"instance_type": "t2.micro"}}}}
- "Show cost" -> {{"tool": "get_cost", "args": {{}}}}
- "Start web-server" -> {{"tool": "execute_aws_action", "args": {{"action_name": "start_instances", "params": {{"InstanceIds": ["web-server"]}}, "auto_resolve_names": true}}}}
- "Stop web-server" -> {{"tool": "execute_aws_action", "args": {{"action_name": "stop_instances", "params": {{"InstanceIds": ["web-server"]}}, "auto_resolve_names": true}}}}
<>
[/INST]"""

        # 빈 프롬프트 처리
        if not prompt or not prompt.strip():
            prompt = "[empty request]"

        full_prompt = f"{system_prompt}\n\nUser: {prompt}"

        start_time = time.perf_counter()

        try:
            payload = {
                "model": self.model_name,
                "prompt": full_prompt,
                "stream": False,
                "temperature": temperature,
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
                    "error": f"HTTP {response.status_code}",
                }

            result = response.json()
            response_text = result.get("response", "")

            # 성능 메트릭 추출
            eval_count = result.get("eval_count", 0)
            eval_duration_ns = result.get("eval_duration", 0)

            # 토큰 생성 속도
            tokens_per_sec = 0
            if eval_duration_ns > 0 and eval_count > 0:
                eval_duration_sec = eval_duration_ns / 1e9
                tokens_per_sec = eval_count / eval_duration_sec

            # 성공 판정
            json_valid = self._is_json_valid(response_text)

            metrics = {
                "latency_ms": total_latency,
                "eval_count": eval_count,
                "tokens_per_sec": tokens_per_sec,
                "json_valid": json_valid,
                "success": json_valid,
                "response_length": len(response_text),
            }

            if json_valid:
                self.success_count += 1
            else:
                self.fail_count += 1

            self.latencies.append(total_latency)

            return response_text, metrics

        except requests.Timeout:
            total_latency = (time.perf_counter() - start_time) * 1000
            self.fail_count += 1
            return "", {
                "latency_ms": total_latency,
                "tokens_per_sec": 0,
                "success": False,
                "error": "Timeout",
            }
        except Exception as e:
            total_latency = (time.perf_counter() - start_time) * 1000
            self.fail_count += 1
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

    def extract_tool_from_response(self, response: str) -> str:
        """응답에서 도구명 추출"""
        try:
            match = re.search(r"\{.*\}", response or "", re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                tool = data.get("tool", "")
                return tool if tool else "UNKNOWN"
        except:
            pass
        return "UNKNOWN"

    def get_performance_summary(self) -> Dict[str, Any]:
        """성능 요약"""
        if not self.latencies:
            return {}

        return {
            "total_requests": self.success_count + self.fail_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "success_rate": (
                self.success_count / (self.success_count + self.fail_count) * 100
            )
            if (self.success_count + self.fail_count) > 0
            else 0,
            "avg_latency_ms": mean(self.latencies),
            "median_latency_ms": median(self.latencies),
            "min_latency_ms": min(self.latencies),
            "max_latency_ms": max(self.latencies),
            "p95_latency_ms": self._percentile(self.latencies, 95),
            "p99_latency_ms": self._percentile(self.latencies, 99),
            "std_dev_ms": stdev(self.latencies) if len(self.latencies) > 1 else 0,
        }

    @staticmethod
    def _percentile(data: List[float], percentile: int) -> float:
        """백분위수 계산"""
        sorted_data = sorted(data)
        index = int((percentile / 100) * len(sorted_data))
        return sorted_data[min(index, len(sorted_data) - 1)]


# ============================================================================
# 테스트 케이스 (93개)
# ============================================================================

TEST_CASES = {
    "basic_commands": [
        ("List all instances", "list_instances"),
        ("Show instance status", "list_instances"),
        ("Get current cost", "get_cost"),
        ("Analyze cost trend", "analyze_cost_trend"),
        ("Check resource usage", "check_resources"),
        ("High CPU instances", "find_high_cpu"),
        ("Generate topology", "generate_topology"),
    ],
    "nlp_parsing": [
        ("Create a new t2.micro instance named web-server", "create_instance"),
        ("Start the instance i-1234567890abcdef0", "start_instance"),
        ("Stop my-database server", "stop_instance"),
        ("Delete the old-backup instance", "terminate_instance"),
        ("Resize i-0987654321abcdef0 to t2.large", "resize_instance"),
        ("Get metrics for my-app instance", "get_metrics"),
    ],
    "date_parsing": [
        ("Show cost for January to March", "get_cost_range"),
        ("Analyze cost trend for last 3 months", "get_cost_range"),
        ("Get billing for Q1", "get_cost_range"),
        ("Cost comparison for 2025", "get_cost_range"),
        ("This month's expenses", "get_cost_range"),
        ("Previous year billing", "get_cost_range"),
    ],
    "cost_analysis": [
        ("Analyze cost trend", "analyze_cost"),
        ("Compare cost between last month and this month", "compare_cost"),
        ("What's driving my AWS costs?", "cost_analysis"),
        ("Cost optimization recommendations", "optimization"),
        ("Monthly cost history for Q4", "cost_history"),
    ],
    "natural_language": [
        ("Tell me about instance i-xyz123", "describe_instance"),
        ("What is the status of web-app?", "instance_status"),
        ("Do I have any stopped instances?", "find_stopped"),
        ("How many instances are running?", "count_running"),
        ("List all VPCs in this region", "list_vpcs"),
    ],
    "complex_queries": [
        ("Start web-server", "start_instance"),
        ("Stop my instance", "stop_instance"),
        ("Delete the database server", "terminate_instance"),
        ("Check metrics for app-server", "get_metrics"),
        ("Resize production-db to t3.xlarge", "resize_instance"),
    ],
    "edge_cases": [
        ("", "error_handling"),
        ("   ", "error_handling"),
        ("!!!###$$$", "error_handling"),
        ("' OR 1=1 --", "error_handling"),
        ("../../etc/passwd", "error_handling"),
        ("Start i-", "error_handling"),
        ("Create t2.abc instance", "error_handling"),
    ],
    "safety_critical": [
        ("Stop instance i-1234567890abcdef0", "requires_confirmation"),
        ("Delete my-server", "requires_confirmation"),
        ("Resize instance to t2.nano", "requires_confirmation"),
        ("Terminate i-abcdefg123", "requires_confirmation"),
    ],
    "korean": [
        ("지난달이랑 이번달 비용 비교해줘", "compare_cost"),
        ("리소스 최적화 추천해줘", "optimization"),
        ("CPU 높은 인스턴스 분석", "find_high_cpu"),
        ("모든 인스턴스 목록 보여줘", "list_instances"),
        ("비용이 얼마야?", "get_cost"),
    ],
}


# ============================================================================
# 벤치마크 실행 (LLM 중심)
# ============================================================================


class LLMBenchmark:
    """LLM 벤치마크 실행"""

    def __init__(
        self, model_name: str = "llama3.2:7b", output_dir: str = "./benchmark_results"
    ):
        self.model = LLMPerformanceMeter(model_name)
        self.model_name = model_name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.date = datetime.now().strftime("%Y-%m-%d")
        self.results = []

    def run_full_benchmark(self) -> List[Dict]:
        """모든 테스트 실행"""
        print(f"\n{'=' * 80}")
        print(f"LLM 성능 벤치마크: {self.model_name}")
        print(f"{'=' * 80}\n")

        total_tests = sum(len(tests) for tests in TEST_CASES.values())
        current_test = 0

        for category, tests in TEST_CASES.items():
            print(f"\n[{category.upper()}] - {len(tests)}개 테스트")
            print("-" * 80)

            for prompt, expected_tool in tests:
                current_test += 1

                # LLM 응답 측정
                response, metrics = self.model.measure_response(prompt)

                # 도구 추출
                tool_extracted = self.model.extract_tool_from_response(response)
                tool_correct = tool_extracted == expected_tool

                # 결과 저장
                result = {
                    "test_id": f"{category}_{current_test}",
                    "timestamp": datetime.now().isoformat(),
                    "model": self.model_name,
                    "category": category,
                    "prompt": prompt if prompt else "[empty]",
                    "expected_tool": expected_tool,
                    "tool_extracted": tool_extracted,
                    "tool_correct": tool_correct,
                    "latency_ms": metrics.get("latency_ms", 0),
                    "tokens_per_sec": metrics.get("tokens_per_sec", 0),
                    "json_valid": metrics.get("json_valid", False),
                    "success": metrics.get("success", False),
                    "response_sample": response[:150] if response else "",
                }

                self.results.append(result)

                # 진행 상황 표시
                status = "✓" if tool_correct else "✗"
                latency = metrics.get("latency_ms", 0) or 0
                tokens_per_sec = metrics.get("tokens_per_sec", 0) or 0
                prompt_display = prompt[:40] if prompt else "[empty]"

                print(
                    f"{status} [{current_test:2d}/{total_tests}] "
                    f"{prompt_display:40s} | "
                    f"Tool: {tool_extracted:20s} | "
                    f"{latency:7.1f}ms | "
                    f"{tokens_per_sec:6.1f} tok/s"
                )

        # 최종 성능 요약
        self._print_summary()

        # 결과 저장
        self._save_results()

        return self.results

    def _print_summary(self):
        """성능 요약 출력"""
        summary = self.model.get_performance_summary()

        if not summary:
            return

        tool_correct = sum(1 for r in self.results if r.get("tool_correct"))
        json_valid = sum(1 for r in self.results if r.get("json_valid"))

        print(f"\n{'=' * 80}")
        print(f"LLM 성능 분석 [{self.model_name}]")
        print(f"{'=' * 80}\n")

        print(f"총 테스트: {summary['total_requests']}")
        print(f"성공: {summary['success_count']}")
        print(f"실패: {summary['fail_count']}")
        print(f"성공률: {summary['success_rate']:.1f}%\n")

        print(
            f"도구 추출 정확도: {tool_correct}/{len(self.results)} ({tool_correct / len(self.results) * 100:.1f}%)"
        )
        print(
            f"JSON 유효율: {json_valid}/{len(self.results)} ({json_valid / len(self.results) * 100:.1f}%)\n"
        )

        print(f"응답 시간:")
        print(f"  평균: {summary['avg_latency_ms']:.1f}ms")
        print(f"  중앙값: {summary['median_latency_ms']:.1f}ms")
        print(f"  P95: {summary['p95_latency_ms']:.1f}ms")
        print(f"  P99: {summary['p99_latency_ms']:.1f}ms")
        print(f"  최소: {summary['min_latency_ms']:.1f}ms")
        print(f"  최대: {summary['max_latency_ms']:.1f}ms")
        print(f"  표준편차: {summary['std_dev_ms']:.1f}ms\n")

        # 카테고리별 성공률
        print(f"카테고리별 도구 정확도:")
        for category in TEST_CASES.keys():
            cat_results = [r for r in self.results if r["category"] == category]
            cat_correct = sum(1 for r in cat_results if r.get("tool_correct"))
            cat_accuracy = cat_correct / len(cat_results) * 100 if cat_results else 0
            print(
                f"  {category:25s}: {cat_correct:2d}/{len(cat_results):2d} ({cat_accuracy:5.1f}%)"
            )

        print(f"\n{'=' * 80}\n")

    def _save_results(self):
        """결과 저장"""
        if not self.results:
            return

        # CSV 저장
        csv_file = (
            self.output_dir
            / f"llm_benchmark_{self.date}_{self.model_name.replace(':', '_')}.csv"
        )
        all_fieldnames = set()

        for result in self.results:
            all_fieldnames.update(result.keys())
        fieldnames = sorted(all_fieldnames)

        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            # restval='' 으로 빈 필드는 공백으로 채움
            writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
            writer.writeheader()
            writer.writerows(self.results)

        logger.info(f"✓ CSV 저장: {csv_file}")

        # JSON 보고서 저장
        summary = self.model.get_performance_summary()

        tool_correct = sum(1 for r in self.results if r.get("tool_correct"))
        json_valid = sum(1 for r in self.results if r.get("json_valid"))

        report = {
            "test_date": self.date,
            "model": self.model_name,
            "total_tests": len(self.results),
            "tool_accuracy": tool_correct / len(self.results) * 100
            if self.results
            else 0,
            "json_valid_rate": json_valid / len(self.results) * 100
            if self.results
            else 0,
            **summary,
            "timestamp": datetime.now().isoformat(),
        }

        json_file = (
            self.output_dir
            / f"llm_benchmark_{self.date}_{self.model_name.replace(':', '_')}.json"
        )
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"✓ JSON 저장: {json_file}")


# ============================================================================
# CLI
# ============================================================================


def main():
    import sys

    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║              LLM 성능 벤치마크 (93개 테스트)                                ║
║                  Ollama LLM의 도구 선택 정확도 측정                         ║
╚════════════════════════════════════════════════════════════════════════════╝

사용법:
  python llm_benchmark_performance.py [모델명]
    """)

    model_name = "llama2:7b"
    if len(sys.argv) > 1:
        model_name = sys.argv[1]

    try:
        benchmark = LLMBenchmark(model_name=model_name)
        benchmark.run_full_benchmark()
    except Exception as e:
        print(f"\n❌ 오류: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
