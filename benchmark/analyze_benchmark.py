import json
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

plt.rcParams["font.family"] = "DejaVu Sans"
sns.set_style("whitegrid")


class BenchmarkAnalyzer:
    """벤치마크 결과 분석 클래스"""

    def __init__(self, json_file: str):
        """
        json_file: 벤치마크 결과 JSON 파일 경로
        """
        self.json_file = Path(json_file)
        self.data = None
        self.df = None
        self.load_data()

    def load_data(self):
        """JSON 파일 로드"""
        with open(self.json_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        # pandas DataFrame으로 변환
        self.df = pd.DataFrame(self.data["results"])
        print(f"✓ 데이터 로드 완료: {len(self.df)} 테스트")

    def analyze_overall_stats(self) -> Dict:
        """전체 통계 분석"""
        stats = {
            "total_tests": len(self.df),
            "tool_accuracy": (self.df["tool_correct"].sum() / len(self.df) * 100),
            "json_valid_rate": (self.df["json_valid"].sum() / len(self.df) * 100),
            "avg_latency": self.df["latency_ms"].mean(),
            "median_latency": self.df["latency_ms"].median(),
            "p95_latency": self.df["latency_ms"].quantile(0.95),
            "p99_latency": self.df["latency_ms"].quantile(0.99),
        }
        return stats

    def analyze_by_category(self) -> pd.DataFrame:
        """카테고리별 분석"""
        category_stats = (
            self.df.groupby("category")
            .agg(
                {
                    "tool_correct": ["sum", "count", lambda x: x.sum() / len(x) * 100],
                    "json_valid": ["sum", lambda x: x.sum() / len(x) * 100],
                    "latency_ms": ["mean", "median", "std"],
                }
            )
            .round(2)
        )

        category_stats.columns = [
            "Correct",
            "Total",
            "Accuracy(%)",
            "JSON_Valid_Sum",
            "JSON_Valid_Rate(%)",
            "Avg_Latency",
            "Median_Latency",
            "Std_Latency",
        ]
        return category_stats

    def plot_tool_accuracy(self, output_file: str = "01_tool_accuracy.png"):
        """도구 선택 정확도 막대 그래프"""
        fig, ax = plt.subplots(figsize=(12, 6))

        category_accuracy = (
            self.df.groupby("category")["tool_correct"]
            .agg(lambda x: x.sum() / len(x) * 100)
            .sort_values(ascending=False)
        )

        colors = [
            "#2ecc71" if x > 80 else "#f39c12" if x > 60 else "#e74c3c"
            for x in category_accuracy.values
        ]

        category_accuracy.plot(
            kind="bar", ax=ax, color=colors, alpha=0.7, edgecolor="black"
        )
        ax.set_title(
            "Tool Selection Accuracy by Category", fontsize=14, fontweight="bold"
        )
        ax.set_ylabel("Accuracy (%)", fontsize=12)
        ax.set_xlabel("Category", fontsize=12)
        ax.set_ylim([0, 105])
        ax.axhline(y=80, color="red", linestyle="--", linewidth=2, label="80% Target")
        ax.legend()

        # 수치 표시
        for i, v in enumerate(category_accuracy.values):
            ax.text(i, v + 2, f"{v:.1f}%", ha="center", va="bottom", fontweight="bold")

        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def plot_json_validity(self, output_file: str = "02_json_validity.png"):
        """JSON 유효성 비율"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # 전체 JSON 유효성 파이차트
        json_valid = self.df["json_valid"].sum()
        json_invalid = len(self.df) - json_valid

        colors_pie = ["#2ecc71", "#e74c3c"]
        ax1.pie(
            [json_valid, json_invalid],
            labels=["Valid", "Invalid"],
            autopct="%1.1f%%",
            colors=colors_pie,
            startangle=90,
            textprops={"fontsize": 12, "weight": "bold"},
        )
        ax1.set_title("Overall JSON Validity", fontsize=14, fontweight="bold")

        # 카테고리별 JSON 유효성
        category_json = (
            self.df.groupby("category")["json_valid"]
            .agg(lambda x: x.sum() / len(x) * 100)
            .sort_values(ascending=False)
        )

        category_json.plot(
            kind="barh", ax=ax2, color="#3498db", alpha=0.7, edgecolor="black"
        )
        ax2.set_title("JSON Validity Rate by Category", fontsize=14, fontweight="bold")
        ax2.set_xlabel("Valid JSON (%)", fontsize=12)
        ax2.set_xlim([0, 105])

        # 수치 표시
        for i, v in enumerate(category_json.values):
            ax2.text(v + 1, i, f"{v:.1f}%", va="center", fontweight="bold")

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def plot_latency_distribution(
        self, output_file: str = "03_latency_distribution.png"
    ):
        """레이턴시 분포"""
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # 전체 히스토그램
        axes[0, 0].hist(
            self.df["latency_ms"],
            bins=30,
            color="#3498db",
            alpha=0.7,
            edgecolor="black",
        )
        axes[0, 0].set_title(
            "Overall Latency Distribution", fontsize=12, fontweight="bold"
        )
        axes[0, 0].set_xlabel("Latency (ms)")
        axes[0, 0].set_ylabel("Count")
        axes[0, 0].axvline(
            self.df["latency_ms"].mean(),
            color="red",
            linestyle="--",
            linewidth=2,
            label=f"Mean: {self.df['latency_ms'].mean():.0f}ms",
        )
        axes[0, 0].axvline(
            self.df["latency_ms"].median(),
            color="orange",
            linestyle="--",
            linewidth=2,
            label=f"Median: {self.df['latency_ms'].median():.0f}ms",
        )
        axes[0, 0].legend()

        # 박스플롯 (카테고리별)
        self.df.boxplot(column="latency_ms", by="category", ax=axes[0, 1])
        axes[0, 1].set_title("Latency by Category", fontsize=12, fontweight="bold")
        axes[0, 1].set_xlabel("Category")
        axes[0, 1].set_ylabel("Latency (ms)")
        plt.sca(axes[0, 1])
        plt.xticks(rotation=45, ha="right")

        # 누적 분포 (CDF)
        sorted_latencies = np.sort(self.df["latency_ms"])
        cdf = np.arange(1, len(sorted_latencies) + 1) / len(sorted_latencies)
        axes[1, 0].plot(sorted_latencies, cdf, linewidth=2, color="#2ecc71")
        axes[1, 0].axvline(
            self.df["latency_ms"].quantile(0.95),
            color="orange",
            linestyle="--",
            linewidth=2,
            label="P95",
        )
        axes[1, 0].axvline(
            self.df["latency_ms"].quantile(0.99),
            color="red",
            linestyle="--",
            linewidth=2,
            label="P99",
        )
        axes[1, 0].set_title(
            "Latency CDF (Cumulative Distribution)", fontsize=12, fontweight="bold"
        )
        axes[1, 0].set_xlabel("Latency (ms)")
        axes[1, 0].set_ylabel("Cumulative Probability")
        axes[1, 0].legend()
        axes[1, 0].grid(True, alpha=0.3)

        # 카테고리별 평균 레이턴시
        avg_latency = (
            self.df.groupby("category")["latency_ms"]
            .mean()
            .sort_values(ascending=False)
        )
        colors_latency = plt.cm.RdYlGn_r(np.linspace(0.2, 0.8, len(avg_latency)))
        avg_latency.plot(
            kind="barh", ax=axes[1, 1], color=colors_latency, edgecolor="black"
        )
        axes[1, 1].set_title(
            "Average Latency by Category", fontsize=12, fontweight="bold"
        )
        axes[1, 1].set_xlabel("Average Latency (ms)")

        for i, v in enumerate(avg_latency.values):
            axes[1, 1].text(v + 10, i, f"{v:.0f}ms", va="center", fontweight="bold")

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def plot_test_results_timeline(self, output_file: str = "04_test_timeline.png"):
        """테스트 순서별 결과 (시간순)"""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))

        # 누적 성공률
        cumulative_success = (
            self.df["tool_correct"].cumsum() / np.arange(1, len(self.df) + 1) * 100
        )
        ax1.plot(
            cumulative_success, linewidth=2, color="#2ecc71", marker="o", markersize=3
        )
        ax1.fill_between(
            range(len(cumulative_success)),
            cumulative_success,
            alpha=0.3,
            color="#2ecc71",
        )
        ax1.set_title(
            "Cumulative Tool Accuracy Over Time", fontsize=12, fontweight="bold"
        )
        ax1.set_ylabel("Cumulative Accuracy (%)")
        ax1.set_ylim([0, 105])
        ax1.axhline(y=80, color="red", linestyle="--", linewidth=2, label="80% Target")
        ax1.grid(True, alpha=0.3)
        ax1.legend()

        # 개별 테스트 결과 (색상으로 표현)
        colors = ["#2ecc71" if x else "#e74c3c" for x in self.df["tool_correct"]]
        ax2.scatter(
            range(len(self.df)),
            self.df["latency_ms"],
            c=colors,
            s=50,
            alpha=0.6,
            edgecolor="black",
        )
        ax2.set_title(
            "Individual Test Results: Latency & Accuracy",
            fontsize=12,
            fontweight="bold",
        )
        ax2.set_xlabel("Test Number")
        ax2.set_ylabel("Latency (ms)")
        ax2.grid(True, alpha=0.3)

        # 범례
        from matplotlib.patches import Patch

        legend_elements = [
            Patch(facecolor="#2ecc71", label="Correct"),
            Patch(facecolor="#e74c3c", label="Incorrect"),
        ]
        ax2.legend(handles=legend_elements)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def plot_correctness_vs_latency(
        self, output_file: str = "05_correctness_vs_latency.png"
    ):
        """정확도 vs 레이턴시 산점도"""
        fig, ax = plt.subplots(figsize=(12, 6))

        # 카테고리별 색상
        categories = self.df["category"].unique()
        colors_map = plt.cm.Set3(np.linspace(0, 1, len(categories)))
        category_colors = {cat: colors_map[i] for i, cat in enumerate(categories)}

        for category in categories:
            mask = self.df["category"] == category
            correct_mask = self.df["tool_correct"][mask]

            # 정확함 (1) vs 오류 (0)
            correct_data = self.df[mask & (self.df["tool_correct"] == True)]
            incorrect_data = self.df[mask & (self.df["tool_correct"] == False)]

            ax.scatter(
                correct_data.index,
                correct_data["latency_ms"],
                s=100,
                marker="o",
                color=category_colors[category],
                alpha=0.7,
                label=f"{category} (Correct)",
                edgecolor="black",
            )

            ax.scatter(
                incorrect_data.index,
                incorrect_data["latency_ms"],
                s=100,
                marker="x",
                color=category_colors[category],
                alpha=0.7,
                label=f"{category} (Wrong)",
                linewidth=2,
            )

        ax.set_title("Latency vs Test Correctness", fontsize=14, fontweight="bold")
        ax.set_xlabel("Test Index")
        ax.set_ylabel("Latency (ms)")
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def plot_category_comparison(self, output_file: str = "06_category_comparison.png"):
        """카테고리별 종합 비교"""
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        category_stats = (
            self.df.groupby("category")
            .agg(
                {
                    "tool_correct": lambda x: x.sum() / len(x) * 100,
                    "json_valid": lambda x: x.sum() / len(x) * 100,
                    "latency_ms": "mean",
                }
            )
            .round(2)
        )

        # 도구 정확도
        category_stats["tool_correct"].sort_values(ascending=False).plot(
            kind="bar", ax=axes[0, 0], color="#3498db", alpha=0.7, edgecolor="black"
        )
        axes[0, 0].set_title(
            "Tool Accuracy by Category", fontsize=12, fontweight="bold"
        )
        axes[0, 0].set_ylabel("Accuracy (%)")
        axes[0, 0].set_ylim([0, 105])
        plt.setp(axes[0, 0].xaxis.get_majorticklabels(), rotation=45, ha="right")

        # JSON 유효성
        category_stats["json_valid"].sort_values(ascending=False).plot(
            kind="bar", ax=axes[0, 1], color="#2ecc71", alpha=0.7, edgecolor="black"
        )
        axes[0, 1].set_title(
            "JSON Validity by Category", fontsize=12, fontweight="bold"
        )
        axes[0, 1].set_ylabel("Valid (%)")
        axes[0, 1].set_ylim([0, 105])
        plt.setp(axes[0, 1].xaxis.get_majorticklabels(), rotation=45, ha="right")

        # 평균 레이턴시
        category_stats["latency_ms"].sort_values(ascending=True).plot(
            kind="barh", ax=axes[1, 0], color="#e74c3c", alpha=0.7, edgecolor="black"
        )
        axes[1, 0].set_title(
            "Average Latency by Category", fontsize=12, fontweight="bold"
        )
        axes[1, 0].set_xlabel("Latency (ms)")

        # 테스트 개수
        test_count = self.df["category"].value_counts().sort_values(ascending=False)
        test_count.plot(
            kind="bar", ax=axes[1, 1], color="#9b59b6", alpha=0.7, edgecolor="black"
        )
        axes[1, 1].set_title(
            "Number of Tests by Category", fontsize=12, fontweight="bold"
        )
        axes[1, 1].set_ylabel("Count")
        plt.setp(axes[1, 1].xaxis.get_majorticklabels(), rotation=45, ha="right")

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def plot_performance_percentiles(self, output_file: str = "07_percentiles.png"):
        """성능 백분위수 분석"""
        fig, ax = plt.subplots(figsize=(12, 6))

        percentiles = [10, 25, 50, 75, 90, 95, 99]
        latency_percentiles = [
            self.df["latency_ms"].quantile(p / 100) for p in percentiles
        ]

        bars = ax.bar(
            range(len(percentiles)),
            latency_percentiles,
            color=[
                "#2ecc71",
                "#3498db",
                "#9b59b6",
                "#f39c12",
                "#e67e22",
                "#e74c3c",
                "#c0392b",
            ],
            alpha=0.7,
            edgecolor="black",
            linewidth=2,
        )

        ax.set_title("Latency Percentiles", fontsize=14, fontweight="bold")
        ax.set_ylabel("Latency (ms)", fontsize=12)
        ax.set_xlabel("Percentile", fontsize=12)
        ax.set_xticks(range(len(percentiles)))
        ax.set_xticklabels([f"P{p}" for p in percentiles])

        # 값 표시
        for i, (bar, val) in enumerate(zip(bars, latency_percentiles)):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                val + 20,
                f"{val:.0f}ms",
                ha="center",
                va="bottom",
                fontweight="bold",
                fontsize=11,
            )

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def plot_heatmap_category_tool(self, output_file: str = "08_heatmap_accuracy.png"):
        """카테고리별 도구 정확도 히트맵"""
        fig, ax = plt.subplots(figsize=(14, 6))

        # 카테고리와 도구별 정확도
        pivot_data = self.df.pivot_table(
            values="tool_correct",
            index="category",
            columns="expected_tool",
            aggfunc=lambda x: x.sum() / len(x) * 100 if len(x) > 0 else 0,
        )

        sns.heatmap(
            pivot_data,
            annot=True,
            fmt=".1f",
            cmap="RdYlGn",
            cbar_kws={"label": "Accuracy (%)"},
            ax=ax,
            vmin=0,
            vmax=100,
        )
        ax.set_title(
            "Tool Accuracy Heatmap: Category vs Expected Tool",
            fontsize=14,
            fontweight="bold",
        )
        ax.set_xlabel("Expected Tool", fontsize=12)
        ax.set_ylabel("Category", fontsize=12)

        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"✓ 저장: {output_file}")
        plt.close()

    def generate_all_plots(self, output_dir: str = "benchmark_plots"):
        """모든 그래프 생성"""
        Path(output_dir).mkdir(exist_ok=True)

        print(f"\n{'=' * 60}")
        print("📊 벤치마크 결과 시각화 중...")
        print(f"{'=' * 60}\n")

        self.plot_tool_accuracy(f"{output_dir}/01_tool_accuracy.png")
        self.plot_json_validity(f"{output_dir}/02_json_validity.png")
        self.plot_latency_distribution(f"{output_dir}/03_latency_distribution.png")
        self.plot_test_results_timeline(f"{output_dir}/04_test_timeline.png")
        self.plot_correctness_vs_latency(f"{output_dir}/05_correctness_vs_latency.png")
        self.plot_category_comparison(f"{output_dir}/06_category_comparison.png")
        self.plot_performance_percentiles(f"{output_dir}/07_percentiles.png")
        self.plot_heatmap_category_tool(f"{output_dir}/08_heatmap_accuracy.png")

        print(f"\n{'=' * 60}")
        print(f"✓ 모든 그래프가 '{output_dir}' 디렉토리에 저장되었습니다.")
        print(f"{'=' * 60}\n")

    def print_summary(self):
        """전체 요약 출력"""
        stats = self.analyze_overall_stats()
        category_stats = self.analyze_by_category()

        print("\n" + "=" * 80)
        print("📊 OVERALL STATISTICS")
        print("=" * 80)
        print(f"Total Tests: {stats['total_tests']}")
        print(f"Tool Accuracy: {stats['tool_accuracy']:.2f}%")
        print(f"JSON Valid Rate: {stats['json_valid_rate']:.2f}%")
        print(f"\nLatency (ms)")
        print(f"  Average: {stats['avg_latency']:.2f}")
        print(f"  Median: {stats['median_latency']:.2f}")
        print(f"  P95: {stats['p95_latency']:.2f}")
        print(f"  P99: {stats['p99_latency']:.2f}")

        print("\n" + "=" * 80)
        print("📂 BY CATEGORY")
        print("=" * 80)
        print(category_stats)
        print()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="벤치마크 결과 분석 및 시각화")
    parser.add_argument("json_file", help="벤치마크 결과 JSON 파일 경로")
    parser.add_argument(
        "--output-dir",
        default="benchmark_plots",
        help="그래프 저장 디렉토리 (기본값: benchmark_plots)",
    )

    args = parser.parse_args()

    # 분석 실행
    analyzer = BenchmarkAnalyzer(args.json_file)
    analyzer.print_summary()
    analyzer.generate_all_plots(args.output_dir)


if __name__ == "__main__":
    main()
