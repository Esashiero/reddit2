# AGENTS.md

> **Note for Agents:** This file contains instructions for the **Agent-Mediated Dialogic (AMD)** framework implemented in this project.

## 🧠 Autonomous Retrieval Architecture

### 1. Socratic Intent Decomposition
Agents MUST decompose search descriptions along three axes before generating Lucene strings:
1. **Clarification**: Refine the core intent.
2. **Assumption Probing**: Surface implicit needs (e.g., entity attributes).
3. **Implication Probing**: Predict downstream linguistic patterns.

### 2. Keyword Efficacy Index (KEI)
Historical performance is stored in `benchmarks/`. 
- **Format**: `(keyword, subreddit, efficacy_score)`.
- **Constraint**: Efficacy is local to subreddits to avoid topic drift.
- **Usage**: Use Boosting (`^N`) for positive efficacy and Prohibition (`-`) for negative efficacy.

### 3. Lucene Operator Standards
- **General Stories**: Use Proximity `~10`.
- **Technical/Logic**: Use Proximity `~5`.
- **Exclusion**: Use `self:true` to force text-only posts.

## 🚀 Optimization Workflow

### Phase 1: Baseline
Run `benchmark_semantic.py` or `auto_optimize.py` to establish an initial score.

### Phase 2: Multi-Pass Analysis (SiGIR)
The `_analyze_results` method performs a 3-pass reasoning:
1. **Historical Critique**: Why did the previous iteration fail?
2. **Intent Refinement**: Are there unresolved information gaps?
3. **Synthesis**: Propose a new query using advanced operators.

### Phase 3: Trajectory Pruning
If using branching exploration, the loop retains only the top-k most promising "reasoning trajectories" based on cumulative relevance rewards.

## 🧪 Commands Reference

### Run Optimization
```bash
python scripts/auto_optimize.py --description "..." --iterations 5 --limit 10 --provider mistral
```

Options:
- `--description`: What you're searching for (required)
- `--iterations`: Number of optimization loops (default: 1)
- `--limit`: Posts per variation (default: 3)
- `--eval-limit`: Posts to evaluate per variation (default: 3)
- `--provider`: AI provider - mistral or gemini (default: mistral)
- `--out`: Output directory (default: benchmarks)

### Run Manual Benchmark
```bash
python scripts/benchmark_semantic.py --description "..." --manual-query "..."
```

### Update Summary
```bash
python scripts/generate_summary.py
```

Generates visual trend report in `benchmarks/SUMMARY.md` with:
- Directional trends (→)
- Historical context (...)
- Status indicators (✅ Optimal, 🛑 Plateaued, 📈 Improving)
- Top mismatches
- Best performing trajectory

## 📝 Code Style
- **Rationale-First**: Always generate an internal rationale (CoT) before outputting scores or queries.
- **Structured JSON**: Evaluation and Analysis must return machine-readable JSON.
- **Trajectory Tracking**: Use cumulative rewards to prune underperforming search branches.
- **Subreddit Profiling**: Auto-profile new high-relevance subreddits for metadata and tags.
