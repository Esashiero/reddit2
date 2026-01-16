#!/usr/bin/env python3

import json
import argparse
import sys
import os
import time
from typing import Optional, Dict, Any, List
from app import RedditSearchEngine, LLMFilter

SEARCH_LOG_FILE = "search_log.json"


def log_search_event(event_type: str, data: Dict[str, Any]):
    log_entry = {"timestamp": time.time(), "event_type": event_type, "data": data}

    log_data: List[Dict[str, Any]] = []
    if os.path.exists(SEARCH_LOG_FILE):
        try:
            with open(SEARCH_LOG_FILE, "r") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    log_data = loaded_data
                else:
                    log_data = []
        except json.JSONDecodeError:
            log_data = []
        except Exception:
            log_data = []

    log_data.append(log_entry)

    with open(SEARCH_LOG_FILE, "w") as f:
        json.dump(log_data, f, indent=2)


def generate_query(description: str, provider: str = "mistral"):
    llm_filter = LLMFilter(provider=provider)
    query_string = llm_filter.generate_boolean_string(description)

    log_search_event(
        "generate_query",
        {
            "description": description,
            "provider": provider,
            "query_string": query_string,
        },
    )

    return query_string


def execute_search(
    query: str,
    limit: int = 20,
    subreddits: str = "all",
    sort: str = "new",
    time: str = "all",
    debug: bool = False,
    log_file: Optional[str] = None,
):
    original_stderr = sys.stderr
    if log_file:
        sys.stderr = open(log_file, "w")

    try:
        engine = RedditSearchEngine(debug=debug)
        subs_list = [s.strip() for s in subreddits.split(",")]

        search_generator = engine.search(
            keywords=query,
            criteria="",
            subreddits=subs_list,
            target_posts=limit,
            manual_limit=limit,
            sort_by=sort,
            time_filter=time,
        )

        raw_praw_posts = []
        converted_posts: List[Dict[str, Any]] = []

        try:
            while True:
                item = next(search_generator)
                if isinstance(item, str):
                    print(item, file=sys.stderr)
        except StopIteration as e:
            raw_praw_posts = e.value

        for p in raw_praw_posts:
            if hasattr(p, "id"):
                converted_posts.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "sub": p.subreddit.display_name,
                        "url": f"https://www.reddit.com{p.permalink}",
                        "content": json.dumps(p.selftext[:1000])[1:-1],
                        "timestamp": p.created_utc,
                        "score": p.score,
                    }
                )

        log_search_event(
            "execute_search",
            {
                "query": query,
                "limit": limit,
                "subreddits": subreddits,
                "sort": sort,
                "time": time,
                "debug": debug,
                "results_count": len(converted_posts),
                "results": converted_posts,
            },
        )
        return json.dumps(converted_posts, indent=2)
    finally:
        if log_file:
            sys.stderr.close()
            sys.stderr = original_stderr


def score_results(
    posts_file_path: str,
    user_intent: str,
    provider: str = "mistral",
    top_n: Optional[int] = None,
):
    with open(posts_file_path, "r") as f:
        posts = json.load(f)
    llm_filter = LLMFilter(provider=provider)
    scored = llm_filter.analyze(posts, user_intent)

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    if top_n is not None:
        scored = scored[:top_n]

    log_search_event(
        "score_results",
        {
            "posts_file_path": posts_file_path,
            "user_intent": user_intent,
            "provider": provider,
            "top_n": top_n,
            "scored_results": scored,
        },
    )

    return json.dumps(scored, indent=2)


