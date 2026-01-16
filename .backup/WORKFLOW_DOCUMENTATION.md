# Reddit Curation Specialist: Workflow Documentation

This document provides a detailed technical reference for the Reddit Curation Specialist's workflow. It is intended to guide the development of a dynamic web application UI that visualizes the agent's reasoning and execution in real-time.

## 🏗️ System Architecture

The system operates on a **Reason-Act-Observe** loop, orchestrated by an AI agent using a set of specialized Python tools.

### Core Components
- **`app.py`**: Contains the `RedditSearchEngine` (PRAW integration) and `LLMFilter` (AI-powered query generation and scoring).
- **`tools.py`**: CLI entry point for the agent to execute specific tasks.
- **`search_log.json`**: Persistent storage for all search events, metadata, and results.
- **`AGENTS.md`**: Behavioral instructions for the AI agent.

---

## 🔄 The Step-by-Step Workflow

### 1. Intent Decomposition (Reasoning)
When a user enters a description (e.g., *"Find 15 stories about X"*), the agent first performs **Socratic Intent Decomposition**.
- **UI Visualization**: Show the agent's internal thoughts as it breaks down the request into core entities, assumptions, and linguistic markers.

### 2. Query Generation (`generate_query`)
The agent calls `python tools.py generate_query --description "..."`.
- **Input**: Natural language description.
- **Process**: `LLMFilter` translates the intent into a complex Boolean Lucene query.
- **Output**: A raw Boolean string.
- **UI Visualization**: Display the generated Boolean query live.

### 3. Search Execution (`execute_search`)
The agent calls `python tools.py execute_search --query "..." --subreddits "..." --limit N`.
- **Input**: Boolean query, target subreddits, and post limit.
- **Process**: `RedditSearchEngine` iterates through subreddits, fetching posts via PRAW.
- **Output**: A JSON array of raw posts (ID, Title, Subreddit, URL, Content, Timestamp, Score).
- **UI Visualization**: Show a live "Scanning r/subreddit..." status and a counter of "Posts Found" as they are retrieved.

### 4. Relevance Scoring (`score_results`)
The agent calls `python tools.py score_results --posts_file_path "..." --user_intent "..." --top_n 15`.
- **Input**: Path to raw posts JSON, original user intent, and desired number of top results.
- **Process**: `LLMFilter` analyzes each post's content against the intent, assigning a 0-100 score. Results are sorted by score.
- **Output**: A JSON array of post IDs and their scores.
- **UI Visualization**: Display a "Scoring in progress..." progress bar. Show posts appearing in a list, sorted dynamically by their relevance score.

### 5. Observation & Iteration (The Loop)
The agent analyzes the scores.
- **Condition**: If the number of posts with high scores (e.g., > 70) is less than the requested count, the agent **Refines** its plan.
- **Action**: It consults `search_log.json`, modifies the query or subreddits, and repeats steps 2-4.
- **UI Visualization**: Show a "Goal not met, refining search..." status. Display the new query and the start of the next search round.

### 6. Final Report Generation (`generate_report`)
Once the goal is met or the user stops the process, the agent calls `python tools.py generate_report`.
- **Process**: Aggregates all data from `search_log.json` into a comprehensive Markdown report.
- **Output**: `search_report.md`.
- **UI Visualization**: Present the final, formatted report with the top 15+ posts, their full details, and a summary of the search rounds.

---

## 📊 Data Structures (for Frontend Reference)

### `search_log.json` Entry Example
```json
{
  "timestamp": 1736784000.0,
  "event_type": "execute_search",
  "data": {
    "query": "(\"pool\") AND (\"assaulted\")",
    "limit": 20,
    "subreddits": "sexualassault,TwoXChromosomes",
    "results_count": 5,
    "results": [...]
  }
}
```

### `score_results` Output Example
```json
[
  { "id": "1ixl5fe", "score": 100 },
  { "id": "1q8004s", "score": 95 }
]
```

---

## 🛠️ Advanced Search Mode
For exhaustive discovery, the system can launch parallel sub-agents:
- **`explore`**: For deep codebase/file analysis.
- **`librarian`**: For external documentation and repository research.
- **Direct Tools**: `grep`, `rg`, `ast-grep` for literal pattern matching.

This multi-threaded approach ensures that no relevant information is missed across local and remote sources.
