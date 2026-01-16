# Backend Feature Reference for Frontend Development

## Project Overview
Reddit AI Curator is an AI-powered Reddit search engine that uses LLMs to intelligently find and score relevant discussions. This document describes the backend features and data flows that need to be surfaced in the frontend.

---

## 1. AI Query Generation Pipeline

### Step 1: Core Characteristics Extraction
When a user provides a natural language description, the system first extracts "mandatory constraints" - non-negotiable elements that must be present in results.

**Backend Process:**
- Input: User's natural language description
- Process: `llm.extract_core_characteristics(criteria)`
- Output: List of constraint objects with themes

**Data to Display:**
```json
{
  "core_constraints": [
    {"theme": "coercion", "description": "..."},
    {"theme": "sexual act", "description": "..."},
    {"theme": "impaired state", "description": "..."}
  ]
}
```

### Step 2: Query Variation Generation
The system generates 5 different Boolean query variations, each using a different search strategy.

**Backend Process:**
- Input: Description + core constraints + optional vocabulary context
- Process: `llm.generate_query_variations(criteria, num_variations=5, ...)`
- Output: 5 query variants

**Data Structure:**
```json
[
  {
    "type": "BROAD",
    "query": "(forced OR coerced OR non-consensual) AND ..."
  },
  {
    "type": "SPECIFIC", 
    "query": "(\"convinced my\" OR \"too scared to\") AND ..."
  },
  {
    "type": "SYNONYM",
    "query": "(\"pressured into\" OR \"didn't want to\") AND ..."
  },
  {
    "type": "NARRATIVE",
    "query": "(\"happened to me\" OR \"first time\") AND ..."
  },
  {
    "type": "JARGON",
    "query": "(\"stealthing\" OR \"NCE\" OR \"non-con\") AND ..."
  }
]
```

### Step 3: Vocabulary Context (Learning System)
If the user has favorited similar posts or there are past high-scoring results, the system extracts common terminology to influence future searches.

**Backend Process:**
- Loads favorites and tagged results databases
- Finds similar posts using keyword matching
- Extracts suggested terms and common tags
- Injects these as "Preferred context" into the criteria

**Data Available:**
- Number of similar results found
- List of suggested terms being used
- Indication that learning is active

---

## 2. Tournament System

### Overview
The system tests all 5 query variations against a sample of real Reddit data to determine which performs best before running the full search.

### Tournament Configuration
- **Sample Size**: 50 posts per variant
- **Test Subreddits**: First 3 from the user's list
- **Scoring Threshold**: ≥75 for tournament evaluation
- **Concurrent Testing**: All variants tested in parallel

### Scoring Formula
Each variant receives a weighted score:
```
tournament_score = (high_quality_matches × 10) + (average_score × 0.5)
```

Where:
- `high_quality_matches` = posts scoring ≥75
- `average_score` = mean score across all analyzed posts

### Tournament Results
**Data Structure:**
```json
{
  "variant_name": {
    "query": "the actual query string",
    "type": "BROAD",
    "avg_score": 95.0,
    "high_quality": 9,
    "v_score": 137.5
  }
}
```

**Winner Selection:**
- Returns top 3 queries ranked by `v_score`
- First query is the "winner" used for primary search
- Queries 2 and 3 are used in cascade fallback if needed

---

## 3. Search Configuration Options

### Basic Parameters
- **keywords**: Direct Boolean query (optional if using description)
- **description**: Natural language input for AI generation
- **criteria**: Detailed scoring criteria for LLM analysis
- **subreddits**: Array of subreddit names
- **target_posts**: Number of high-quality posts desired (default: 10)
- **provider**: "mistral" or "gemini"

### Search Behavior
- **sort**: "new" | "relevance" | "top" | "hot" | "comments"
- **time**: "all" | "day" | "week" | "month" | "year" | "hour"
- **post_type**: "any" | "text" | "media"
- **limit**: Posts to fetch per subreddit (1-500, default: 100)
- **ai_chunk**: Batch size for LLM analysis (default: 5)

