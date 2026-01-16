from flask import Flask, Response, request, render_template, jsonify
import os
import praw
import json
import time
import requests
import re
import argparse
import sys
from typing import List, Dict, Optional, Generator
from dotenv import load_dotenv, find_dotenv
from mistralai import Mistral
import prawcore

# Load environment variables
load_dotenv(find_dotenv(), override=True)

# --- CONFIGURATION ---
SAVED_QUERIES_FILE = "saved_queries.json"
SUBREDDITS_FILE = "subreddits.json"
BLACKLIST_FILE = "blacklist.json"

DEFAULT_SUBS_ENV = os.getenv(
    "REDDIT_SUBREDDITS", "ArtificialInteligence,LocalLLaMA,Python"
)
REDDIT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_AGENT = os.getenv("REDDIT_USER_AGENT", "script:flask_app:v13_optimized")
MISTRAL_KEY = os.getenv("MISTRAL_API_KEY", "")
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY", "")

class LLMFilter:
    def __init__(self, provider: str):
        self.provider = provider
        self.client = None
        self.api_key = None
        
        if provider == "mistral":
            if not MISTRAL_KEY:
                print("⚠️ Mistral Key Missing", file=sys.stderr)
            else:
                self.client = Mistral(api_key=MISTRAL_KEY)
        elif provider == "gemini":
            if not GOOGLE_KEY:
                print("⚠️ Google Key Missing", file=sys.stderr)
            else:
                self.api_key = GOOGLE_KEY

    def analyze(self, posts: List[Dict], criteria: str) -> List[Dict]:
        """Scored batch analysis of posts."""
        if not posts: return []
        
        sys_p = (
            "You are a Relevance Judge. Analyze the Reddit posts based on the User Criteria. "
            "Return a JSON object with a 'results' key containing a list of objects. "
            "Each object must have 'id' and 'score' (0-100 integer, where 100 is perfect match). "
            "Justification is not required to save tokens."
        )
        usr_p = f"USER CRITERIA: {criteria}\n\nPOSTS TO SCORE:\n{json.dumps(posts)}"

        retries = 3
        delay = 2
        
        while retries > 0:
            try:
                content = ""
                if self.provider == "mistral" and self.client:
                    res = self.client.chat.complete(
                        model="mistral-large-latest",
                        messages=[
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": usr_p},
                        ],
                        response_format={"type": "json_object"},
                    )
                    content = str(res.choices[0].message.content)
                
                elif self.provider == "gemini" and self.api_key:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
                    pl = {
                        "contents": [{"parts": [{"text": usr_p}]}],
                        "system_instruction": {"parts": [{"text": sys_p}]},
                        "generationConfig": {"response_mime_type": "application/json"},
                    }
                    res = requests.post(
                        url, json=pl, headers={"Content-Type": "application/json"}
                    )
                    if res.status_code != 200:
                        raise Exception(f"Gemini API Error: {res.text}")
                    content = res.json()["candidates"][0]["content"]["parts"][0]["text"]

                # Parse JSON safely
                try:
                    data = json.loads(content)
                    return data.get("results", [])
                except json.JSONDecodeError:
                    # Fallback regex extraction
                    match = re.search(r"\{.*\}", content, re.DOTALL)
                    if match:
                        return json.loads(match.group(0)).get("results", [])
                    return []

            except Exception as e:
                print(f"LLM Error ({self.provider}): {e}", file=sys.stderr)
                if "429" in str(e):
                    time.sleep(delay)
                    retries -= 1
                    delay *= 2
                else:
                    return []
        return []

    def generate_boolean_string(self, description: str) -> str:
        sys_p = (
            "You are a Search Logic Generator. Convert the user's request into a precise Reddit Boolean Query.\n"
            "Supported Operators: AND, OR, ( ). Wildcards (*) are supported.\n"
            "Rules:\n"
            "1. Output ONLY the raw query string. No markdown, no explanations.\n"
            "2. Group Synonyms with OR inside parentheses: (car OR auto OR vehicle).\n"
            "3. Combine concepts with AND: (concept1) AND (concept2).\n"
            "4. Use quotes for multi-word phrases: \"machine learning\".\n"
            "5. Use wildcards for variations: run* (matches running, runner).\n"
            "6. Max length: ~6-8 terms to prevent timeouts."
        )

        try:
            content = ""
            if self.provider == "mistral" and self.client:
                res = self.client.chat.complete(
                    model="mistral-large-latest",
                    messages=[
                        {"role": "system", "content": sys_p},
                        {"role": "user", "content": description},
                    ],
                )
                content = res.choices[0].message.content
            elif self.provider == "gemini" and self.api_key:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.api_key}"
                pl = {
                    "contents": [{"parts": [{"text": description}]}],
                    "system_instruction": {"parts": [{"text": sys_p}]},
                }
                res = requests.post(url, json=pl, headers={"Content-Type": "application/json"})
                content = res.json()["candidates"][0]["content"]["parts"][0]["text"]

            # Cleanup
            query = str(content).strip().replace("```", "").replace("\n", " ")
            if query.startswith('"') and query.endswith('"'):
                query = query[1:-1]
            return query
            
        except Exception as e:
            return f"Error: {str(e)}"

    def expand_query(self, original: str, criteria: str) -> str:
        # Placeholder for query expansion logic if 0 results
        return original


