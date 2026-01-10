#!/usr/bin/env python3
"""
LLM 벤치마크 결과 분석 및 모델 비교
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt
    import seaborn as sns

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("matplotlib 미설치")


class LLMBenchmarkAnalyzer:
    """LLM 벤치마크 분석"""

    def __init__(self, results_dir: str = "./benchmark_results"):
        self.results_dir = Path(results_dir)
        self.csv_files = list(self.results_dir.glob("llm_benchmark_*.csv"))
        self.json_files = list(self.results_dir.glob("llm_benchmark_*.json"))

        self.data = {}
        self.reports = {}
        self._load_all_results()

    def plot_comparison(self):
        """비교 차트 생성"""
        if not HAS_MATPLOTLIB or len(self.reports) < 2:
            print("matplotlib 필요하거나 모델 부족")
            return

        # ✅ reports.keys() 직접 사용 (일관성 보장)
        models = [m.replace("_", ":") for m in self.reports.keys()]
        accuracies = [
            self.reports[m].get("tool_accuracy", 0) for m in self.reports.keys()
        ]
        latencies = [
            self.reports[m].get("avg_latency_ms", 0) for m in self.reports.keys()
        ]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # 도구 정확도
        colors1 = plt.cm.RdYlGn(np.linspace(0.3, 0.9, len(models)))
        ax1.bar(models, accuracies, color=colors1)
        ax1.set_ylabel("도구 선택 정확도 (%)")
        ax1.set_title("LLM 도구 선택 정확도 비교")
        ax1.set_ylim(0, 105)
        ax1.grid(axis="y", alpha=0.3)

        for i, acc in enumerate(accuracies):
            ax1.text(i, acc + 1, f"{acc:.1f}%", ha="center")

            # 응답 시간
            colors2 = plt.cm.RdYlGn_r(np.linspace(0.3, 0.9, len(models)))
            ax2.bar(models, latencies, color=colors2)
            ax2.set_ylabel("응답 시간 (ms)")
            ax2.set_title("LLM 응답 시간 비교")
            ax2.grid(axis="y", alpha=0.3)

            for i, lat in enumerate(latencies):
                ax2.text(i, lat + 20, f"{lat:.0f}ms", ha="center")

            plt.tight_layout()
            output_file = (
                self.results_dir
                / f"llm_comparison_{datetime.now().strftime('%Y-%m-%d')}.png"
            )
            plt.savefig(output_file, dpi=150)
            print(f"✓ 차트 저장: {output_file}")

    def _load_all_results(self):
        """모든 결과 로드"""
        print(f"\n로드 중: {self.results_dir}\n")

        for json_file in self.json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    report = json.load(f)
                    model = report.get("model", "unknown")
                    self.reports[model] = report
                    print(f"✓ {json_file.name}")
            except Exception as e:
                print(f"✗ {json_file.name}: {e}")

        for csv_file in self.csv_files:
            try:
                df = pd.read_csv(csv_file, encoding="utf-8")
                # 모델명 추출
                filename = csv_file.stem  # llm_benchmark_2026-01-09_llama3.2:7b
                parts = filename.split("_")
                if len(parts) >= 4:
                    model = "_".join(parts[3:]).replace(":", "_")
                else:
                    model = "unknown"

                self.data[model] = df
                print(f"✓ {csv_file.name} ({len(df)} 테스트)")
            except Exception as e:
                print(f"✗ {csv_file.name}: {e}")

    def print_summary(self):
        """전체 요약 출력"""
        if not self.reports:
            print("데이터 없음")
            return

        print(f"\n{'=' * 90}")
        print(f"LLM 성능 벤치마크 결과 요약")
        print(f"{'=' * 90}\n")

        # 모델별 정렬
        sorted_models = sorted(
            self.reports.items(),
            key=lambda x: x[1].get("tool_accuracy", 0),
            reverse=True,
        )

        print(
            f"{'모델':<20} {'도구정확도':<12} {'JSON유효율':<12} {'응답시간':<12} {'성공률':<10}"
        )
        print("-" * 90)

        for model, report in sorted_models:
            model_display = model.replace("_", ":")
            accuracy = report.get("tool_accuracy", 0)
            json_rate = report.get("json_valid_rate", 0)
            latency = report.get("avg_latency_ms", 0)
            success_rate = report.get("success_rate", 0)

            print(
                f"{model_display:<20} {accuracy:>10.1f}% {json_rate:>10.1f}% "
                f"{latency:>10.1f}ms {success_rate:>8.1f}%"
            )

    def print_detailed_analysis(self):
        """상세 분석 출력"""
        for model_display, report in sorted(self.reports.items()):
            model_name = model_display.replace("_", ":")

            print(f"\n{'=' * 90}")
            print(f"📊 {model_name}")
            print(f"{'=' * 90}\n")

            print(f"총 테스트: {report.get('total_tests')}")
            print(f"도구 정확도: {report.get('tool_accuracy', 0):.1f}%")
            print(f"JSON 유효율: {report.get('json_valid_rate', 0):.1f}%")
            print(f"성공률: {report.get('success_rate', 0):.1f}%\n")

            print(f"응답 시간 (ms):")
            print(f"  평균: {report.get('avg_latency_ms', 0):.1f}")
            print(f"  중앙값: {report.get('median_latency_ms', 0):.1f}")
            print(f"  P95: {report.get('p95_latency_ms', 0):.1f}")
            print(f"  P99: {report.get('p99_latency_ms', 0):.1f}")
            print(f"  최소: {report.get('min_latency_ms', 0):.1f}")
            print(f"  최대: {report.get('max_latency_ms', 0):.1f}")
            print(f"  표준편차: {report.get('std_dev_ms', 0):.1f}\n")

    def print_category_analysis(self):
        """카테고리별 분석"""
        print(f"\n{'=' * 90}")
        print(f"카테고리별 도구 정확도 분석")
        print(f"{'=' * 90}\n")

        for model, df in self.data.items():
            model_name = model.replace("_", ":")
            print(f"\n[{model_name}]")

            if "category" not in df.columns or "tool_correct" not in df.columns:
                print("  데이터 부족")
                continue

            categories = (
                df.groupby("category")
                .agg({"tool_correct": ["sum", "count", "mean"]})
                .round(3)
            )

            categories.columns = ["정확", "총개", "정확도"]
            categories["정확도"] = (categories["정확도"] * 100).round(1)

            for category, row in categories.iterrows():
                print(
                    f"  {category:25s}: "
                    f"{int(row['정확']):2d}/{int(row['총개']):2d} "
                    f"({row['정확도']:5.1f}%)"
                )

    def compare_models(self):
        """모델 간 비교"""
        if len(self.reports) < 2:
            print("비교할 모델 부족 (2개 이상 필요)")
            return

        print(f"\n{'=' * 90}")
        print(f"🏆 모델 성능 순위")
        print(f"{'=' * 90}\n")

        # 도구 정확도 순위
        print("도구 선택 정확도")
        models_by_accuracy = sorted(
            self.reports.items(),
            key=lambda x: x[1].get("tool_accuracy", 0),
            reverse=True,
        )
        for rank, (model, report) in enumerate(models_by_accuracy, 1):
            model_name = model.replace("_", ":")
            accuracy = report.get("tool_accuracy", 0)
            print(f"   {rank}. {model_name:20s}: {accuracy:6.1f}%")

        # 응답 속도 순위
        print("\n응답 속도 (빠를수록 좋음)")
        models_by_speed = sorted(
            self.reports.items(), key=lambda x: x[1].get("avg_latency_ms", float("inf"))
        )
        for rank, (model, report) in enumerate(models_by_speed, 1):
            model_name = model.replace("_", ":")
            latency = report.get("avg_latency_ms", 0)
            print(f"   {rank}. {model_name:20s}: {latency:7.1f}ms")

        # 종합 점수
        print("\n종합 점수 (최대 100점)")
        scores = {}
        for model, report in self.reports.items():
            accuracy_score = (report.get("tool_accuracy", 0) / 100) * 40
            json_score = (report.get("json_valid_rate", 0) / 100) * 20
            latency = report.get("avg_latency_ms", 1000)
            speed_score = max(0, (1 - latency / 2000) * 40)  # 2000ms 기준

            total_score = accuracy_score + json_score + speed_score
            scores[model] = total_score

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        for rank, (model, score) in enumerate(sorted_scores, 1):
            model_name = model.replace("_", ":")
            print(f"   {rank}. {model_name:20s}: {score:6.1f}/100")

    def export_comparison_table(self):
        """비교 테이블 내보내기"""
        if not self.reports:
            print("데이터 없음")
            return

        comparison = []
        for model, report in self.reports.items():
            comparison.append(
                {
                    "모델": model.replace("_", ":"),
                    "총테스트": report.get("total_tests"),
                    "도구정확도": f"{report.get('tool_accuracy', 0):.1f}%",
                    "JSON유효율": f"{report.get('json_valid_rate', 0):.1f}%",
                    "평균응답시간": f"{report.get('avg_latency_ms', 0):.1f}ms",
                    "중앙값": f"{report.get('median_latency_ms', 0):.1f}ms",
                    "P95": f"{report.get('p95_latency_ms', 0):.1f}ms",
                    "성공률": f"{report.get('success_rate', 0):.1f}%",
                }
            )

        df_comparison = pd.DataFrame(comparison)

        # 콘솔에 출력
        print("\n" + "=" * 100)
        print("비교 테이블")
        print("=" * 100 + "\n")
        print(df_comparison.to_string(index=False))

        # CSV로 저장
        output_file = (
            self.results_dir
            / f"model_comparison_{datetime.now().strftime('%Y-%m-%d')}.csv"
        )
        df_comparison.to_csv(output_file, index=False, encoding="utf-8")
        print(f"\n✓ 저장: {output_file}\n")

        def plot_comparison(self):
            """비교 차트 생성"""
            if not HAS_MATPLOTLIB or len(self.reports) < 2:
                print("matplotlib 필요하거나 모델 부족")
                return

            # reports.keys()를 직접 사용 (일관성 보장)
            models = [m.replace("_", ":") for m in self.reports.keys()]
            accuracies = [
                self.reports[m].get("tool_accuracy", 0) for m in self.reports.keys()
            ]
            latencies = [
                self.reports[m].get("avg_latency_ms", 0) for m in self.reports.keys()
            ]

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

            # 도구 정확도
            colors1 = plt.cm.RdYlGn(np.linspace(0.3, 0.9, len(models)))
            ax1.bar(models, accuracies, color=colors1)
            ax1.set_ylabel("도구 선택 정확도 (%)")
            ax1.set_title("LLM 도구 선택 정확도 비교")
            ax1.set_ylim(0, 105)
            ax1.grid(axis="y", alpha=0.3)

            for i, acc in enumerate(accuracies):
                ax1.text(i, acc + 1, f"{acc:.1f}%", ha="center")

            # 응답 시간
            colors2 = plt.cm.RdYlGn_r(np.linspace(0.3, 0.9, len(models)))
            ax2.bar(models, latencies, color=colors2)
            ax2.set_ylabel("응답 시간 (ms)")
            ax2.set_title("LLM 응답 시간 비교")
            ax2.grid(axis="y", alpha=0.3)

            for i, lat in enumerate(latencies):
                ax2.text(i, lat + 20, f"{lat:.0f}ms", ha="center")

            plt.tight_layout()
            output_file = (
                self.results_dir
                / f"llm_comparison_{datetime.now().strftime('%Y-%m-%d')}.png"
            )
            plt.savefig(output_file, dpi=150)
            print(f"✓ 차트 저장: {output_file}")

    def generate_report(self):
        """최종 분석 리포트"""
        print(f"\n{'=' * 90}")
        print(f"LLM 성능 벤치마크 최종 리포트")
        print(f"{'=' * 90}\n")

        self.print_summary()
        self.print_category_analysis()
        self.compare_models()
        self.export_comparison_table()
        self.plot_comparison()

        print(f"\n{'=' * 90}")
        print(f"분석 완료")
        print(f"{'=' * 90}\n")


def main():
    analyzer = LLMBenchmarkAnalyzer()
    analyzer.generate_report()
    analyzer.print_detailed_analysis()


if __name__ == "__main__":
    main()
