# AI Agent & Model Selection Guide

**Purpose:** Optimize your OpenCode agent workflows by using the right tool and model for each task, maximizing efficiency and minimizing costs.

---

## Table of Contents

1. [Overview of Your Stack](#overview-of-your-stack)
2. [Agent Model Assignments](#agent-model-assignments)
3. [Tool Selection Guide](#tool-selection-guide)
4. [Model Selection by Task Type](#model-selection-by-task-type)
5. [Provider Rate Limits & Quotas](#provider-rate-limits--quotas)
6. [Common Workflows](#common-workflows)

---

## Overview of Your Stack

You have three addon systems installed:

| Addon | Purpose | Key Features |
|--------|----------|---------------|
| **oh-my-opencode** | Main orchestration with specialized subagents | Parallel execution, LSP tools, MCP integration |
| **OpenAgents** | Plan-first development workflows | Approval-based execution, automatic testing, code review |
| **opencode-antigravity-auth** | Google OAuth for Antigravity models | Multi-account load balancing, thinking models, free tier |

---

## Agent Model Assignments

### Current Configuration (`~/.config/opencode/oh-my-opencode.json`)

| Agent | Model | Provider | Why This Model? |
|--------|--------|-----------|------------------|
| **Sisyphus** (main orchestrator) | `google/antigravity-claude-sonnet-4.5-thinking:low` | Balanced reasoning (8k thinking budget) + good coding capability |
| **Explore** (fast codebase search) | `google/antigravity-gemini-3-flash` | Fast, multimodal, flash-level reasoning for quick pattern discovery |
| **Librarian** (docs + OSS research) | `google/antigravity-gemini-3-flash` | Fast comprehension, low latency for doc lookups |
| **Oracle** (deep reasoning) | `google/antigravity-claude-opus-4.5-thinking:max` | Maximum intelligence with 32k thinking budget |
| **Frontend UI/UX Engineer** | `google/antigravity-gemini-3-pro` | Strong coding + visual capabilities for UI work |
| **Document Writer** | `google/antigravity-gemini-3-pro` | Strong language skills, high-quality output |
| **Multimodal Looker** | `google/antigravity-gemini-3-flash` | Vision capable, fast multimodal processing |

---

## Tool Selection Guide

### When to Use Direct Tools vs. Agents

| Scenario | Recommended Approach | Why? |
|----------|---------------------|---------|
| **Single file edit** | Direct tools (`edit`, `write`) | No overhead, immediate result |
| **Multi-file refactoring** | `lsp_rename`, `ast_grep_replace` | Safe, surgical changes |
| **Code search** | `explore` agent (background) | Context-aware search, finds patterns |
| **External docs/research** | `librarian` agent (background) | Searches official docs + GitHub examples |
| **Architecture decisions** | `oracle` agent | Deep reasoning, considers tradeoffs |
| **Visual/UI changes** | `frontend-ui-ux-engineer` agent | Specialized in visual design |
| **Documentation** | `document-writer` agent | Professional prose, clear structure |
| **Complex multi-step task** | `background_task` + parallel agents | Maximizes throughput |
| **Plan-first approach** | `openagent` / `opencoder` (OpenAgents) | Approval-based execution, quality checks |

---

## Model Selection by Task Type

### 🚀 **Speed-Critical Tasks** (Low Latency Priority)

**Use Case:** Quick searches, simple questions, pattern matching, background agents

| Model | Provider | Rate Limit | Best For |
|--------|-----------|-------------|-----------|
| `google/antigravity-gemini-3-flash` | Antigravity | Free tier | Fast exploration, pattern matching, simple queries |
| `google/antigravity-gemini-3-pro` | Antigravity | Free tier | High-quality exploration, better comprehension |

**Why:** Gemini 3 Flash has extremely low latency and good comprehension, perfect for:
- Background `explore` agents (parallel searches)
- Background `librarian` agents (doc lookups)
- Quick code navigation
- Simple question answering

**Note:** Add OpenRouter/Groq providers via OpenCode GUI if you need their higher rate limits for background tasks.

---

### 🧠 **Deep Reasoning Tasks** (Intelligence Priority)

**Use Case:** Architecture design, complex debugging, security analysis, multi-system tradeoffs

| Model | Provider | Thinking Budget | Best For |
|--------|-----------|-----------------|-----------|
| `google/antigravity-claude-opus-4.5-thinking:max` | Antigravity | 32k tokens | Oracle - architecture, strategy, deep analysis |
| `google/antigravity-claude-sonnet-4.5-thinking:max` | Antigravity | 32k tokens | Complex debugging, security review |
| `tngtech/deepseek-r1t-chimera:free` | OpenRouter | - | Alternative reasoning model, chain-of-thought |
| `deepseek/deepseek-r1-0528:free` | OpenRouter | - | Open-source reasoning alternative |

**Why:** Thinking models explicitly allocate tokens to reasoning before generating output. Use when:
- Designing architecture from scratch
- Debugging complex, multi-file issues
- Analyzing security vulnerabilities
- Evaluating tradeoffs between approaches

---

### 💻 **Coding Tasks** (Code Generation Priority)

**Use Case:** Implementation, refactoring, code generation, feature development

| Model | Provider | Rate Limit | Best For |
|--------|-----------|-------------|-----------|
| `google/antigravity-claude-sonnet-4.5-thinking:low` | Antigravity | 8k thinking | Sisyphus - balanced coding + reasoning |
| `kwaipilot/kat-coder-pro:free` | OpenRouter | 20 req/min | Frontend coding specialist |
| `qwen/qwen3-coder:free` | OpenRouter | 20 req/min | Coding-focused variant |
| `groq/llama-3.3-70b-versatile` | Groq | 1,000 req/day | Medium-sized coding tasks |
| `openrouter/meta-llama/llama-3.1-405b:free` | OpenRouter | 20 req/min | Large-scale code generation |

**Why:** These models excel at generating clean, functional code with proper syntax:
- `claude-sonnet-4.5-thinking` for balanced approach
- `kat-coder-pro` for frontend/visual tasks
- `llama-405b` for large context codebase refactoring

---

### 📝 **Documentation Tasks** (Language Quality Priority)

**Use Case:** Writing docs, README, API docs, guides, explanations

| Model | Provider | Rate Limit | Best For |
|--------|-----------|-------------|-----------|
| `qwen/qwen3-32b:free` | OpenRouter | 20 req/min, 50 req/day | General documentation, clear explanations |
| `google/antigravity-gemini-3-pro:high` | Antigravity | Free tier | Technical documentation, structured output |
| `groq/llama-3.3-70b-versatile` | Groq | 1,000 req/day | High-volume doc generation |

**Why:** These models excel at:
- Clear, readable prose
- Structured technical explanations
- Proper formatting (markdown, tables, code blocks)
- Maintaining consistency across sections

---

### 🖼️ **Multimodal Tasks** (Vision Priority)

**Use Case:** Analyzing images, PDFs, diagrams, screenshots

| Model | Provider | Capabilities | Best For |
|--------|-----------|--------------|-----------|
| `google/antigravity-gemini-3-flash` | Antigravity | Text, image, PDF | General multimodal analysis |
| `google/antigravity-gemini-3-pro:high` | Antigravity | Text, image, PDF | Detailed visual analysis |
| `nvidia/nemotron-nano-9b-v2:free` | OpenRouter | Vision | Lightweight image analysis |

**Why:** Multimodal models can:
- Extract text from images/PDFs
- Analyze screenshots for UI issues
- Read diagrams and architecture drawings
- Generate images (if needed)

---

### 🔍 **Search & Exploration** (Pattern Discovery Priority)

**Use Case:** Finding code patterns, understanding codebase, locating implementations

| Model | Provider | Rate Limit | Best For |
|--------|-----------|-------------|-----------|
| `qwen/qwen3-4b:free` | OpenRouter | 20 req/min | Ultra-fast exploration |
| `google/gemma-3n-e2b-it:free` | OpenRouter | 20 req/min | Minimal context pattern search |
| `groq/llama-3.1-8b-instant` | Groq | 14,400 req/day | High-throughput exploration |

**Why:** Fire multiple `explore` agents in parallel with tiny models:
```python
# Parallel exploration (recommended pattern)
background_task(agent="explore", prompt="Find all CLI entry points")
background_task(agent="explore", prompt="Map argument parser usage")
background_task(agent="explore", prompt="Search for help text patterns")
```

---

## Provider Rate Limits & Quotas

### OpenRouter & Groq (Optional Add-ons)

**Note:** Configure these providers via OpenCode GUI if you need higher rate limits for background tasks.

**Quotas:**
- OpenRouter: 20 req/min, 50 req/day free tier (up to 1,000 with $10 topup)
- Groq: Up to 14,400 req/day for tiny models

**When to Add:**
```bash
opencode provider add openrouter
opencode provider add groq
```

### Groq

**Per-Model Limits:**
- `llama-3.1-8b-instant`: 14,400 requests/day, 6,000 tokens/minute
- `llama-3.3-70b-versatile`: 1,000 requests/day, 12,000 tokens/minute
- `qwen-2.5-32b-instruct`: 1,000 requests/day, 6,000 tokens/minute
- `openai/gpt-oss-120b`: 1,000 requests/day, 8,000 tokens/minute

**When to Use:**
- High-throughput background agents (Librarian)
- Long-running tasks with many requests
- When OpenRouter quota is exhausted

### Google Antigravity (Free Tier)

**Free Tier Benefits:**
- High rate limits (not strictly documented)
- Access to Claude and Gemini 3 models
- Multi-account load balancing
- Extended thinking support

**Key Models:**
- `antigravity-claude-sonnet-4.5-thinking` - Balanced reasoning + coding
- `antigravity-claude-opus-4.5-thinking` - Maximum reasoning
- `antigravity-gemini-3-pro` - Capable multimodal
- `antigravity-gemini-3-flash` - Fast multimodal

**When to Use:**
- Oracle (deep reasoning with Opus)
- Sisyphus (balanced coding with Sonnet)
- Multimodal tasks (Gemini models)
- When you need extended thinking for complex problems

---

## Common Workflows

### Workflow 1: Python CLI Analysis (Your Current Task)

**Goal:** Analyze a Python CLI tool with dozens of scripts to improve interface and usability

**Step 1: Parallel Codebase Understanding**
```python
# Fire in parallel - use tiny models for speed
background_task(agent="explore", prompt="Map CLI structure - entry points, commands, argument parsers")
background_task(agent="explore", prompt="Find all Python CLI patterns - argparse/click/typer usage")
background_task(agent="codebase-pattern-analyst", prompt="Analyze command organization and patterns")
```

**Step 2: External Best Practices Research**
```python
# Research in parallel - use small models
background_task(agent="librarian", prompt="Research Python CLI best practices - click vs argparse vs typer")
background_task(agent="librarian", prompt="Find examples of well-structured CLIs - pytest, pip, aws-cli")
```

**Step 3: Wait for Results**
```python
# Collect results when needed
result1 = background_output(task_id="...")
result2 = background_output(task_id="...")
# Continue with analysis
```

**Step 4: Architecture Review**
```python
# Use Oracle for deep reasoning
ask @oracle to review CLI architecture and propose improvements
```

**Step 5: Implementation**
```python
# Use Sisyphus with balanced thinking model
# Or use OpenAgents opencoder for plan-first approach
```

**Step 6: Documentation**
```python
# Use document-writer for improved docs
```

---

### Workflow 2: Feature Development

**Goal:** Implement a new feature from scratch

**Step 1: Planning**
```bash
# Use OpenAgents with plan-first workflow
opencode --agent openagent
> "Add user authentication system"

# OpenAgent will:
# 1. Propose implementation plan
# 2. Wait for approval
# 3. Execute step-by-step
```

**Step 2: Coding**
```python
# Sisyphus handles implementation
# Uses claude-sonnet-4.5-thinking for balanced coding
```

**Step 3: Testing & Review**
```python
# OpenAgents automatically delegates to:
# - @tester for test creation
# - @reviewer for security review
# - @build-agent for type checking
```

---

### Workflow 3: Code Refactoring

**Goal:** Improve existing code quality

**Step 1: Analysis**
```python
# Use parallel explore agents
background_task(agent="explore", prompt="Find all uses of X pattern")
background_task(agent="explore", prompt="Search for Y anti-patterns")
```

**Step 2: Safe Refactoring**
```python
# Use LSP tools for surgical changes
lsp_rename(filePath="...", line=..., character=..., newName="...")
ast_grep_replace(pattern="...", rewrite="...", lang="python")
```

**Step 3: Verification**
```bash
# Use /test command
/test
```

---

### Workflow 4: Deep Debugging

**Goal:** Fix complex, multi-file issues

**Step 1: Investigation**
```python
# Use explore agents in parallel
background_task(agent="explore", prompt="Find all files related to X functionality")
background_task(agent="explore", prompt="Search for error patterns matching Y")
```

**Step 2: Deep Analysis**
```python
# Use Oracle for root cause analysis
ask @oracle to analyze the issue and propose fix approach
```

**Step 3: Implementation**
```python
# Use Sisyphus to implement fix
```

**Step 4: Verification**
```bash
/test
/optimize
```

---

## Tool & Agent Quick Reference

### Oh-My-OpenCode Agents

| Agent | Model | Use When |
|--------|--------|----------|
| **Sisyphus** (main) | `claude-sonnet-4.5-thinking:low` | Default orchestrator, balanced coding |
| **Explore** | `qwen3-4b:free` | Codebase search, pattern finding |
| **Librarian** | `llama-3.1-8b-instant` | External docs, OSS research |
| **Oracle** | `claude-opus-4.5-thinking:max` | Architecture, strategy, deep reasoning |
| **Frontend UI/UX** | `kat-coder-pro:free` | Visual changes, UI/UX improvements |
| **Document Writer** | `qwen3-32b:free` | Writing docs, guides, explanations |
| **Multimodal Looker** | `gemini-3-flash` | Image/PDF analysis, screenshots |

### OpenAgents (Plan-First)

| Agent | Model | Use When |
|--------|--------|----------|
| **openagent** | Your default model | General tasks, questions, workflows |
| **opencoder** | Your default model | Complex coding, architecture, refactoring |
| **task-manager** | Your default model | Task breakdown, planning |
| **coder-agent** | Your default model | Quick implementation |
| **tester** | Your default model | Test creation, validation |
| **reviewer** | Your default model | Code review, security |
| **build-agent** | Your default model | Build, type checking |
| **codebase-pattern-analyst** | Your default model | Pattern discovery |
| **documentation** | Your default model | Documentation authoring |

### Direct Tools

| Tool | Use Case | When to Use |
|-------|-----------|--------------|
| `lsp_goto_definition` | Jump to symbol definition | Navigation, understanding code |
| `lsp_find_references` | Find all usages | Refactoring scope |
| `lsp_rename` | Rename symbol across workspace | Safe refactoring |
| `lsp_code_actions` | Get quick fixes/refactorings | Fix issues, improvements |
| `ast_grep_search` | AST-aware code search | Find patterns, anti-patterns |
| `ast_grep_replace` | AST-aware code replacement | Safe, surgical refactoring |
| `grep` / `glob` | Simple search/file finding | Quick lookups |
| `read` | Read file content | Understanding code |
| `edit` / `write` | Modify files | Implementation |
| `bash` | Run commands | Testing, builds, git |
| `background_task` | Run agents in background | Parallel execution |
| `background_output` | Get background results | Collect parallel work |

---

## Optimization Strategies

### 1. Parallel Execution (Default for Ultrawork)

**Pattern:** Fire multiple `background_task` calls simultaneously

```python
# Wrong (sequential, slow):
result1 = background_task(agent="explore", prompt="Find X")
result2 = background_task(agent="explore", prompt="Find Y")

# Correct (parallel, fast):
task1 = background_task(agent="explore", prompt="Find X")
task2 = background_task(agent="explore", prompt="Find Y")
# Continue working...
result1 = background_output(task_id=task1)
result2 = background_output(task_id=task2)
```

**Benefit:** 3-10x faster exploration, reduced context usage in main session

### 2. Context Window Management

**Challenge:** Large codebases exceed context limits

**Solutions:**
- Use `explore` agents to map structure first
- Delegate to specialists for specific areas
- Use LSP tools for targeted code reading
- Use `look_at` for large files (extracts key info, not full content)

### 3. Token Cost Optimization

**Strategy:** Match model size to task complexity

| Task Complexity | Model Size | Example |
|---------------|--------------|----------|
| Trivial (single file lookup) | 2-4B | `qwen3-4b`, `gemma-3n-e2b` |
| Simple (few files) | 8-32B | `llama-3.1-8b`, `qwen3-32b` |
| Medium (feature implementation) | 32-70B | `qwen3-32b`, `llama-3.3-70b` |
| Complex (architecture design) | Thinking models | `claude-sonnet-4.5-thinking`, `claude-opus-4.5-thinking` |

### 4. Provider Quota Management

**Strategy:** Use Google Antigravity's free tier with multi-account load balancing
 
| Time of Day | Provider | Note |
|--------------|----------|-------|
| Any time | Antigravity | Free tier, high limits |
| Rate limited? | Add more accounts | Run `opencode auth login` |

**Benefits of Antigravity:**
- Free tier with high rate limits
- Multi-account automatic rotation
- Extended thinking support (8k-32k budget)
- Access to Claude and Gemini 3 models |

### 5. Background Task Hygiene

**Always:**
```python
# Cancel all tasks when done to free resources
background_cancel(all=True)
```

---

## Quick Decision Tree

**Task → Recommended Tool/Model**

```
Need to search codebase?
├─ Pattern finding → @explore (gemini-3-flash) + background_task
├─ File location → glob / grep (direct tools)
└─ Symbol navigation → lsp_goto_definition
 
Need external info?
├─ Official docs → @librarian (gemini-3-flash)
├─ OSS examples → @librarian (gemini-3-flash)
└─ Best practices → @librarian (gemini-3-flash)
 
Need deep reasoning?
├─ Architecture design → @oracle (claude-opus-4.5-thinking:max)
├─ Complex debugging → @oracle (claude-opus-4.5-thinking:max)
└─ Security analysis → @oracle (claude-opus-4.5-thinking:max)
 
Need to write code?
├─ Simple implementation → Sisyphus (claude-sonnet-4.5-thinking:low)
├─ Feature development → OpenAgents openagent
├─ Complex refactoring → OpenAgents opencoder
└─ Visual changes → @frontend-ui-ux-engineer (gemini-3-pro)
 
Need documentation?
├─ Docs/guides → @document-writer (gemini-3-pro)
├─ README/API docs → @document-writer (gemini-3-pro)
└─ In-code comments → Sisyphus (claude-sonnet-4.5-thinking:low)
```

---

## Summary: Key Takeaways

1. **Always use parallel `background_task` for exploration** - 3-10x speedup
2. **Match model size to task complexity** - Fast models for exploration, thinking models for reasoning
3. **Use OpenAgents for plan-first workflows** - Approval-based execution, automatic testing
4. **Delegate to specialists** - Oracle for reasoning, Librarian for docs, Explore for codebase
5. **Use Antigravity's free tier** - High limits, multi-account load balancing, thinking models
6. **Use LSP tools for refactoring** - Safer than direct edits for multi-file changes
7. **Cancel background tasks when done** - Free resources

---

## Configuration Files Reference

| File | Purpose | Key Settings |
|-------|-----------|---------------|
| `~/.config/opencode/opencode.json` | Model definitions | All OpenRouter, Groq, Antigravity models |
| `~/.config/opencode/oh-my-opencode.json` | Agent model assignments | Which agent uses which model |
| `~/.opencode/context/project/project-context.md` | Your coding patterns | Agents automatically load this |
| `~/.config/opencode/antigravity.json` | Antigravity plugin config | Multi-account, thinking, rate limits |

---

## Troubleshooting

### Rate Limit Errors

**Symptom:** 429 / rate limit exceeded

**Solutions:**
1. Switch provider (OpenRouter → Groq → Antigravity)
2. Use smaller models (reduce token usage)
3. Fire tasks in background to reduce main session load
4. Add more Antigravity accounts (`opencode auth login`)

### Slow Responses

**Symptom:** Agents taking >10s to respond

**Solutions:**
1. Use smaller models for exploration (qwen3-4b, gemma-3n-e2b)
2. Check network connectivity
3. Reduce context window in prompt
4. Use parallel execution instead of sequential

### Poor Code Quality

**Symptom:** Generated code has bugs or bad patterns

**Solutions:**
1. Update `~/.opencode/context/project/project-context.md` with your patterns
2. Use Oracle for architecture review
3. Use OpenAgents opencoder for complex tasks (better reasoning)
4. Enable automatic testing (built into OpenAgents)

---

## Next Steps

1. **Configure Additional Antigravity Accounts (Optional):**
   ```bash
   opencode auth login  # Add more accounts for higher combined quota
   ```

2. **Test Configuration:**
   ```bash
   opencode run "Hello" --model=google/antigravity-claude-sonnet-4.5-thinking
   ```

3. **Start Analyzing Your CLI:**
   ```bash
   cd /path/to/your/python/cli
   opencode
   > "[analyze-mode] Analyze my Python CLI tool using ultrawork for maximum performance."
   ```

---

**Remember:** The key to efficiency is using the right tool + model for each task. Small/fast models for exploration, thinking models for reasoning, specialists for specific domains.