class RedditSearchEngine:
    def __init__(self, provider: str = "mistral", debug: bool = False):
        self.provider = provider
        self.debug = debug
        self.reddit = praw.Reddit(
            client_id=REDDIT_ID, 
            client_secret=REDDIT_SECRET, 
            user_agent=REDDIT_AGENT
        )
        self.llm = LLMFilter(provider)

    def _log(self, msg: str):
        if self.debug:
            print(f"DEBUG: {msg}", file=sys.stderr)

    @staticmethod
    def parse_keywords(keywords: str) -> List[List[str]]:
        """Parses Boolean string into a list of lists for local logic checking."""
        parsed_groups = []
        # Extract groups inside parentheses
        paren_groups = re.findall(r"\(([^)]+)\)", keywords)
        
        # If no parentheses, treat whole string as one group (or split by AND if implicit)
        if not paren_groups:
            if " AND " in keywords:
                parts = keywords.split(" AND ")
                for p in parts:
                    parsed_groups.append([p.strip().replace('"', '')])
            else:
                # Fallback: treat as single list of ORs if just words, or raw text
                terms = [t.strip().replace('"', '') for t in keywords.split() if t.strip()]
                if terms: parsed_groups.append(terms)
        else:
            for g in paren_groups:
                # Split by OR
                terms = re.split(r"\s+OR\s+|\s+\|\s+", g, flags=re.IGNORECASE)
                # Keep wildcards, strip quotes
                clean_terms = [t.strip().replace('"', "") for t in terms if t.strip()]
                if clean_terms:
                    parsed_groups.append(clean_terms)
                    
        return parsed_groups

    @staticmethod
    def matches_logic(text: str, parsed_groups: List[List[str]]) -> bool:
        """
        Validates if text matches the parsed Boolean logic locally.
        Supports Wildcards (*) via Regex conversion.
        """
        if not parsed_groups:
            return True
            
        text_lower = text.lower()
        
        for group in parsed_groups:
            group_match = False
            for term in group:
                term_lower = term.lower()
                
                # Check for wildcard
                if '*' in term_lower:
                    # Escape special regex chars except *, then replace * with \w*
                    # \b ensures we match start of word (optional, but usually desired)
                    regex_pattern = re.escape(term_lower).replace(r'\*', r'\w*')
                    # Add boundary check so 'cat' doesn't match 'certificate' unless wildcard used
                    if not term_lower.startswith('*'):
                        regex_pattern = r'\b' + regex_pattern
                    
                    if re.search(regex_pattern, text_lower):
                        group_match = True
                        break
                else:
                    # Standard exact substring match (or whole word if preferred)
                    if term_lower in text_lower:
                        group_match = True
                        break
            
            if not group_match:
                return False # AND condition failed
                
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
        
        yield f"⚙️ Mode: Iterative Search"
        yield f"🔎 Raw Query: {keywords}"
        yield f"🎯 Goal: Find {target_posts} posts total."

        all_matches = []
        seen_ids = set()

        # Decide which subs to use
        search_subs = subreddits
        if "all" in subreddits and len(subreddits) == 1:
            search_subs = DEFAULT_SUBS_ENV.split(",")

        def fetch_candidates():
            yield f"ℹ️ Searching across {len(search_subs)} subreddits..."
            matches_found = 0
            
            for sub in search_subs:
                if matches_found >= manual_limit and not is_deep_scan:
                    break
                    
                try:
                    # PRAW requires valid Reddit query syntax. 
                    # We pass the raw keywords assuming the frontend/LLM built valid boolean syntax.
                    # We rely on local filtering for precision.
                    sub_obj = self.reddit.subreddit(sub)
                    
                    # Adjust PRAW limit based on scan type
                    praw_limit = 100 if not is_deep_scan else 500
                    
                    iterator = sub_obj.search(
                        keywords, 
                        sort=sort_by, 
                        time_filter=time_filter, 
                        limit=praw_limit
                    )
                    
                    for post in iterator:
                        if post.id in seen_ids: continue
                        seen_ids.add(post.id)
                        
                        # Type Filter
                        if post_type == "text" and not post.is_self: continue
                        if post_type == "media" and post.is_self: continue

                        # Local Logic Filter (handles wildcards correctly now)
                        full_content = f"{post.title} {post.selftext}"
                        if self.matches_logic(full_content, parsed_groups):
                            matches_found += 1
                            all_matches.append(post)
                            # Yield progress dot every 5 matches
                            if matches_found % 5 == 0:
                                yield f"   Found {matches_found} candidates..."
                                
                        if matches_found >= manual_limit and not is_deep_scan:
                            break
                            
                except Exception as e:
                    self._log(f"Error r/{sub}: {e}")
                    # Don't crash stream on one sub error
                    continue
        
        # Run Fetcher
        for msg in fetch_candidates():
            yield msg

        if not all_matches:
            yield "\n❌ No posts found matching local filters."
            return []

        yield f"✅ Found {len(all_matches)} candidates. Starting Analysis..."

        # Prepare for AI
        processed_candidates = []
        post_map = {}
        for p in all_matches:
            # Truncate for AI context window
            content = p.selftext[:1500] if p.selftext else "[Title Only]"
            processed_candidates.append({
                "id": p.id,
                "sub": p.subreddit.display_name,
                "title": p.title,
                "content": content
            })
            post_map[p.id] = p

        final_approved = []

        # If no criteria, just return them all
        if not criteria.strip():
            yield "⏩ No AI criteria provided. Returning raw matches."
            final_approved = [{
                "id": p.id,
                "title": p.title,
                "sub": p.subreddit.display_name,
                "url": f"https://www.reddit.com{p.permalink}",
                "content": p.selftext,
                "score": 100
            } for p in all_matches[:target_posts]]
        else:
            # AI Batch Processing
            chunks = [processed_candidates[i:i + ai_chunk_size] for i in range(0, len(processed_candidates), ai_chunk_size)]
            
            for i, batch in enumerate(chunks):
                yield f"🤖 Analyzing batch {i+1}/{len(chunks)}..."
                scores = self.llm.analyze(batch, criteria)
                
                for res in scores:
                    score = res.get("score", 0)
                    pid = res.get("id")
                    
                    if score >= 60 and pid in post_map:
                        p = post_map[pid]
                        final_approved.append({
                            "id": p.id,
                            "title": p.title,
                            "sub": p.subreddit.display_name,
                            "url": f"https://www.reddit.com{p.permalink}",
                            "content": p.selftext,
                            "score": score
                        })
                
                if len(final_approved) >= target_posts:
                    break
                time.sleep(0.5) # Rate limit politeness

        # Sort by score
        final_approved.sort(key=lambda x: x['score'], reverse=True)
        final_approved = final_approved[:target_posts]

        yield f"🎉 Finished! {len(final_approved)} posts approved."
        
        # Save to history
        if final_approved:
            self.save_to_blacklist(final_approved, keywords, criteria)

        return final_approved

    def save_to_blacklist(self, posts: List[Dict], keywords: str, criteria: str):
        """Saves search results to the persistent history file."""
        current_bl = {}
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f:
                    current_bl = json.load(f)
            except: pass
            
        for p in posts:
            current_bl[p['id']] = {
                "id": p['id'],
                "title": p['title'],
                "url": p['url'],
                "keywords": keywords,
                "criteria": criteria,
                "score": p['score'],
                "timestamp": time.time()
            }
            
        with open(BLACKLIST_FILE, "w") as f:
            json.dump(current_bl, f, indent=2)

    def discover_subreddits(self, keywords: str, limit_subs: int = 10, criteria: str = "") -> Generator[str, None, List[Dict]]:
        """Finds subreddits relevant to the query."""
        parsed_groups = self.parse_keywords(keywords)
        yield "🌍 Searching r/all for active communities..."
        
        sub_stats = {}
        sub_objs = {}
        
        try:
            # Cast wide net
            search_query = keywords if "AND" in keywords else keywords.replace(" ", " OR ")
            
            for post in self.reddit.subreddit("all").search(search_query, sort="relevance", limit=200):
                if self.matches_logic(post.title, parsed_groups):
                    sub_name = post.subreddit.display_name
                    if sub_name not in sub_stats:
                        sub_stats[sub_name] = 0
                        sub_objs[sub_name] = post.subreddit
                    sub_stats[sub_name] += 1
            
            sorted_subs = sorted(sub_stats.items(), key=lambda x: x[1], reverse=True)[:20]
            
            final_subs = []
            yield f"✅ Found {len(sorted_subs)} potential communities. Analyzing relevance..."
            
            for name, hits in sorted_subs:
                if len(final_subs) >= limit_subs: break
                
                try:
                    desc = sub_objs[name].public_description or "No description"
                    
                    # If criteria exists, ask AI
                    is_relevant = True
                    if criteria:
                        res = self.llm.analyze([{
                            "id": name, 
                            "content": f"Subreddit: {name}\nDescription: {desc}\nTopic Hits: {hits}"
                        }], f"Is this subreddit suitable for: {criteria}?")
                        if not res or res[0].get('score', 0) < 50:
                            is_relevant = False
                            yield f"   ❌ r/{name} rejected by AI."

                    if is_relevant:
                        final_subs.append({"name": name, "hits": hits, "description": desc})
                        yield f"   ✅ r/{name} added!"
                        
                except Exception as e:
                    pass

            return final_subs
            
        except Exception as e:
            yield f"Error during discovery: {e}"
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
    
    if not desc: return jsonify({"error": "No description provided"}), 400
    
    query = LLMFilter(provider).generate_boolean_string(desc)
    return jsonify({"query": query})

