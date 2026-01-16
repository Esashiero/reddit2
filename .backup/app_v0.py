from flask import Flask, Response, request, render_template, jsonify
import os
import praw
import json
import time
import requests
import math
import re
import argparse
import sys
from typing import List, Dict, Optional, Generator
from dotenv import load_dotenv, find_dotenv
from mistralai import Mistral

load_dotenv(find_dotenv(), override=True)

# --- FILE STORAGE ---
SAVED_QUERIES_FILE = "saved_queries.json"
SUBREDDITS_FILE = "subreddits.json"
BLACKLIST_FILE = "blacklist.json"

# --- CONFIG ---
DEFAULT_SUBS_ENV = os.getenv(
    "REDDIT_SUBREDDITS", "ArtificialInteligence,LocalLLaMA,Python"
)
REDDIT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_AGENT = os.getenv("REDDIT_USER_AGENT", "script:flask_app:v12_fixed")
MISTRAL_KEY = os.getenv("MISTRAL_API_KEY", "")
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY", "")


class LLMFilter:
    def __init__(self, provider: str):
        self.provider = provider
        if provider == "mistral":
            if not MISTRAL_KEY:
                raise Exception("Mistral Key Missing")
            self.client = Mistral(api_key=MISTRAL_KEY)
        elif provider == "gemini":
            if not GOOGLE_KEY:
                raise Exception("Google Key Missing")
            self.api_key = GOOGLE_KEY

    def analyze(self, posts: List[Dict], criteria: str) -> List[Dict]:
        sys_p = (
            "Analyze the following Reddit posts based on the criteria. "
            "Return a JSON object with a 'results' key containing a list of objects. "
            "Each object must have 'id' and 'score' (0-100, where 100 is perfect match). "
            'Example: {"results": [{"id": "abc", "score": 85}]}'
        )
        usr_p = f"CRITERIA: {criteria}\nPOSTS:\n{json.dumps(posts)}"
        try:
            if self.provider == "mistral":
                res = self.client.chat.complete(
                    model="mistral-small-latest",
                    messages=[
                        {"role": "system", "content": sys_p},
                        {"role": "user", "content": usr_p},
                    ],
                    response_format={"type": "json_object"},
                )
                return json.loads(str(res.choices[0].message.content)).get(
                    "results", []
                )
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
                pl = {
                    "contents": [{"parts": [{"text": usr_p}]}],
                    "system_instruction": {"parts": [{"text": sys_p}]},
                    "generationConfig": {"response_mime_type": "application/json"},
                }
                res = requests.post(
                    url, json=pl, headers={"Content-Type": "application/json"}
                )
                txt = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(txt).get("results", [])
        except Exception as e:
            print(f"LLM Error: {e}", file=sys.stderr)
            return []

    def expand_query(self, original_keywords: str, criteria: str) -> str:
        sys_p = (
            "You are an expert Reddit Search Engineer. The user's search returned 0 results. "
            "Suggest a broader but still relevant Boolean Search String. "
            "Format: (term1 OR term2) AND (termA OR termB). "
            "Return ONLY the raw string."
        )
        usr_p = f"Original Keywords: {original_keywords}\nCriteria: {criteria}"
        try:
            if self.provider == "mistral":
                res = self.client.chat.complete(
                    model="mistral-medium-latest",
                    messages=[
                        {"role": "system", "content": sys_p},
                        {"role": "user", "content": usr_p},
                    ],
                )
                content = res.choices[0].message.content
                return str(content).strip() if content else original_keywords
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.api_key}"
                pl = {
                    "contents": [{"parts": [{"text": usr_p}]}],
                    "system_instruction": {"parts": [{"text": sys_p}]},
                }
                res = requests.post(
                    url, json=pl, headers={"Content-Type": "application/json"}
                )
                return res.json()["candidates"][0]["content"]["parts"][0][
                    "text"
                ].strip()
        except:
            return original_keywords

    def generate_boolean_string(self, description: str) -> str:
        sys_p = (
            "You are an expert Reddit Search Engineer. Your task is to generate a high-precision Boolean Search String "
            "based on the user's description. The query must be optimized for Reddit's search engine.\n\n"
            "**Rules:**\n"
            "1. **Structure:** Identify the core concepts (2-4 distinct groups) and connect them with AND. Connect synonyms within groups with OR.\n"
            '2. **Keywords:** Use precise single words or short phrases in quotes (e.g., "machine learning"). Avoid stopwords (a, the, in, with).\n'
            "3. **Complexity:** 3-6 terms per group. Focus on high-signal keywords.\n"
            '4. **Format:** Return ONLY the raw string: (term1 OR term2) AND (term3 OR "term 4").\n'
            "5. **Constraints:** No markdown, no explanations. Do not nest parentheses."
        )

        try:
            if self.provider == "mistral":
                res = self.client.chat.complete(
                    model="mistral-medium-latest",
                    messages=[
                        {"role": "system", "content": sys_p},
                        {"role": "user", "content": description},
                    ],
                )
                content = res.choices[0].message.content
                query_string = str(content).strip() if content else ""
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.api_key}"
                pl = {
                    "contents": [{"parts": [{"text": description}]}],
                    "system_instruction": {"parts": [{"text": sys_p}]},
                }
                res = requests.post(
                    url, json=pl, headers={"Content-Type": "application/json"}
                )
                query_string = res.json()["candidates"][0]["content"]["parts"][0][
                    "text"
                ].strip()

            # Cleanup
            query_string = query_string.replace("```", "").strip()
            if query_string.startswith('"') and query_string.endswith('"'):
                query_string = query_string[1:-1]
            return query_string

        except Exception as e:
            return f"Error: {e}"