def generate_report(output_file: str):
    if not os.path.exists(SEARCH_LOG_FILE):
        return "No search log found."

    with open(SEARCH_LOG_FILE, "r") as f:
        log_data = json.load(f)

    report = ["# Reddit Curation Search Report\n"]

    original_intent = "Unknown"
    for event in log_data:
        if event["event_type"] == "generate_query":
            original_intent = event["data"].get("description", "Unknown")
            break

    report.append(f"## Original Intent\n{original_intent}\n")

    report.append("## Search Process\n")
    for i, event in enumerate(log_data):
        etype = event["event_type"]
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(event["timestamp"]))

        if etype == "generate_query":
            report.append(f"### Round {i+1}: Query Generation ({ts})")
            report.append(f"- **Query**: `{event['data'].get('query_string')}`")
        elif etype == "execute_search":
            report.append(f"### Round {i+1}: Search Execution ({ts})")
            report.append(f"- **Subreddits**: {event['data'].get('subreddits')}")
            report.append(f"- **Results Found**: {event['data'].get('results_count')}")

    report.append("\n## Top Relevant Posts\n")

    all_scored = []
    for event in log_data:
        if event["event_type"] == "score_results":
            all_scored.extend(event["data"].get("scored_results", []))

    unique_posts = {}
    for p in all_scored:
        pid = p.get("id")
        if pid not in unique_posts or p.get("score", 0) > unique_posts[pid].get("score", 0):
            unique_posts[pid] = p

    sorted_posts = sorted(unique_posts.values(), key=lambda x: x.get("score", 0), reverse=True)

    post_details = {}
    for event in log_data:
        if event["event_type"] == "execute_search":
            for p in event["data"].get("results", []):
                post_details[p["id"]] = p

    for i, p in enumerate(sorted_posts[:15]):
        details = post_details.get(p["id"], {})
        report.append(
            f"### {i+1}. {details.get('title', 'No Title')} (Score: {p.get('score')})"
        )
        report.append(f"- **Subreddit**: r/{details.get('sub')}")
        report.append(f"- **URL**: {details.get('url')}")
        report.append(f"- **Content Excerpt**: {details.get('content', '')[:500]}...")
        report.append("\n---\n")

    with open(output_file, "w") as f:
        f.write("\n".join(report))

    return f"Report generated: {output_file}"


class Decomposer:
    """Agent 1: Socratic Intent Decomposition"""

    def decompose(self, user_intent: str) -> List[str]:
        """Break down user intent into atomic sub-questions"""
        llm = LLMFilter(provider="mistral")
        prompt = f"""
You are a Socratic Intent Decomposer. Your task is to break down the following user intent into 2-4 atomic sub-questions that will help other agents search more effectively.

User Intent: "{user_intent}"

Please decompose this intent by identifying:
1. Core Event: What is the primary event being described?
2. Required Elements: What specific details MUST be present in matching posts?
3. Nice-to-Have: What additional elements would improve search results?
4. Linguistic Patterns: What language/phrases would someone discussing this topic use?

For each sub-question, provide:
- A brief explanation of what you're identifying
- The specific search aspects (keywords, phrases) that relate to this sub-question

Format your output as a JSON array of objects, where each object has:
{{"aspect": "...", "search_terms": ["...", "..."]}}

Return ONLY a JSON array, no other text.
"""
        response = llm.complete(prompt, response_format="json")
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return []

    def run(self, user_intent: str):
        """Execute decomposer and return breakdown"""
        aspects = self.decompose(user_intent)

        log_search_event("decomposer", {
            "user_intent": user_intent,
            "aspects": aspects
        })

        return json.dumps(aspects, indent=2)