@app.route("/api/subreddits", methods=["GET", "POST"])
def manage_subreddits():
    if request.method == "POST":
        with open(SUBREDDITS_FILE, "w") as f:
            json.dump(request.json, f, indent=2)
        return jsonify({"status": "saved"})
    
    if os.path.exists(SUBREDDITS_FILE):
        with open(SUBREDDITS_FILE, "r") as f:
            return jsonify(json.load(f))
    return jsonify(DEFAULT_SUBS_ENV.split(","))

@app.route("/api/queries", methods=["GET", "POST"])
def manage_queries():
    current_data = {}
    if os.path.exists(SAVED_QUERIES_FILE):
        try:
            with open(SAVED_QUERIES_FILE, "r") as f:
                current_data = json.load(f)
        except: pass

    if request.method == "POST":
        data = request.json
        current_data[data["name"]] = data["payload"]
        with open(SAVED_QUERIES_FILE, "w") as f:
            json.dump(current_data, f, indent=2)
        return jsonify({"status": "saved"})
        
    return jsonify(current_data)

@app.route("/api/queries/<name>", methods=["DELETE"])
def delete_query(name):
    if os.path.exists(SAVED_QUERIES_FILE):
        with open(SAVED_QUERIES_FILE, "r") as f:
            data = json.load(f)
        if name in data:
            del data[name]
            with open(SAVED_QUERIES_FILE, "w") as f:
                json.dump(data, f, indent=2)
    return jsonify({"status": "deleted"})