### Advanced Options
- **tournament**: Enable/disable query tournament (boolean)
- **exhaustive**: Try all sort methods and variants for maximum recall (boolean)
- **no_fallback**: Disable automatic cascade retries (boolean)

---

## 4. Tiered Search Cascade

When enabled (default), the system automatically retries searches with different configurations if the target quota isn't met.

### Cascade Levels

**Tier 1: Sort Variation**
- Retries the winning query with different sort methods
- Sequence: Initial sort → relevance → top → hot → comments
- Each pass accumulates results (no duplication)

**Tier 2: Variant Queries**
- Uses the 2nd and 3rd best tournament queries
- Tries up to 2 sort methods per variant
- Skipped if exhaustive mode is disabled

**Tier 3: Parameter Expansion**
- Increases fetch limit to 500 posts per subreddit
- Expands time filter to "all"
- Uses "top" sort

**Tier 4: Adaptive Scoring**
- Lowers the quality threshold from 80 to 70, then 60
- Only affects what counts toward the quota
- All posts still returned with original scores

### Quota Check Logic
```python
def quota_met():
    if exhaustive_mode:
        return False  # Never stop early
    return len([p for p in results if p['score'] >= current_threshold]) >= target_posts
```

---

## 5. Search Pass Information

Each search pass (whether initial or cascade tier) provides:

### Configuration Details
- Query string being used
- Sort method
- Time filter
- Fetch limit per subreddit

### Live Statistics
- **Posts fetched**: Total posts retrieved from Reddit API
- **Posts analyzed**: Posts sent to LLM for scoring
- **Score distribution**:
  - High: Score ≥80
  - Medium: Score 60-79
  - Low: Score <60
- **Per-subreddit breakdown**: Fetched and approved counts per subreddit

---

## 6. Post Scoring System

### Scoring Components

**Base LLM Score (0-100)**
- Returned by the LLM based on criteria match

**Content Quality Bonuses**
- +7 if content length > 800 characters
- +5 if upvotes > 200
- +3 if comments > 20

**Subreddit Bias Multiplier**
- Configurable per-subreddit (default: 1.0)
- Applied to base score before bonuses

**Final Score Formula:**
```python
final_score = min(100, (llm_score × subreddit_bias) + bonuses)
```

---

## 7. Post Data Structure

Each result contains:

```json
{
  "id": "abc123",
  "title": "Post title",
  "content": "Full post text",
  "url": "https://www.reddit.com/r/...",
  "sub": "subreddit_name",
  "score": 95.5,
  "timestamp": 1234567890,
  "upvotes": 250,
  "num_comments": 45,
  "tags": ["tag1", "tag2", "tag3"]
}
```

### Tags
- Automatically extracted for posts scoring ≥80
- Semantic labels (not generic categories)
- Examples: "party", "passed out", "sibling", "pretending to sleep"
- Maximum 8 tags displayed
- Stored in learning database for future query enhancement

---

## 8. Learning System Features

### Favorites
**Purpose**: User-saved posts that personalize future searches

**Storage**: `config/favorites.json`

**Usage**:
- When searching with similar criteria, the system:
  1. Finds favorited posts with matching keywords
  2. Extracts common tags and terms
  3. Injects them into the search criteria as "Preferred context"
  4. This influences LLM scoring to prioritize similar content

**Data Structure**: Same as post data structure

### Blacklist
**Purpose**: Prevent seeing the same high-quality posts repeatedly

**Auto-blacklist**: Posts scoring ≥85 are automatically added

**Filtering**: Blacklisted post IDs are loaded at search start and excluded from results

**Storage**: `config/blacklist.json`

**Data Structure**:
```json
{
  "post_id": {
    "id": "post_id",
    "title": "...",
    "url": "...",
    "keywords": "query used",
    "criteria": "criteria used",
    "timestamp": 1234567890
  }
}
```

### Tagged Results Database
**Purpose**: Historical record of successful searches for learning

**Storage**: `config/tagged_results.json`

