# 🤖 Reddit AI Curator

> **🤖 For AI Agents:** Please refer to [`AGENTS.md`](AGENTS.md) for your operational instructions, available tools, and workflow patterns.

**Reddit AI Curator** is a toolbox for an intelligent agent designed to find high-quality Reddit discussions based on your specific needs. It replaces manual searching and scripting with a powerful, agent-driven workflow.

---

## 🕵️ The Agentic Framework

This project has pivoted from a script-based system to an **Agentic Tool-Use** model. Instead of running a hard-coded optimization loop, you now instruct a CLI-based AI agent (like `opencode`, Gemini-CLI, etc.), which uses the tools provided in this repository to find, filter, and score content.

The agent follows a **Reason-Act-Observe** loop, allowing it to self-correct and refine its strategy, just like a human researcher.

### Core Components of the Framework

1.  **Socratic Intent Decomposition**
    The agent is instructed to first break down your request to understand its core components, assumptions, and linguistic markers before it even attempts a search.

2.  **Toolbox (`tools.py`)**
    The agent has access to a set of simple, powerful command-line tools:
    -   **`generate_query`**: Translates your natural language into a precise Reddit Boolean search string.
    -   **`execute_search`**: Runs the search on Reddit and fetches candidate posts.
    -   **`score_results`**: Uses an LLM to score the relevance of the found posts against your original, nuanced intent.

3.  **The Agentic Loop (Reason-Act-Observe)**
    The agent, not a script, drives the process:
    -   **Reason**: It formulates a plan (e.g., "First, I'll generate a query...").
    -   **Act**: It calls the appropriate tool from `tools.py`.
    -   **Observe**: It analyzes the output.
    -   **Refine**: If the results are poor, it critiques its own work, refines the query, and tries again.

This approach is far more flexible and powerful than the previous `auto_optimize.py` script.

---

## 🚀 Usage

The primary way to use this project is by directing a capable CLI agent to use the provided `tools.py` script.

### Example Agentic Session

**1. Your Instruction to the Agent:**
```
> agent "Find me first-person stories on Reddit where a woman was assaulted in a public pool by a stranger, but I only want stories with a lot of detail."
```

**2. The Agent's Internal Monologue & Actions:**
*   **Reasoning**: "I'll start by generating a query."
*   **Action**: `> python tools.py generate_query --description "..."`
*   **Observation**: Gets a query: `(pool AND stranger AND assaulted...)`
*   **Reasoning**: "Now I'll search for 20 posts with this query."
*   **Action**: `> python tools.py execute_search --query "..." --limit 20`
*   **Observation**: Gets a list of 20 posts.
*   **Reasoning**: "Time to score these posts against the user's detailed request."
*   **Action**: `> python tools.py score_results --posts_json "[...]" --user_intent "..."`
*   **Observation & Refinement**: "Scores are low. Too many news articles. I'll add `-flair:news` and `self:true` to the query and re-run the search and score steps."

This loop continues until the agent is satisfied with the quality of the results.

---

## 🛠️ Prerequisites & Configuration
- **A capable CLI-based AI Agent** (e.g., opencode, a custom LangChain/LlamaIndex agent).
- **Python 3.10+**
- **Reddit API Credentials** (Client ID, Secret, User Agent) in a `.env` file.
- **AI Provider Keys** (Mistral or Gemini) in a `.env` file for the underlying tools.

**License:** MIT
# reddit2
