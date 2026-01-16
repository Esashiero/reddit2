# 🕵️ Project "Reddit Detective": Autonomous Retrieval Optimization Plan

## 1. Objective
Transform the Reddit Search Engine from a keyword matcher into a multi-agent "Detective" system capable of autonomous, high-precision retrieval using Socratic reasoning, advanced Lucene syntax, and domain-specific memory.

## 2. Architectural Components

### 2.1 Socratic Intent Decomposition (The "Profiler")
- **Mechanism**: Deconstruct user descriptions into three dimensions: Clarification, Assumption Probing, and Implication Probing.
- **Tool**: Update LLMFilter.generate_boolean_string.

### 2.2 Advanced Lucene Generator (The "Locksmith")
- **Proximity Search (~N)**: Use ~10 for conversational text and ~5 for precise/technical matches.
- **Boosting (^N)**: Weight mandatory entities higher.
- **Field Filters**: Use self:true for text-only and title: for high-signal matches.

### 2.3 Subreddit-Specific Keyword Efficacy Index (KEI) (The "Memory")
- **Logic**: Store efficacy as (keyword, subreddit, efficacy_score).
- **Domain Mapping**: Weights are local to subreddits. Use Contextual Evaluation Prompt Routing.
- **Persistence**: JSON storage in benchmark_module/knowledge_store/.

### 2.4 Chronological Sliding Windows (The "Magnifying Glass")
- **Technique**: 30-day steps (after:TIMESTAMP).
- **Goal**: Bypass the 1,000-post API limit.

### 2.5 Rationale-First Evaluation (The "Judge")
- **Process**: Chain-of-Thought reasoning before scoring.
- **Output**: Structured JSON identifying Mismatch Reasons and Meta-Discussion Detection.

## 3. Implementation Phases

### Phase 1: Foundation (High Priority)
1. Rationale-First Judge: Update BenchmarkRunner._evaluate_relevance.
2. Socratic Profiler: Update LLMFilter.generate_boolean_string.
3. KEI Initialization: Implement knowledge_store.py.

### Phase 2: Search Mechanics (Medium Priority)
4. Lucene Pro: Implement proximity and boosting logic.
5. 30-Day Batches: Implement chronological loop.

### Phase 3: Loop Optimization (Medium Priority)
6. Branching Trajectories: Update auto_optimize.py for parallel queries.
7. SPO Alignment: Reduce samples to top-3 for efficiency.

## 4. Documentation Update (Proposed)
Update README.md and AGENTS.md to reflect the new "Detective" workflow and the specific parameters (30-day steps, ~10 proximity, etc.).

## 5. Next Steps
Run /start-work to begin Phase 1.