@app.route("/api/blacklist", methods=["GET"])
def get_history():
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r") as f:
                return jsonify(json.load(f))
        except: pass
    return jsonify({})

@app.route("/api/blacklist/clear", methods=["POST"])
def clear_history():
    with open(BLACKLIST_FILE, "w") as f:
        json.dump({}, f)
    return jsonify({"status": "cleared"})

@app.route("/stream")
def stream_search():
    # Extract params
    keywords = request.args.get("keywords", "")
    criteria = request.args.get("criteria", "")
    provider = request.args.get("provider", "mistral")
    target = int(request.args.get("target_posts", 10))
    chunk = int(request.args.get("ai_chunk", 5))
    is_deep = request.args.get("deep_scan") == "true"
    limit = int(request.args.get("scan_limit", 100))
    
    subs = request.args.get("subreddits", "").split(",")
    subs = [s.strip() for s in subs if s.strip()]
    if not subs: subs = ["all"]
    
    # Init Engine
    engine = RedditSearchEngine(provider=provider, debug=request.args.get("debug") == "true")
    
    def generate():
        def send(data): return f"data: {data}\n\n"
        
        final_posts = []
        gen = engine.search(
            keywords=keywords,
            criteria=criteria,
            subreddits=subs,
            target_posts=target,
            ai_chunk_size=chunk,
            is_deep_scan=is_deep,
            manual_limit=limit,
            sort_by=request.args.get("sort", "new"),
            time_filter=request.args.get("time", "all"),
            post_type=request.args.get("post_type", "any")
        )
        
        try:
            while True:
                val = next(gen)
                yield send(val)
        except StopIteration as e:
            final_posts = e.value
            
        # 1. Send JSON data for the Export/Score View
        json_data = json.dumps(final_posts)
        yield send(f"<<<APPROVED_POSTS>>>{json_data}")
        
        # 2. Send HTML for the Visual Card View
        html_out = ""
        for p in final_posts:
            # Safe HTML escaping
            safe_body = p['content'].replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            html_out += f"""
            <div class="card">
                <h3>{p['title']} <span style="float:right; color:#10b981; font-size:0.8em">{p['score']}</span></h3>
                <span class="meta">r/{p['sub']} | <a href="{p['url']}" target="_blank">Open</a></span>
                <hr style="border-color:#333">
                <div class="body-text">{safe_body}</div>
            </div>
            """
        # Replace newlines so SSE doesn't break
        yield send(f"<<<HTML_RESULT>>>{html_out.replace(chr(10), '||NEWLINE||')}")

    return Response(generate(), mimetype="text/event-stream")

@app.route("/stream_discovery")
def stream_discovery():
    keywords = request.args.get("keywords", "")
    limit = int(request.args.get("limit", 10))
    criteria = request.args.get("criteria", "")
    provider = request.args.get("provider", "mistral")
    
    engine = RedditSearchEngine(provider=provider)
    
    def generate():
        def send(data): return f"data: {data}\n\n"
        
        gen = engine.discover_subreddits(keywords, limit, criteria)
        final_subs = []
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

# --- CLI ENTRY ---
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run_cli":
        # Basic CLI support if needed
        print("Please run via Flask: python app.py")
    else:
        app.run(host="0.0.0.0", port=5000)