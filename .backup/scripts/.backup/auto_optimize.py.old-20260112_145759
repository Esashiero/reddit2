#!/usr/bin/env python3
import sys
import os
import argparse
import json
from pprint import pprint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark_module.benchmarking import BenchmarkRunner


def main():
    parser = argparse.ArgumentParser(description="Auto-Optimize Reddit Search Queries")
    parser.add_argument("--description", type=str, required=True, help="Description of what you are looking for")
    parser.add_argument("--provider", type=str, default="mistral", choices=["mistral", "gemini"], help="LLM Provider")
    parser.add_argument("--limit", type=int, default=3, help="Number of posts to fetch per variation")
    parser.add_argument("--eval-limit", type=int, default=3, help="Number of posts to evaluate per variation (Mistral SPO default: 3)")
    parser.add_argument("--iterations", type=int, default=1, help="Number of optimization iterations")
    parser.add_argument("--out", type=str, default="benchmarks", help="Output directory")

    args = parser.parse_args()

    runner = BenchmarkRunner(provider=args.provider, storage_dir=args.out)

    current_variations = [
        {"type": "standard", "limit": args.limit},
        {"type": "deep_scan", "limit": args.limit, "is_deep_scan": True, "sort_by": "top"},
    ]

    print(f"🚀 Starting Auto-Optimization for: '{args.description}'")
    print(f"   Provider: {args.provider}")

    trajectories = {}
    best_score = -1.0
    best_trajectory = None

    for i in range(args.iterations):
        print(f"\n--- 🔄 Iteration {i + 1}/{args.iterations} ---")

        if len(current_variations) > 2:
            avg_rewards = {}
            for v_type, data in trajectories.items():
                avg_rewards[v_type] = data["reward"] / data["count"]

            sorted_variations = sorted(
                current_variations,
                key=lambda v: avg_rewards.get(v.get("type", ""), 0),
                reverse=True,
            )

            print(f"   🌿 Pruning trajectories based on cumulative rewards:")
            for v in sorted_variations:
                v_type = v.get("type", "unknown")
                avg_r = avg_rewards.get(v_type, 0)
                print(f"      {v_type:<15} avg reward: {avg_r:.1f}")

            current_variations = sorted_variations[:2]
            print(f"   → Kept: {[v['type'] for v in current_variations]}")

        print(f"   Variations to test: {len(current_variations)}")

        for v in current_variations:
            v["eval_limit"] = args.eval_limit

        saved_path, analysis_data = runner.run_benchmark_suite(args.description, current_variations)

        print(f"\n✅ Iteration complete!")
        print(f"📂 Results: {saved_path}")

        run = runner.storage.load_run(os.path.basename(saved_path))
        if run:
            print("\n📊 Summary:")
            current_best = -1.0
            for var in run.variations:
                m = var["metrics"]
                score = m["average_score"]
                v_type = var["type"]

                if v_type not in trajectories:
                    trajectories[v_type] = {"reward": 0.0, "count": 0}
                trajectories[v_type]["reward"] += score
                trajectories[v_type]["count"] += 1

                avg_reward = trajectories[v_type]["reward"] / trajectories[v_type]["count"]
                if avg_reward > best_score:
                    best_score = avg_reward
                    best_trajectory = v_type

                profiled = m.get("profiled_subreddits", [])
                profiled_str = f" | 🔍 Profiled: {len(profiled)}" if profiled else ""

                print(
                    f"   Variation: {v_type:<15} | Found: {m['found_count']:<2} | Avg Score: {score:.1f} | Cumulative: {avg_reward:.1f}{profiled_str}"
                )
                current_best = max(current_best, score)

        if analysis_data.get("proposed_variations"):
            print("\n🧠 AI Analysis:")
            print(f"   {analysis_data.get('text')}")

            current_variations = analysis_data["proposed_variations"]

            print(f"   Next proposed trajectories: {[v['type'] for v in current_variations]}")
        else:
            print("\n🛑 No more improvements suggested. Converged.")
            break

        if best_score >= 9.0:
            print("\n🎯 High relevance achieved (9.0+). Stopping early.")
            break

    if best_trajectory:
        print(f"\n🏆 Best trajectory: {best_trajectory} (avg reward: {best_score:.1f})")


if __name__ == "__main__":
    main()
