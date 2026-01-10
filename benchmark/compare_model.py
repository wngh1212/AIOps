import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
import glob
import argparse
import os
from matplotlib.patches import Rectangle
from matplotlib.patches import FancyBboxPatch

plt.style.use('dark_background')
sns.set_palette("husl")

class ComparisonDashboard:
    def __init__(self, json_files):
        self.json_files = json_files
        self.df = self._load_data()
        self.model_stats = self._calculate_stats()
    
    def _load_data(self):
        #데이터 로드
        dfs = []
        for filepath in self.json_files:
            try:
                data = json.loads(Path(filepath).read_text(encoding='utf-8'))
                df_single = pd.DataFrame(data['results'])
                df_single['model'] = Path(filepath).parent.name
                dfs.append(df_single)
            except Exception as e:
                print(f"{filepath} load failed: {e}")
        
        combined = pd.concat(dfs, ignore_index=True)
        print(f"{len(combined)} tests loaded ({len(dfs)} models)")
        return combined
    
    def _calculate_stats(self):
        #모델별 통계 계산
        stats = {}
        
        for model in self.df['model'].unique():
            mask = self.df['model'] == model
            model_data = self.df[mask]
            
            # 전체 메트릭
            accuracy = model_data['tool_correct'].mean() * 100
            json_valid = model_data['json_valid'].mean() * 100
            avg_latency = model_data['latency_ms'].mean()
            
            # 카테고리별 메트릭
            category_accuracy = model_data.groupby('category')['tool_correct'].agg(
                lambda x: x.sum() / len(x) * 100
            )
            
            # 종합 점수 (정확도 40% + JSON 30% + 속도 20% + 안정성 10%)
            speed_score = 100 / (avg_latency / 1000 + 1)
            consistency = category_accuracy.std() if len(category_accuracy) > 1 else 0
            overall_score = (accuracy * 0.4 + json_valid * 0.3 + speed_score * 0.2 + (100 - consistency) * 0.1)
            
            stats[model] = {
                'accuracy': accuracy,
                'json_valid': json_valid,
                'avg_latency': avg_latency,
                'speed_score': speed_score,
                'consistency': 100 - min(consistency, 100),
                'overall_score': overall_score,
                'category_accuracy': category_accuracy,
                'test_count': len(model_data),
                'success_count': model_data['tool_correct'].sum(),
                'p95_latency': model_data['latency_ms'].quantile(0.95),
                'p99_latency': model_data['latency_ms'].quantile(0.99),
            }
        
        return stats
    
    def plot_grouped_comparison(self, output_file="01_grouped_comparison.png"):
        #그룹 막대 그래프 모든 메트릭 한눈에
        fig, ax = plt.subplots(figsize=(16, 9))
        
        models = list(self.model_stats.keys())
        x = np.arange(len(models))
        width = 0.2
        
        # 정규화된 메트릭 (0-100)
        metrics_data = {
            'Accuracy': [self.model_stats[m]['accuracy'] for m in models],
            'JSON Valid': [self.model_stats[m]['json_valid'] for m in models],
            'Speed Score': [self.model_stats[m]['speed_score'] for m in models],
            'Consistency': [self.model_stats[m]['consistency'] for m in models],
        }
        
        colors = ['#2ecc71', '#3498db', '#f39c12', '#e74c3c']
        
        for i, (label, values) in enumerate(metrics_data.items()):
            offset = width * (i - 1.5)
            bars = ax.bar(x + offset, values, width, label=label, 
                         color=colors[i], alpha=0.8, edgecolor='white', linewidth=2)
            
            # 값 표시
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                       f'{height:.1f}',
                       ha='center', va='bottom', fontweight='bold', fontsize=10)
        
        ax.set_xlabel('Model', fontsize=14, fontweight='bold')
        ax.set_ylabel('Score (0-100)', fontsize=14, fontweight='bold')
        ax.set_title('Clear Comparison of 4 Models: 4 Evaluation Metrics\n(Accuracy, JSON Valid, Speed, Consistency)', 
                    fontsize=16, fontweight='bold', pad=20)
        ax.set_xticks(x)
        ax.set_xticklabels([m.replace('_', '\n') for m in models], fontsize=12, fontweight='bold')
        ax.set_ylim([0, 110])
        ax.axhline(y=80, color='red', linestyle='--', linewidth=2, alpha=0.5, label='80% Threshold')
        ax.legend(fontsize=11, loc='upper left')
        ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"Saved: {output_file}")
        plt.close()
    
    def plot_overall_ranking(self, output_file="02_overall_ranking.png"):
        """종합 순위 카드"""
        fig, ax = plt.subplots(figsize=(14, 10))
        
        # 점수순 정렬
        sorted_models = sorted(self.model_stats.items(), 
                              key=lambda x: x[1]['overall_score'], reverse=True)
        
        y_pos = np.arange(len(sorted_models))
        scores = [m[1]['overall_score'] for m in sorted_models]
        model_names = [m[0].replace('_', ' ') for m in sorted_models]
        
        colors_rank = plt.cm.RdYlGn(np.linspace(0.2, 0.9, len(sorted_models)))
        
        bars = ax.barh(y_pos, scores, color=colors_rank, height=0.6, 
                      edgecolor='white', linewidth=3)
        
        # 순위 뱃지 + 점수 표시
        for i, (bar, score, name) in enumerate(zip(bars, scores, model_names)):
            # 순위 뱃지
            badges = ['1', '2', '3']
            badge = badges[i] if i < 3 else f"#{i+1}"
            ax.text(-5, bar.get_y() + bar.get_height()/2, badge,
                   va='center', fontsize=20, fontweight='bold')
            
            # 점수 표시
            ax.text(score + 1, bar.get_y() + bar.get_height()/2, f'{score:.1f} pts',
                   va='center', fontweight='bold', fontsize=12)
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(model_names, fontsize=12, fontweight='bold')
        ax.set_xlabel('Overall Score (0-100)', fontsize=13, fontweight='bold')
        ax.set_title('Overall Ranking (Accuracy 40% + JSON 30% + Speed 20% + Consistency 10%)',
                    fontsize=16, fontweight='bold', pad=20)
        ax.set_xlim([0, 105])
        ax.grid(axis='x', alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"Saved: {output_file}")
        plt.close()
    
    def plot_metrics_scorecard(self, output_file="03_metrics_scorecard.png"):
        #메트릭 스코어카드 
        fig, ax = plt.subplots(figsize=(16, 10))
        ax.axis('tight')
        ax.axis('off')
        
        models = list(self.model_stats.keys())
        
        # 테이블 데이터
        table_data = [['Metric', 'Evaluation Item'] + models]
        
        metrics = [
            ('Accuracy', 'Tool Accuracy (%)', 'accuracy'),
            ('JSON Validity', 'JSON Valid Rate (%)', 'json_valid'),
            ('Avg Latency', 'Avg Latency (ms)', 'avg_latency'),
            ('Speed Score', 'Speed Score (0-100)', 'speed_score'),
            ('Consistency', 'Consistency Score', 'consistency'),
            ('P95 Latency', 'P95 Latency (ms)', 'p95_latency'),
            ('Test Count', 'Test Count', 'test_count'),
            ('Success Count', 'Success Count', 'success_count'),
        ]
        
        for category, description, key in metrics:
            row = [category, description]
            for model in models:
                value = self.model_stats[model][key]
                if 'latency' in key.lower() or key == 'test_count' or key == 'success_count':
                    row.append(f'{value:.0f}')
                else:
                    row.append(f'{value:.1f}')
            table_data.append(row)
        
        # 테이블 생성
        table = ax.table(cellText=table_data, cellLoc='center', loc='center',
                        colWidths=[0.12, 0.2] + [0.15]*len(models))
        
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1, 2.5)
        
        # 헤더 스타일링
        for i in range(len(table_data[0])):
            table[(0, i)].set_facecolor('#1f77b4')
            table[(0, i)].set_text_props(weight='bold', color='white', fontsize=12)
        
        # 행 색상 지정
        for i in range(1, len(table_data)):
            table[(i, 0)].set_facecolor('#2c3e50')
            table[(i, 0)].set_text_props(weight='bold', color='white')
            table[(i, 1)].set_facecolor('#34495e')
            
            for j in range(2, len(models) + 2):
                if i % 2 == 0:
                    table[(i, j)].set_facecolor('#1a1a1a')
                else:
                    table[(i, j)].set_facecolor('#262626')
        
        ax.set_title('Detailed Metrics Scorecard', fontsize=18, fontweight='bold', pad=20)
        
        plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"Saved: {output_file}")
        plt.close()
    
    def plot_category_matrix(self, output_file="04_category_matrix.png"):
        #카테고리별 정확도 히트맵 모든 모델 비교
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # 데이터 준비
        models = list(self.model_stats.keys())
        categories = list(self.model_stats[models[0]]['category_accuracy'].index)
        
        matrix_data = []
        for model in models:
            row = [self.model_stats[model]['category_accuracy'].get(cat, 0) 
                   for cat in categories]
            matrix_data.append(row)
        
        matrix_array = np.array(matrix_data)
        
        # 히트맵
        sns.heatmap(matrix_array, annot=True, fmt='.1f', cmap='RdYlGn',
                   xticklabels=categories, yticklabels=models,
                   cbar_kws={'label': 'Accuracy (%)'}, ax=ax,
                   vmin=0, vmax=100, linewidths=2, linecolor='gray',
                   square=False)
        
        ax.set_title('Accuracy Comparison by Category (All Models x All Categories)',
                    fontsize=16, fontweight='bold', pad=20)
        ax.set_ylabel('Model', fontsize=12, fontweight='bold')
        ax.set_xlabel('Category', fontsize=12, fontweight='bold')
        
        # Y축 레이블 정리
        ax.set_yticklabels([m.replace('_', ' ') for m in models], rotation=0)
        ax.set_xticklabels(categories, rotation=45, ha='right')
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"Saved: {output_file}")
        plt.close()
    
    def plot_spider_comprehensive(self, output_file="05_spider_comprehensive.png"):
        #종합 레이더 차트 
        from math import pi
        
        fig, ax = plt.subplots(figsize=(14, 14), subplot_kw=dict(projection='polar'))
        
        # 메트릭 정의
        metrics = ['Accuracy', 'JSON\nValidity', 'Speed', 'Consistency']
        N = len(metrics)
        
        angles = [n / float(N) * 2 * pi for n in range(N)]
        angles += angles[:1]
        
        models = list(self.model_stats.keys())
        colors = plt.cm.Set1(np.linspace(0, 1, len(models)))
        
        for idx, (model, color) in enumerate(zip(models, colors)):
            values = [
                self.model_stats[model]['accuracy'],
                self.model_stats[model]['json_valid'],
                self.model_stats[model]['speed_score'],
                self.model_stats[model]['consistency'],
            ]
            values += values[:1]
            
            ax.plot(angles, values, 'o-', linewidth=3, label=model.replace('_', ' '),
                   color=color, markersize=8)
            ax.fill(angles, values, alpha=0.15, color=color)
        
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(metrics, fontsize=13, fontweight='bold')
        ax.set_ylim(0, 100)
        ax.set_yticks([20, 40, 60, 80, 100])
        ax.set_yticklabels(['20', '40', '60', '80', '100'], fontsize=10)
        ax.grid(True, linewidth=0.5)
        
        ax.set_title('Comprehensive Comparison of 4 Models (Accuracy, JSON, Speed, Consistency)',
                    fontsize=18, fontweight='bold', pad=30)
        ax.legend(loc='upper right', bbox_to_anchor=(1.25, 1.1), fontsize=12)
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"Saved: {output_file}")
        plt.close()
    
    def plot_summary_report(self, output_file="06_summary_report.png"):
        #종합 리포트 (텍스트 + 차트)
        fig = plt.figure(figsize=(16, 12))
        gs = fig.add_gridspec(3, 2, hspace=0.4, wspace=0.3)
        
        # 제목
        ax_title = fig.add_subplot(gs[0, :])
        ax_title.axis('off')
        ax_title.text(0.5, 0.7, 'AIOps LLM Benchmark Final Report',
                     ha='center', va='center', fontsize=28, fontweight='bold',
                     transform=ax_title.transAxes)
        ax_title.text(0.5, 0.2, f'Analysis of Total {len(self.df)} Test Results',
                     ha='center', va='center', fontsize=14, color='gray',
                     transform=ax_title.transAxes)
        
        # 순위표
        ax1 = fig.add_subplot(gs[1, 0])
        sorted_models = sorted(self.model_stats.items(), 
                              key=lambda x: x[1]['overall_score'], reverse=True)
        y_pos = np.arange(len(sorted_models))
        scores = [m[1]['overall_score'] for m in sorted_models]
        names = [m[0].replace('_', ' ') for m in sorted_models]
        colors_rank = plt.cm.RdYlGn(np.linspace(0.2, 0.9, len(sorted_models)))
        
        bars = ax1.barh(y_pos, scores, color=colors_rank, edgecolor='white', linewidth=2)
        for i, (bar, score) in enumerate(zip(bars, scores)):
            ax1.text(score + 1, bar.get_y() + bar.get_height()/2, f'{score:.1f}',
                    va='center', fontweight='bold', fontsize=11)
        
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(names, fontsize=11, fontweight='bold')
        ax1.set_xlabel('Overall Score', fontsize=11, fontweight='bold')
        ax1.set_title('Overall Ranking', fontsize=13, fontweight='bold', pad=10)
        ax1.set_xlim([0, 105])
        ax1.grid(axis='x', alpha=0.2)
        
        # 정확도 비교
        ax2 = fig.add_subplot(gs[1, 1])
        accuracy_vals = [self.model_stats[m]['accuracy'] for m in sorted_models]
        ax2.bar(range(len(sorted_models)), accuracy_vals, color=['#2ecc71', '#3498db', '#f39c12', '#e74c3c'][:len(sorted_models)],
               edgecolor='white', linewidth=2, alpha=0.8)
        for i, v in enumerate(accuracy_vals):
            ax2.text(i, v + 1, f'{v:.1f}%', ha='center', fontweight='bold', fontsize=11)
        ax2.set_xticks(range(len(sorted_models)))
        ax2.set_xticklabels([n.split()[0] for n in names], fontsize=10, fontweight='bold')
        ax2.set_ylabel('Accuracy (%)', fontsize=11, fontweight='bold')
        ax2.set_title('Accuracy (40% Weight)', fontsize=13, fontweight='bold', pad=10)
        ax2.set_ylim([0, 105])
        ax2.axhline(y=80, color='red', linestyle='--', linewidth=1.5, alpha=0.5)
        
        # 레이턴시 비교
        ax3 = fig.add_subplot(gs[2, 0])
        latency_vals = [self.model_stats[m]['avg_latency'] for m in sorted_models]
        colors_latency = ['#e74c3c' if v > 2500 else '#f39c12' if v > 2000 else '#2ecc71' for v in latency_vals]
        ax3.bar(range(len(sorted_models)), latency_vals, color=colors_latency, edgecolor='white', linewidth=2, alpha=0.8)
        for i, v in enumerate(latency_vals):
            ax3.text(i, v + 50, f'{v:.0f}ms', ha='center', fontweight='bold', fontsize=11)
        ax3.set_xticks(range(len(sorted_models)))
        ax3.set_xticklabels([n.split()[0] for n in names], fontsize=10, fontweight='bold')
        ax3.set_ylabel('Latency (ms)', fontsize=11, fontweight='bold')
        ax3.set_title('Average Latency (Lower is Better)', fontsize=13, fontweight='bold', pad=10)
        
        # JSON 유효성
        ax4 = fig.add_subplot(gs[2, 1])
        json_vals = [self.model_stats[m]['json_valid'] for m in sorted_models]
        ax4.bar(range(len(sorted_models)), json_vals, color='#3498db', edgecolor='white', linewidth=2, alpha=0.8)
        for i, v in enumerate(json_vals):
            ax4.text(i, v + 1, f'{v:.1f}%', ha='center', fontweight='bold', fontsize=11)
        ax4.set_xticks(range(len(sorted_models)))
        ax4.set_xticklabels([n.split()[0] for n in names], fontsize=10, fontweight='bold')
        ax4.set_ylabel('Valid (%)', fontsize=11, fontweight='bold')
        ax4.set_title('JSON Validity (30% Weight)', fontsize=13, fontweight='bold', pad=10)
        ax4.set_ylim([0, 105])
        ax4.axhline(y=95, color='green', linestyle='--', linewidth=1.5, alpha=0.5)
        
        plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"Saved: {output_file}")
        plt.close()
    
    def print_text_report(self):
        """텍스트 리포트 출력"""
        print("\n" + "="*80)
        print("AIOps LLM Benchmark Final Report")
        print("="*80 + "\n")
        
        sorted_models = sorted(self.model_stats.items(), 
                              key=lambda x: x[1]['overall_score'], reverse=True)
        
        for i, (model, stats) in enumerate(sorted_models, 1):
            badges = ['1', '2', '3']
            badge = badges[i-1] if i <= 3 else f"  #{i}"
            
            print(f"{badge} {model.upper()}")
            print(f"   Final Score: {stats['overall_score']:.1f}/100")
            print(f"   Accuracy: {stats['accuracy']:.1f}% (40% Weight)")
            print(f"   JSON Validity: {stats['json_valid']:.1f}% (30% Weight)")
            print(f"   Speed Score: {stats['speed_score']:.1f}/100 (20% Weight)")
            print(f"   Consistency: {stats['consistency']:.1f}/100 (10% Weight)")
            print(f"   Avg Latency: {stats['avg_latency']:.0f}ms")
            print(f"   Success Rate: {stats['success_count']}/{stats['test_count']} tests")
            print()
    
    def generate_all(self, output_dir="final_comparison"):
        #모든 그래프 생성
        Path(output_dir).mkdir(exist_ok=True)
        
        print("\n" + "="*70)
        print("Generating 4-model comparison dashboard...")
        print("="*70)
        
        self.plot_grouped_comparison(f"{output_dir}/01_grouped_comparison.png")
        self.plot_overall_ranking(f"{output_dir}/02_overall_ranking.png")
        self.plot_metrics_scorecard(f"{output_dir}/03_metrics_scorecard.png")
        self.plot_category_matrix(f"{output_dir}/04_category_matrix.png")
        self.plot_spider_comprehensive(f"{output_dir}/05_spider_comprehensive.png")
        self.plot_summary_report(f"{output_dir}/06_summary_report.png")
        
        self.print_text_report()
        
        print("="*70)
        print(f"Comparison charts saved in '{output_dir}'")
        print("="*70)

def find_latest_files():
    #최신 벤치마크 파일 자동 검색
    files = glob.glob("benchmark_results/*/*.json", recursive=True)
    if not files:
        raise FileNotFoundError("No JSON files found in benchmark_results folder!")
    
    models = {}
    for f in files:
        model = Path(f).parent.name
        models.setdefault(model, []).append(f)
    
    latest_files = [max(models[model], key=os.path.getmtime) for model in models]
    print(f"Detected {len(latest_files)} models:")
    for f in latest_files:
        print(f"  • {Path(f).parent.name}")
    return latest_files

def main():
    parser = argparse.ArgumentParser(description="4-model comparison dashboard")
    parser.add_argument("--dir", nargs="*", help="Specific folders (auto if omitted)")
    parser.add_argument("--output", default="final_comparison", help="Output folder")
    args = parser.parse_args()
    
    try:
        json_files = args.dir or find_latest_files()
        dashboard = ComparisonDashboard(json_files)
        dashboard.generate_all(args.output)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()