class QueryGenerator:
    """Agent 2: Complex Lucene Query Synthesis"""

    def generate_queries(self, aspects: List[Dict]) -> List[str]:
        """Generate optimized Lucene queries from decomposed aspects"""
        llm = LLMFilter(provider="mistral")

        prompt = f"""
You are a Lucene Query Generator. Your task is to generate optimized Reddit Boolean search queries based on the following search aspects.

Search Aspects:
{json.dumps(aspects, indent=2)}

For each aspect, create a separate Lucene query. Each query should:
- Use OR operators for synonyms/related terms within each aspect
- Use AND operators to combine aspects together
- Use proximity operators (e.g., ~5) for phrases when appropriate
- Use quote marks for multi-word terms
- Use self:true to filter for text posts only

Important Rules:
- Each query should be independently executable
- Combine different aspects systematically to ensure comprehensive coverage
- Avoid overly complex nested structures that might cause search timeouts

Return ONLY a valid JSON array of query strings. Format:
{{"query": "...", "target": "...", "reasoning": "..."}}
"""
        response = llm.complete(prompt, response_format="json")
        try:
            queries = json.loads(response)
            return [q["query"] for q in queries]
        except json.JSONDecodeError:
            return []

    def run(self, user_intent: str, aspects: List[Dict]) -> List[str]:
        """Execute query generator and return optimized queries"""
        queries = self.generate_queries(aspects)

        log_search_event("query_generator", {
            "user_intent": user_intent,
            "aspects": aspects,
            "queries": queries
        })

        return json.dumps(queries, indent=2)


class RelevanceJudge:
    """Agent 3: Evaluate Search Results"""

    def evaluate_batch(self, posts: List[Dict], user_intent: str) -> List[Dict]:
        """Score a batch of posts against user intent"""
        llm = LLMFilter(provider="mistral")

        post_list_str = json.dumps(posts)
        prompt = f"""
You are a Relevance Judge. Evaluate the following Reddit posts against the user's original intent.

Original User Intent: "{user_intent}"

Posts to Evaluate:
{post_list_str}

For each post, provide:
1. A relevance score from 0-100 (0 = completely irrelevant, 100 = perfect match)
2. A brief justification for the score (1-2 sentences)

Format your output as a JSON array of objects with the same order as input:
{{"id": "...", "score": 85, "justification": "..."}}
"""
        response = llm.complete(prompt, response_format="json")
        try:
            scored = json.loads(response)
            return scored
        except json.JSONDecodeError:
            return []

    def run(self, posts: List[Dict], user_intent: str) -> List[Dict]:
        """Execute relevance judge and return scored posts"""
        scored = self.evaluate_batch(posts, user_intent)

        log_search_event("relevance_judge", {
            "user_intent": user_intent,
            "post_count": len(posts),
            "scored_results": scored
        })

        return json.dumps(scored, indent=2)


class ReflectiveFeedback:
    """Agent 4: Analyze and Suggest Improvements"""

    def analyze_quality(self, scored_posts: List[Dict], user_intent: str) -> str:
        """Analyze search result quality and provide feedback"""
        llm = LLMFilter(provider="mistral")

        high_score_count = sum(1 for p in scored_posts if p.get("score", 0) >= 70)
        total_count = len(scored_posts)

        prompt = f"""
You are a Reflective Feedback Agent. Analyze the following search results and provide improvement suggestions.

Original User Intent: "{user_intent}"

Scored Posts Summary:
- Total posts scored: {total_count}
- High-scoring posts (>= 70): {high_score_count}
- Top score: {max((p.get("score", 0) for p in scored_posts), default=0)}

Provide analysis:
1. Assessment: Are the current results sufficient? If not, why?
2. Gaps: What types of relevant posts might be missing from the current search strategy?
3. Suggestions: Specific improvements to search queries or subreddits that could yield better results.

Return your response as a plain text analysis (no JSON, no markdown).
"""
        response = llm.complete(prompt)
        return response

    def run(self, scored_posts: List[Dict], user_intent: str):
        """Execute reflective analysis and return feedback"""
        feedback = self.analyze_quality(scored_posts, user_intent)

        log_search_event("reflective_feedback", {
            "user_intent": user_intent,
            "feedback": feedback
        })

        return feedback


