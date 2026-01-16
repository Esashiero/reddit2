import os
import json
import time
from collections import defaultdict, Counter


def update_summary(base_dir="benchmarks"):
    summary_file = os.path.join(base_dir, "SUMMARY.md")
    runs = []

    for d in os.listdir(base_dir):
        if d.startswith("run_") and os.path.isdir(os.path.join(base_dir, d)):
            res_path = os.path.join(base_dir, d, "results.json")
            if os.path.exists(res_path):
                with open(res_path, "r") as f:
                    try:
                        data = json.load(f)
                        data["_dir"] = d
                        runs.append(data)
                    except json.JSONDecodeError:
                        continue

    tracks = defaultdict(list)
    for r in runs:
        tracks[r["description"]].append(r)

    for desc in tracks:
        tracks[desc].sort(key=lambda x: x.get("timestamp", 0))

    with open(summary_file, "w") as f:
        f.write("# 📈 Reddit Detective - Benchmark Optimization Summary\n\n")
        f.write(
            "| Date | Description | Best Score | Trend | Status | Top Mismatches | Trajectory | Link |\n"
        )
        f.write(
            "|------|-------------|------------|-------|--------|----------------|------------|------|\n"
        )

        all_runs_sorted = sorted(
            runs, key=lambda x: x.get("timestamp", 0), reverse=True
        )

        for r in all_runs_sorted:
            date_str = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(r["timestamp"])
            )
            desc = r["description"]

            history = [h for h in tracks[desc] if h["timestamp"] <= r["timestamp"]]
            score_history = [
                max(v["metrics"]["average_score"] for v in h["variations"])
                for h in history
                if h["variations"]
            ]

            current_best = score_history[-1] if score_history else 0

            mismatch_summary = []
            if r["variations"]:
                all_mismatches = []
                for v in r["variations"]:
                    for res in v["results"]:
                        all_mismatches.extend(
                            res.get("feedback", {}).get("mismatch_reasons", [])
                        )

                top_mismatches = Counter(all_mismatches).most_common(3)
                mismatch_summary = [f"{m} ({c})" for m, c in top_mismatches]

            if len(score_history) > 1:
                trend_str = " → ".join([f"{s:.1f}" for s in score_history[-3:]])
                if len(score_history) > 3:
                    trend_str = "... " + trend_str
            else:
                trend_str = f"{current_best:.1f}"

            if current_best >= 9.0:
                status = "✅ Optimal"
            elif len(score_history) > 1:
                delta = score_history[-1] - score_history[-2]
                if delta < 0.2:
                    status = "🛑 Plateaued"
                else:
                    status = "📈 Improving"
            else:
                status = "🔍 First Run"

            best_trajectory = None
            if r["variations"]:
                best_var = max(
                    r["variations"], key=lambda v: v["metrics"]["average_score"]
                )
                best_trajectory = best_var.get("type", "unknown")

            run_id = r["run_id"][:8]
            mismatch_str = ", ".join(mismatch_summary) if mismatch_summary else "None"
            trajectory_str = best_trajectory if best_trajectory else "N/A"

            f.write(
                f"| {date_str} | {desc[:40]}... | **{current_best:.1f}** | {trend_str} | {status} | {mismatch_str} | {trajectory_str} | [View](./{r['_dir']}/results.json) |\n"
            )

        f.write("\n## 📊 Visual Trend Legend\n\n")
        f.write("- **→** Directional trend (improving or declining)\n")
        f.write("- **...**: Historical context (3+ data points)\n")
        f.write("- **✅ Optimal**: Score >= 9.0 (high relevance achieved)\n")
        f.write("- **🛑 Plateaued**: Improvement < 0.2 from previous iteration\n")
        f.write("- **🔍 First Run**: Initial benchmark without history\n\n")


if __name__ == "__main__":
    update_summary()