class RedditSearchEngine:
    def __init__(self, provider: str = "mistral", debug: bool = False):
        self.provider = provider
        self.debug = debug
        self.reddit = praw.Reddit(
            client_id=REDDIT_ID, client_secret=REDDIT_SECRET, user_agent=REDDIT_AGENT
        )
        self.llm = LLMFilter(provider)

    def _log(self, msg: str):
        if self.debug:
            print(f"DEBUG: {msg}", file=sys.stderr)

    @staticmethod
    def parse_keywords(keywords: str) -> List[List[str]]:
        parsed_groups = []
        paren_groups = re.findall(r"\(([^)]+)\)", keywords)
        if not paren_groups and keywords:
            terms = [
                t.strip().lower().replace('"', "")
                for t in keywords.split()
                if t.strip()
            ]
            if terms:
                parsed_groups.append(terms)
        else:
            for g in paren_groups:
                terms = re.split(r"\s+OR\s+|\s+\|\s+", g, flags=re.IGNORECASE)
                clean_terms = [
                    t.strip().lower().replace('"', "") for t in terms if t.strip()
                ]
                if clean_terms:
                    parsed_groups.append(clean_terms)
        return parsed_groups

    @staticmethod
    def build_reddit_query(parsed_groups: List[List[str]]) -> str:
        if not parsed_groups:
            return ""
        and_blocks = []
        for group in parsed_groups:
            or_terms = [f'"{term.replace('"', "").strip()}"' for term in group]
            block = "(" + " OR ".join(or_terms) + ")"
            and_blocks.append(block)
        return " AND ".join(and_blocks)

    @staticmethod
    def matches_logic(text: str, parsed_groups: List[List[str]]) -> bool:
        if not parsed_groups:
            return True
        text_lower = text.lower()
        for group in parsed_groups:
            clean_group = [t.replace('"', "") for t in group]
            if not any(t in text_lower for t in clean_group):
                return False
        return True

    def search(
        self,
        keywords: str,
        criteria: str,
        subreddits: List[str],
        target_posts: int = 10,
        ai_chunk_size: int = 5,
        is_deep_scan: bool = False,
        manual_limit: int = 100,
        sort_by: str = "new",
        time_filter: str = "all",
        post_type: str = "any",
    ) -> Generator[str, None, List]:
        parsed_groups = self.parse_keywords(keywords)
        reddit_query = self.build_reddit_query(parsed_groups)

        reddit_fetch_limit = 950 if is_deep_scan else manual_limit

        yield f"⚙️ Mode: Iterative Search"
        yield f"🔎 Query: {reddit_query}"
        yield f"🎯 Goal: Find {target_posts} posts total."

        all_matches = []
        found_total = 0

        def perform_fetch(query, limit):
            matches = []
            for sub in subreddits:
                try:
                    subreddit_object = self.reddit.subreddit(sub)
                    post_stream = subreddit_object.search(
                        query, sort=sort_by, time_filter=time_filter, limit=limit
                    )
                    for post in post_stream:
                        if post_type == "text" and not post.is_self:
                            continue
                        if post_type == "media" and post.is_self:
                            continue
                        full_text = f"{post.title} {post.selftext}"
                        if self.matches_logic(full_text, self.parse_keywords(query)):
                            matches.append(post)
                except Exception as e:
                    self._log(f"Error r/{sub}: {e}")
            return matches

        all_matches = perform_fetch(reddit_query, reddit_fetch_limit)

        if not all_matches and criteria:
            yield "🔄 No results. Attempting query expansion..."
            expanded_keywords = self.llm.expand_query(keywords, criteria)
            yield f"🔎 Expanded Query: {expanded_keywords}"
            all_matches = perform_fetch(
                self.build_reddit_query(self.parse_keywords(expanded_keywords)),
                reddit_fetch_limit,
            )

        if not all_matches:
            yield "\n❌ No posts found."
            return []

        # AI PHASE
        final_posts = []
        if not criteria:
            yield "\n⏩ Skipping AI."
            final_posts = all_matches[:target_posts]
        else:
            yield f"\n🤖 AI Analyzing {len(all_matches)} candidates..."
            processed = []
            pmap = {}
            for p in all_matches:
                body = p.selftext
                if len(body) > 30000:
                    body = body[:30000] + "..."
                elif not body:
                    body = "[No Body]"
                processed.append(
                    {
                        "id": p.id,
                        "sub": p.subreddit.display_name,
                        "title": p.title,
                        "content": body,
                    }
                )
                pmap[p.id] = p

            scored_results = []
            for i in range(0, len(processed), ai_chunk_size):
                batch = processed[i : i + ai_chunk_size]
                yield f"   Chunk {i // ai_chunk_size + 1}..."
                results = self.llm.analyze(batch, criteria)
                for r in results:
                    if r.get("score", 0) > 50:  # Threshold
                        scored_results.append(r)
                time.sleep(0.5)

            # Sort by score
            scored_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            for r in scored_results[:target_posts]:
                if r["id"] in pmap:
                    final_posts.append(pmap[r["id"]])

            yield f"   🎉 Approved {len(final_posts)} posts."

        if final_posts:
            self.save_to_blacklist(final_posts, keywords, criteria)

        return final_posts

    def save_to_blacklist(self, posts: List, keywords: str, criteria: str):
        current_bl = {}
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f:
                    current_bl = json.load(f)
            except:
                pass
        for p in posts:
            current_bl[p.id] = {
                "id": p.id,
                "title": p.title,
                "url": f"https://www.reddit.com{p.permalink}",
                "keywords": keywords,
                "criteria": criteria,
                "timestamp": time.time(),
            }
        with open(BLACKLIST_FILE, "w") as f:
            json.dump(current_bl, f, indent=2)

    def discover_subreddits(
        self, keywords: str, limit_subs: int = 10, criteria: str = ""
    ) -> Generator[str, None, List[Dict]]:
        parsed_groups = self.parse_keywords(keywords)
        yield f"🌍 Searching r/all..."

        sub_hits = {}
        sub_details = {}

        simple_query = (
            " ".join([g[0] for g in parsed_groups]) if parsed_groups else keywords
        )

        try:
            for post in self.reddit.subreddit("all").search(
                simple_query, sort="new", limit=300
            ):
                if self.matches_logic(f"{post.title} {post.selftext}", parsed_groups):
                    s_name = post.subreddit.display_name
                    if s_name not in sub_hits:
                        sub_hits[s_name] = 0
                        sub_details[s_name] = post.subreddit
                    sub_hits[s_name] += 1

            yield f"✅ Found {len(sub_hits)} communities."
            sorted_subs = sorted(sub_hits.items(), key=lambda x: x[1], reverse=True)[
                : limit_subs * 2
            ]
            final_subs = []

            if not criteria:
                for name, hits in sorted_subs[:limit_subs]:
                    try:
                        desc = sub_details[name].public_description or ""
                        final_subs.append(
                            {"name": name, "hits": hits, "description": desc}
                        )
                    except:
                        pass
            else:
                yield f"🤖 AI analyzing..."
                for name, hits in sorted_subs:
                    if len(final_subs) >= limit_subs:
                        break
                    try:
                        s_obj = sub_details[name]
                        desc = s_obj.public_description or ""
                        prompt_data = {
                            "subreddit": name,
                            "description": desc,
                            "match_count": hits,
                        }
                        matches = self.llm.analyze(
                            [prompt_data], f"Is relevant to: {criteria}?"
                        )
                        if matches:
                            final_subs.append(
                                {"name": name, "hits": hits, "description": desc}
                            )
                            yield f"   ✅ AI Approved: r/{name}"
                        else:
                            yield f"   ❌ AI Rejected: r/{name}"
                    except:
                        pass
            return final_subs
        except Exception as e:
            yield f"❌ Error: {e}"
            return []


# --- FLASK APP ---
app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/generate_query", methods=["POST"])
def api_generate_query():
    data = request.json
    desc = data.get("description")
    provider = data.get("provider", "mistral")
    try:
        llm = LLMFilter(provider)
        query_string = llm.generate_boolean_string(desc)
        if query_string.startswith("Error:"):
            return jsonify({"error": query_string}), 500
        return jsonify({"query": query_string})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/blacklist", methods=["GET"])
def get_blacklist():
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r") as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})


@app.route("/api/blacklist/clear", methods=["POST"])
def clear_blacklist():
    with open(BLACKLIST_FILE, "w") as f:
        json.dump({}, f)
    return jsonify({"status": "cleared"})


@app.route("/api/subreddits", methods=["GET"])
def get_subreddits():
    if os.path.exists(SUBREDDITS_FILE):
        try:
            with open(SUBREDDITS_FILE, "r") as f:
                return jsonify(json.load(f))
        except:
            pass
    defaults = [s.strip() for s in DEFAULT_SUBS_ENV.split(",") if s.strip()]
    return jsonify(defaults)


@app.route("/api/subreddits", methods=["POST"])
def update_subreddits():
    new_list = request.json
    with open(SUBREDDITS_FILE, "w") as f:
        json.dump(new_list, f, indent=2)
    return jsonify({"status": "saved"})


@app.route("/api/queries", methods=["GET"])
def get_queries():
    if not os.path.exists(SAVED_QUERIES_FILE):
        return jsonify({})
    try:
        with open(SAVED_QUERIES_FILE, "r") as f:
            return jsonify(json.load(f))
    except:
        return jsonify({})


@app.route("/api/queries", methods=["POST"])
def save_query_route():
    data = request.json
    name = data.get("name")
    current = {}
    if os.path.exists(SAVED_QUERIES_FILE):
        try:
            with open(SAVED_QUERIES_FILE, "r") as f:
                current = json.load(f)
        except:
            pass
    current[name] = data["payload"]
    with open(SAVED_QUERIES_FILE, "w") as f:
        json.dump(current, f, indent=2)
    return jsonify({"status": "saved"})


@app.route("/api/queries/<name>", methods=["DELETE"])
def delete_query(name):
    if not os.path.exists(SAVED_QUERIES_FILE):
        return jsonify({"status": "ok"})
    with open(SAVED_QUERIES_FILE, "r") as f:
        data = json.load(f)
    if name in data:
        del data[name]
        with open(SAVED_QUERIES_FILE, "w") as f:
            json.dump(data, f, indent=2)
    return jsonify({"status": "deleted"})


@app.route("/stream")
def stream():
    keywords = request.args.get("keywords", "")
    criteria = request.args.get("criteria", "")
    provider = request.args.get("provider", "mistral")
    target_posts = int(request.args.get("target_posts", 10))
    ai_chunk_size = int(request.args.get("ai_chunk", 5))
    is_deep_scan = request.args.get("deep_scan") == "true"
    manual_limit = int(request.args.get("scan_limit", 100))
    debug_mode = request.args.get("debug") == "true"
    sort_by = request.args.get("sort", "new")
    time_filter = request.args.get("time", "all")
    post_type = request.args.get("post_type", "any")
    subs_param = request.args.get("subreddits", "")

    if subs_param:
        subs_list = [s.strip() for s in subs_param.split(",") if s.strip()]
    else:
        subs_list = ["ArtificialInteligence"]

    engine = RedditSearchEngine(provider=provider, debug=debug_mode)

    def generate():
        def send(msg):
            return f"data: {msg}\n\n"

        # Use a list to capture the return value of the generator
        final_posts_container = []

        gen = engine.search(
            keywords=keywords,
            criteria=criteria,
            subreddits=subs_list,
            target_posts=target_posts,
            ai_chunk_size=ai_chunk_size,
            is_deep_scan=is_deep_scan,
            manual_limit=manual_limit,
            sort_by=sort_by,
            time_filter=time_filter,
            post_type=post_type,
        )

        try:
            while True:
                val = next(gen)
                yield send(val)
        except StopIteration as e:
            final_posts = e.value

        html_res = ""
        for p in final_posts:
            safe_body = (
                p.selftext.replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )
            html_res += f"""<div class="card"><h3>{p.title}</h3><span class="meta">r/{p.subreddit.display_name} | <a href="https://www.reddit.com{p.permalink}" target="_blank">Open</a></span><hr style="border-color:#333"><div class="body-text">{safe_body}</div></div>"""

        yield send(f"<<<HTML_RESULT>>>{html_res.replace('\n', '||NEWLINE||')}")

    return Response(generate(), mimetype="text/event-stream")


@app.route("/stream_discovery")
def stream_discovery():
    keywords = request.args.get("keywords", "")
    limit_subs = int(request.args.get("limit", 10))
    criteria = request.args.get("criteria", "")
    provider = request.args.get("provider", "mistral")

    engine = RedditSearchEngine(provider=provider)

    def generate():
        def send(msg):
            return f"data: {msg}\n\n"

        gen = engine.discover_subreddits(keywords, limit_subs, criteria)
        try:
            while True:
                val = next(gen)
                yield send(val)
        except StopIteration as e:
            final_subs = e.value

        yield send("✨ Rendering results...")
        for sub in final_subs:
            yield send(f"<<<JSON_CARD>>>{json.dumps(sub)}")
        yield send("<<<DONE>>>")

    return Response(generate(), mimetype="text/event-stream")


# --- CLI HANDLER ---
def run_cli():
    parser = argparse.ArgumentParser(description="Reddit Search Engine CLI")
    parser.add_argument("--keywords", type=str, help="Boolean search string")
    parser.add_argument("--criteria", type=str, help="AI filtering criteria")
    parser.add_argument("--subreddits", type=str, help="Comma-separated subreddits")
    parser.add_argument(
        "--target_posts", type=int, default=10, help="Target number of posts"
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="mistral",
        choices=["mistral", "gemini"],
        help="LLM provider",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--discovery", action="store_true", help="Run discovery mode")

    parser.add_argument(
        "--deep_scan", action="store_true", help="Enable deep historical scan"
    )
    parser.add_argument(
        "--sort",
        type=str,
        default="new",
        choices=["new", "relevance", "top", "hot", "comments"],
        help="Sort order",
    )
    parser.add_argument(
        "--time",
        type=str,
        default="all",
        choices=["all", "day", "hour", "month", "week", "year"],
        help="Time filter",
    )
    parser.add_argument(
        "--post_type",
        type=str,
        default="any",
        choices=["any", "text", "media"],
        help="Filter by post type",
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Manual fetch limit (max posts to scan)"
    )
    parser.add_argument(
        "--ai_chunk", type=int, default=5, help="Batch size for AI analysis"
    )

    args = parser.parse_args()

    if not args.keywords:
        parser.print_help()
        return

    engine = RedditSearchEngine(provider=args.provider, debug=args.debug)

    if args.discovery:
        gen = engine.discover_subreddits(
            args.keywords, limit_subs=args.target_posts, criteria=args.criteria or ""
        )
        final_results = []
        try:
            for msg in gen:
                if not args.json:
                    print(msg)
        except StopIteration as e:
            final_results = e.value

        if args.json:
            print(json.dumps(final_results, indent=2))
        else:
            print(f"\nFound {len(final_results)} subreddits.")
    else:
        subs = (
            [s.strip() for s in args.subreddits.split(",")]
            if args.subreddits
            else DEFAULT_SUBS_ENV.split(",")
        )
        gen = engine.search(
            keywords=args.keywords,
            criteria=args.criteria or "",
            subreddits=subs,
            target_posts=args.target_posts,
            ai_chunk_size=args.ai_chunk,
            is_deep_scan=args.deep_scan,
            manual_limit=args.limit,
            sort_by=args.sort,
            time_filter=args.time,
            post_type=args.post_type,
        )
        final_posts = []
        try:
            for msg in gen:
                if not args.json:
                    print(msg)
        except StopIteration as e:
            final_posts = e.value

        if args.json:
            output = []
            for p in final_posts:
                output.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "subreddit": p.subreddit.display_name,
                        "url": f"https://www.reddit.com{p.permalink}",
                        "content": p.selftext,
                    }
                )
            print(json.dumps(output, indent=2))
        else:
            print(f"\nFound {len(final_posts)} approved posts.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_cli()
    else:
        app.run(host="0.0.0.0", port=5000)