class MultiAgentOrchestrator:
    """Agent 5: Coordinates Multi-Agent Workflow with Human Confirmation"""

    def __init__(self):
        self.decomposer = Decomposer()
        self.query_generator = QueryGenerator()
        self.judge = RelevanceJudge()
        self.reflector = ReflectiveFeedback()

    def present_search_plan(self, user_intent: str) -> str:
        """Generate and present search plan for human confirmation"""

        # Step 1: Decompose intent
        aspects = json.loads(self.decomposer.run(user_intent))

        # Step 2: Generate queries
        queries = json.loads(self.query_generator.run(user_intent, aspects))

        # Format for human review
        plan = f"""## Search Plan for: {user_intent}

I've analyzed your request and broken it down into {len(aspects)} search aspects. Here's my plan:

### Search Aspects Identified:
"""
        for i, aspect in enumerate(aspects):
            plan += f"\n**{i + 1}. {aspect['aspect']}**\n"
            plan += f"   Search Terms: {', '.join(aspect['search_terms'])}\n\n"

        plan += f"""
### Proposed Search Queries:
I've generated {len(queries)} search queries to comprehensively cover all aspects:

"""
        for i, query in enumerate(queries):
            plan += f"\n**Query {i + 1}**: `{query}`"

        plan += f"""
### Execution Strategy:
1. I will execute each query across relevant subreddits
2. Results will be scored for relevance
3. Top-scoring posts will be aggregated
4. If initial results are insufficient, I will refine queries and re-search

---
**Ready to proceed?**
- Reply "yes" to execute this search plan
- Reply "modify" to see different queries or add specific requirements
- Reply "cancel" to stop

Which would you like?
"""
        return plan

    def execute_searches(
        self,
        user_intent: str,
        queries: List[str],
        subreddits: str = "all",
        limit_per_query: int = 20
    ) -> List[Dict]:
        """Execute all queries and collect all results"""
        engine = RedditSearchEngine(debug=False)

        all_posts = {}
        post_ids = set()

        for query in queries:
            try:
                subs_list = [s.strip() for s in subreddits.split(",")]
                search_generator = engine.search(
                    keywords=query,
                    criteria="",
                    subreddits=subs_list,
                    target_posts=limit_per_query,
                    manual_limit=limit_per_query,
                    sort_by="new",
                    time_filter="all",
                )

                raw_praw_posts = []
                try:
                    while True:
                        item = next(search_generator)
                        if isinstance(item, str):
                            pass
                except StopIteration as e:
                    raw_praw_posts = e.value or []

                for p in raw_praw_posts:
                    if hasattr(p, "id") and p.id not in post_ids:
                        all_posts[p.id] = {
                            "id": p.id,
                            "title": p.title,
                            "sub": p.subreddit.display_name,
                            "url": f"https://www.reddit.com{p.permalink}",
                            "content": json.dumps(p.selftext[:1000])[1:-1],
                            "timestamp": p.created_utc,
                            "score": p.score,
                        }
                        post_ids.add(p.id)

                log_search_event("multi_search_execution", {
                    "query": query,
                    "results_count": len([p for p in raw_praw_posts if hasattr(p, "id")]),
                })

            except Exception as e:
                log_search_event("search_error", {
                    "query": query,
                    "error": str(e)
                })

        return list(all_posts.values())

    def execute_with_confirmation(
        self,
        user_intent: str,
        subreddits: str = "all",
        limit: int = 20
    ) -> List[Dict]:
        """Execute multi-agent workflow with human confirmation"""

        # Step 1: Present plan
        plan = self.present_search_plan(user_intent)
        print(plan)

        # Step 2: Wait for user response
        print("\n[Waiting for your response (yes/modify/cancel)...]")

        try:
            user_response = input().strip().lower()

            if user_response == "cancel":
                print("\nSearch cancelled by user.")
                return []

            elif user_response == "modify":
                print("\nPlease describe what you'd like to modify:")
                modification = input()
                print(f"\nModification noted: {modification}")

                # Regenerate plan
                return self.execute_with_confirmation(user_intent, subreddits, limit)

            elif user_response == "yes":
                # Step 3: Decompose and generate queries
                aspects = json.loads(self.decomposer.run(user_intent))
                queries = json.loads(self.query_generator.run(user_intent, aspects))

                # Step 4: Execute searches
                all_posts = self.execute_searches(
                    user_intent, queries, subreddits, limit
                )

                # Step 5: Score results
                scored_posts = self.judge.run(all_posts, user_intent)

                # Step 6: Generate feedback
                feedback = self.reflector.run(scored_posts, user_intent)

                print(f"\n{feedback}")

                # Return top results (already sorted by judge)
                return scored_posts

            else:
                print("\nInvalid response. Please reply with 'yes', 'modify', or 'cancel'.")
                return []

        except KeyboardInterrupt:
            print("\nSearch interrupted by user.")
            return []
        except Exception as e:
            print(f"\nError during execution: {e}")
            return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic tools for Reddit Curation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gen_parser = subparsers.add_parser(
        "generate_query", help="Generate a search query."
    )
    gen_parser.add_argument(
        "--description", required=True, help="Natural language description."
    )
    gen_parser.add_argument("--provider", default="mistral", help="LLM provider.")

    search_parser = subparsers.add_parser(
        "execute_search", help="Execute a Reddit search."
    )
    search_parser.add_argument("--query", required=True, help="Boolean search query.")
    )
    search_parser.add_argument(
        "--limit", type=int, default=20, help="Number of posts to fetch."
    )
    search_parser.add_argument(
        "--subreddits", default="all", help="Comma-separated subreddits."
    )
    search_parser.add_argument(
        "--sort", default="new", help="Sort order (new, top, relevance)."
    )
    search_parser.add_argument(
        "--time", default="all", help="Time filter (all, year, month, day)."
    )
    search_parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging."
    )
    search_parser.add_argument(
        "--log-file", type=str, help="File to write debug logs to."
    )

    score_parser = subparsers.add_parser("score_results", help="Score search results.")
    score_parser.add_argument(
        "--posts_file_path",
        required=True,
        help="Path to a JSON file containing posts to score.",
    )
    score_parser.add_argument(
        "--user_intent", required=True, help="Original user intent."
    )
    score_parser.add_argument(
        "--provider", default="mistral", help="LLM provider."
    )
    score_parser.add_argument("--top_n", type=int, help="Number of top results to return."
    )

    report_parser = subparsers.add_parser(
        "generate_report", help="Generate a search report."
    )
    report_parser.add_argument(
        "--output_file", default="search_report.md", help="Output markdown file."
    )

    # Sub-parser for multi-agent search
    multi_parser = subparsers.add_parser(
        "multi_search", help="Execute multi-agent search workflow."
    )
    multi_parser.add_argument(
        "--intent", required=True, help="Natural language search intent."
    )
    multi_parser.add_argument(
        "--subreddits", default="multi", help="Comma-separated subreddits."
    )
    multi_parser.add_argument(
        "--limit", type=int, default=20, help="Posts per query."
    )
    multi_parser.add_argument(
        "--provider", default="mistral", help="LLM provider."
    )

    args = parser.parse_args()

    if args.command == "generate_query":
        result = generate_query(args.description, args.provider)
        print(result)
    elif args.command == "execute_search":
        result = execute_search(
            args.query,
            args.limit,
            args.subreddits,
            args.sort,
            args.time,
            args.debug,
            args.log_file,
        )
        print(result)
    elif args.command == "score_results":
        result = score_results(
            args.posts_file_path, args.user_intent, args.provider, args.top_n
        )
        print(result)
    elif args.command == "generate_report":
        result = generate_report(args.output_file)
        print(result)
    elif args.command == "multi_search":
        orchestrator = MultiAgentOrchestrator()
        result = orchestrator.execute_with_confirmation(
            args.intent, args.subreddits, args.limit, args.provider
        )
        print(json.dumps(result, indent=2))