**Auto-population**: High-scoring posts (≥80) get tags extracted and stored

**Data Structure**:
```json
{
  "post_id": {
    "title": "...",
    "content": "first 2000 chars",
    "score": 95,
    "original_query": "query that found it",
    "tags": ["tag1", "tag2"],
    "effective_terms": ["phrase1", "phrase2"],
    "timestamp": 1234567890
  }
}
```

---

## 9. API Endpoints

### Search & Analysis
- **POST /api/search**: Execute search (returns JSON or initiates SSE stream)
- **GET /stream**: Server-Sent Events endpoint for real-time search updates
- **POST /api/generate_query**: Convert description to Boolean query
- **POST /api/analyze**: Score posts against criteria

### Configuration Management
- **GET /api/subreddits**: Retrieve subreddit list
- **POST /api/subreddits**: Update subreddit list (expects JSON array)
- **GET /api/queries**: Fetch saved queries
- **POST /api/queries**: Save a query
- **DELETE /api/queries/:id**: Remove a saved query

### Learning System
- **GET /api/favorites**: Get all favorited posts
- **POST /api/favorites**: Add a post to favorites (expects post object)
- **DELETE /api/favorites/:id**: Remove from favorites
- **GET /api/blacklist**: Get blacklist
- **POST /api/blacklist/clear**: Clear entire blacklist

---

## 10. Real-Time Search Updates (SSE)

The `/stream` endpoint provides Server-Sent Events with status messages:

### Message Types

**Status Updates** (plain text):
```
🚀 Concurrent Pipeline Activated
🔎 Initial Query: (example query)
🎯 Target: 10 posts
```

**Structured Post Data** (prefixed):
```
<<<POST_SCORED>>>{"id": "...", "score": 95, "title": "..."}
```

**Completion Signal**:
```
<<<DONE>>>
```

### Update Flow
1. Pipeline initialization
2. Core characteristics extraction
3. Learning context (if applicable)
4. Tournament progress (per variant)
5. Tournament winner announcement
6. Search pass configuration
7. Individual post scores as analyzed
8. Pass completion stats
9. Cascade tier activation (if quota not met)
10. Final statistics
11. Tag extraction progress
12. Blacklist updates
13. Done signal

---

## 11. Keyword Highlighting

Posts can have matched keywords highlighted in both title and content.

**Backend Process**:
- Extract terms from the Boolean query
- Filter out operators (AND, OR, NOT)
- Apply case-insensitive regex matching
- Wrap matches in `<mark>` tags

**HTML Output**:
```html
This is a <mark>highlighted</mark> keyword in the text.
```

---

## 12. Subreddit Discovery

Additional feature to find relevant subreddits based on keywords.

**Endpoint**: `POST /api/discover`

**Parameters**:
- keywords: Search terms
- criteria: Optional filtering criteria
- limit_subs: Maximum subreddits to return (default: 10)

**Returns**:
```json
[
  {
    "name": "subreddit_name",
    "description": "Subreddit description",
    "hits": 15,
    "relevance": 0.85
  }
]
```

---

## 13. Export Functionality

Results can be exported to:
- **JSON**: Complete data structure with all metadata
- **HTML**: Standalone report with styling and JavaScript

HTML reports include:
- All post data
- Keyword highlighting
- Collapsible content
- Tag display
- Timestamp formatting
- Clickable links

---

## Summary of Data Flows

1. **User Input** → Query Generation → Core Characteristics + 5 Variants
2. **5 Variants** → Tournament Testing → Top 3 Queries
3. **Winner Query** → Search Pass → Posts Fetched → LLM Scoring → Results
4. **Results** → Check Quota → If not met → Cascade to next tier
5. **Final Results** → Tag Extraction → Save to Learning DB
6. **High Scorers (≥85)** → Auto-add to Blacklist
7. **User Favorites** → Save to Favorites → Influence Future Searches

---

This document provides all functional requirements for the frontend without prescribing design approaches. The frontend can implement these features using any UI framework, design system, or visual approach.
