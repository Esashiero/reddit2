#!/usr/bin/env python3
import sys
import os
import json
import argparse
import time
from typing import List, Dict
from dotenv import load_dotenv, find_dotenv
from mistralai import Mistral
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import RedditSearchEngine

load_dotenv(find_dotenv(), override=True)


class SemanticBenchmark:
    def __init__(self, provider="mistral"):
        self.provider = provider
        self.engine = RedditSearchEngine(provider=provider, debug=False)
        self.mistral_key = os.getenv("MISTRAL_API_KEY")
        self.google_key = os.getenv("GOOGLE_API_KEY")

        if provider == "mistral" and self.mistral_key:
            self.client = Mistral(api_key=self.mistral_key)
        elif provider == "gemini" and not self.google_key:
            raise ValueError("Google API Key missing")

    def evaluate_relevance(self, user_request: str, post_content: str) -> int:
        sys_prompt = (
            "You are a relevance judge. "
            "Rate the relevance of the Reddit post to the User Request on a scale of 0-10. "
            "0 = Completely irrelevant/spam. "
            "10 = Perfect match, exactly what user asked for. "
            "Return ONLY the number."
        )
        user_prompt = (
            f"User Request: {user_request}\n\nReddit Post:\n{post_content[:2000]}"
        )

        try:
            if self.provider == "mistral":
                res = self.client.chat.complete(
                    model="mistral-large-latest",
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                if not res or not res.choices or not res.choices[0].message.content:
                    return 0
                content = str(res.choices[0].message.content).strip()
                return int("".join(filter(str.isdigit, content)))
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.google_key}"
                payload = {
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "system_instruction": {"parts": [{"text": sys_prompt}]},
                }
                res = requests.post(
                    url, json=payload, headers={"Content-Type": "application/json"}
                )
                txt = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                return int("".join(filter(str.isdigit, txt)))
        except Exception as e:
            print(f"Evaluation error: {e}", file=sys.stderr)
            return 0

    def run_benchmark(
        self,
        description: str,
        subreddits: List[str],
        limit: int = 5,
        manual_query: str = "",
    ):
        print(f"Benchmarking: {description}")

        if manual_query:
            print(f"Using Manual Query: {manual_query}")
            query = manual_query
        else:
            llm_filter = self.engine.llm
            query = llm_filter.generate_boolean_string(description)
            print(f"Generated Query: {query}")

            if query.startswith("Error:"):
                print(f"❌ Aborting benchmark due to Query Generation Error: {query}")
                print(
                    '💡 Tip: Use --manual-query "(your OR terms)" to bypass this step.'
                )
                return {
                    "description": description,
                    "query": query,
                    "found_count": 0,
                    "average_score": 0,
                    "details": [],
                    "error": True,
                }

        print("Fetching posts from Reddit...")

        results = []
        gen = self.engine.search(
            keywords=query,
            criteria="",
            subreddits=subreddits,
            target_posts=limit,
            manual_limit=limit * 2,
        )

        while True:
            try:
                msg = next(gen)
                print(f"  {msg}")
            except StopIteration as e:
                results = e.value
                break
            except Exception as e:
                print(f"Search failed: {e}")
                return

        print(f"Found {len(results)} posts.")

        total_score = 0
        details = []

        for post in results:
            score = self.evaluate_relevance(
                description, f"{post.title}\n{post.selftext}"
            )
            details.append({"title": post.title, "score": score, "url": post.permalink})
            total_score += score
            print(f"  [{score}/10] {post.title[:50]}...")

        avg_score = (total_score / len(results)) * 10 if results else 0
        print(f"Average Relevance: {avg_score:.1f}/100")
        return {
            "description": description,
            "query": query,
            "found_count": len(results),
            "average_score": avg_score,
            "details": details,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--description", type=str, required=True)
    parser.add_argument("--subreddits", type=str, default="all")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--provider", type=str, default="mistral")
    parser.add_argument(
        "--manual-query", type=str, help="Skip LLM generation and use this query"
    )
    args = parser.parse_args()

    bench = SemanticBenchmark(provider=args.provider)
    subs = args.subreddits.split(",")

    bench.run_benchmark(
        args.description, subs, args.limit, manual_query=args.manual_query
    )


if __name__ == "__main__":
    main()
