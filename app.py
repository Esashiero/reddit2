import prawcore
import logging
from logging.handlers import RotatingFileHandler
from markupsafe import escape
from collections import deque
from functools import lru_cache
import hashlib

load_dotenv(find_dotenv(), override=True)

# --- Configuration & Logging ---
def setup_logging(debug: bool = False):
    logger = logging.getLogger("reddit_search")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    if not logger.handlers:
        # File handler
        try:
            fh = RotatingFileHandler("app.log", maxBytes=10_000_000, backupCount=5)
            fh.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            logger.addHandler(fh)
        except Exception as e:
            print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)
        
        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.addHandler(ch)
    
    return logger

logger = setup_logging()

def validate_env():
    missing = []
    if not os.getenv("REDDIT_CLIENT_ID"): missing.append("REDDIT_CLIENT_ID")
    if not os.getenv("REDDIT_CLIENT_SECRET"): missing.append("REDDIT_CLIENT_SECRET")
    
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        # We don't exit here to allow CLI help to work, but class init will fail later
    return missing

validate_env()

# --- Files & Constants ---
SAVED_QUERIES_FILE = "saved_queries.json"
SUBREDDITS_FILE = "subreddits.json"
BLACKLIST_FILE = "blacklist.json"

DEFAULT_SUBS_ENV = os.getenv(
    "REDDIT_SUBREDDITS", "offmychest,sexualassault,TwoXChromosomes,amiwrong,relationship_advice,confessions,india,indiasocial,advice,relationships,lifeadvice,trueoffmychest,self,rapecounseling,vent,questions,familyissues,family"
)
REDDIT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_AGENT = os.getenv("REDDIT_USER_AGENT", "script:flask_app:v12_fixed")
MISTRAL_KEY = os.getenv("MISTRAL_API_KEY", "")
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY", "")


class LLMFilter:
    def __init__(self, provider: str, debug: bool = False):
        self.provider = provider
        self.debug = debug
        self._analysis_cache = {}
        
        if provider == "mistral":
            if not MISTRAL_KEY:
                logger.warning("MISTRAL_API_KEY missing. LLM features will fail.")
            else:
                self.client = Mistral(api_key=MISTRAL_KEY)
        elif provider == "gemini":
            if not GOOGLE_KEY:
                logger.warning("GOOGLE_API_KEY missing. LLM features will fail.")
            else:
                self.api_key = GOOGLE_KEY

    def _get_cache_key(self, posts: List[Dict], criteria: str) -> str:
        # Create a stable hash of the input
        ids = sorted([p.get('id', '') for p in posts])
        payload = f"{criteria}:{','.join(ids)}"
        return hashlib.md5(payload.encode()).hexdigest()

    def analyze(self, posts: List[Dict], criteria: str) -> List[Dict]:
        if not posts:
            return []
            
        cache_key = self._get_cache_key(posts, criteria)
        if cache_key in self._analysis_cache:
            if self.debug: logger.debug(f"Cache hit for analysis batch")
            return self._analysis_cache[cache_key]

        sys_p = (
            "Analyze the following Reddit posts based on the criteria. "
            "Return a JSON object with a 'results' key containing a list of objects. "
            "Each object must have 'id' and 'score' (0-100, where 100 is perfect match). "
            'Example: {"results": [{"id": "abc", "score": 85}]}'
        )
        usr_p = f"CRITERIA: {criteria}\nPOSTS:\n{json.dumps(posts)}"

        retries = 3
        delay = 5
        while retries > 0:
            content = "N/A"
            try:
                if self.provider == "mistral" and hasattr(self, "client"):
                    res = self.client.chat.complete(
                        model="mistral-large-latest",
                        messages=[
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": usr_p},
                        ],
                        response_format={"type": "json_object"},
                    )
                    content = str(res.choices[0].message.content)
                elif hasattr(self, "api_key"):
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
                    pl = {
                        "contents": [{"parts": [{"text": usr_p}]}],
                        "system_instruction": {"parts": [{"text": sys_p}]},
                        "generationConfig": {"response_mime_type": "application/json"},
                    }
                    res = requests.post(
                        url, json=pl, headers={"Content-Type": "application/json"}
                    )
                    content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    return []

                try:
                    res_data = json.loads(content).get("results", [])
                    self._analysis_cache[cache_key] = res_data
                    return res_data
                except json.JSONDecodeError:
                    match = re.search(r"```json\s*({.*?})\s*```", content, re.DOTALL)
                    if match:
                        res_data = json.loads(match.group(1)).get("results", [])
                        self._analysis_cache[cache_key] = res_data
                        return res_data
                    match = re.search(r"({.*})", content, re.DOTALL)
                    if match:
                        res_data = json.loads(match.group(1)).get("results", [])
                        self._analysis_cache[cache_key] = res_data
                        return res_data
                    raise

            except Exception as e:
                if "429" in str(e):
                    logger.warning(f"Rate limited by {self.provider}, retrying in {delay}s...")
                    time.sleep(delay)
                    retries -= 1
                    delay *= 2
                else:
                    logger.error(f"LLM Error ({self.provider}): {e}")
                    if self.debug:
                        logger.debug(f"Raw Content: {content}")
                    return []
        return []

    def expand_query(self, original_keywords: str, criteria: str) -> str:
        # Implementation could be expanded, but keeping simple for now
        return original_keywords

    def generate_boolean_string(self, description: str) -> str:
        sys_p = (
            "You are an expert Reddit Search Engineer. Your task is to generate a high-precision Boolean Search String.\n\n"
            "**SOCRATIC INTENT DECOMPOSITION:**\n"
            "1. Clarification: Core event/entity?\n"
            "2. Assumption Probing: Implicit details?\n"
            "3. Implication Probing: Narrative jargon/markers?\n\n"
            "**REDDIT SEARCH SYNTAX:**\n"
            "SUPPORTED: AND, OR, parentheses grouping\n"
            "NOT SUPPORTED: ~ (proximity), ^ (boosting), self:text:, field: prefixes\n"
            "**SIMPLE FORMAT:** (term1 OR term2) AND (term3 OR term4)\n\n"
            "**STRICT RULES:**\n"
            "1. MAX 3 AND groups total. Overly restrictive queries fail.\n"
            "2. MAX 2-3 terms per OR group. Reddit's search engine breaks with 5+ OR terms!\n"
            "3. NO nested parentheses like `((A OR B) AND C)`. Keep it simple: `(A OR B) AND (C OR D)`.\n"
            "4. NO trailing operators. NEVER end a group like `(term OR )` or `(term AND )`.\n"
            "5. NO markdown blocks (```). Return ONLY the raw string.\n"
            "6. NO generic words like 'story' or 'experience'.\n"
            "7. USE SIMPLE QUERIES: 2-3 keywords total, not 15+. Reddit search is fragile.\n"
            "8. Use specific terms, not phrases. Reddit search does full-text matching."
        )

        # def generate_boolean_string(self, description: str) -> str:
        #     sys_p = (
        #         "You are an expert Reddit Search Engineer. Your task is to generate a high-precision Boolean Search String "
        #         "based on the user's description. The query must be optimized for Reddit's search engine.\n\n"
        #         "**SOCRATIC INTENT DECOMPOSITION:**\n"
        #         "Before generating the query, you MUST perform a 3-axis decomposition:\n"
        #         "1. **Clarification**: What is the core event or entity being sought?\n"
        #         "2. **Assumption Probing**: What implicit details must be present (e.g., gender, relationship, specific setting)?\n"
        #         "3. **Implication Probing**: What linguistic markers or 'aftermath jargon' would a user naturally use when discussing this?\n\n"
        #         "**CRITICAL PRINCIPLE:** Precision over recall. Better to return 5-30 highly relevant results than 100 irrelevant ones.\n\n"
        #         "**Rules:**\n"
        #         "1. **Structure:** Identify ONLY 2-3 MOST critical concepts. Each additional AND group dramatically reduces results. Connect groups with AND.\n"
        #         "2. **EXTRACTION STRATEGY:**\n"
        #         "   - Focus on distinctive, high-signal entities and actions\n"
        #         "   - For each critical concept, include 3-4 natural variations people use on Reddit\n"
        #         "3. **SPECIFICITY RULES:**\n"
        #         "   - NEVER use generic story terms: 'story', 'experience', 'personal', 'happened to me', 'first person', 'true story'\n"
        #         '5. **Format:** Return ONLY the raw string: (term1 OR term2 OR "term 3") AND (term4 OR term5 OR term6).\n'
        #         "6. **Constraints:** No markdown, no explanations. Do not nest parentheses."
        #     )

        retries = 3
        delay = 5
        while retries > 0:
            try:
                if self.provider == "mistral" and hasattr(self, "client"):
                    res = self.client.chat.complete(
                        model="mistral-large-latest",
                        messages=[
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": description},
                        ],
                    )
                    query_string = str(res.choices[0].message.content).strip()
                elif hasattr(self, "api_key"):
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
                else:
                    return "Error: No LLM Provider configured."

                query_string = (
                    query_string.replace("```", "").replace("lucene", "").strip()
                )

                if self.debug:
                    print(
                        f"DEBUG: LLM generated query: {query_string}", file=sys.stderr
                    )

                return query_string
            except Exception as e:
                if "429" in str(e):
                    time.sleep(delay)
                    retries -= 1
                    delay *= 2
                else:
                    return f"Error: {e}"
        return "Error: LLM rate limit exceeded."


DEFAULT_SEARCH_SUBREDDITS = [
    "offmychest",
    "sexualassault",
    "TwoXChromosomes",
    "amiwrong",
    "relationship_advice",
    "confessions",
    "india",
    "indiasocial",
    "advice",
    "relationships",
    "lifeadvice",
    "trueoffmychest",
    "self",
    "rapecounseling",
    "vent",
    "questions",
    "familyissues",
    "family",
]


class RedditSearchEngine:
    def __init__(self, provider: str = "mistral", debug: bool = False):
        self.provider = provider
        self.debug = debug
        self.reddit = praw.Reddit(
            client_id=REDDIT_ID, client_secret=REDDIT_SECRET, user_agent=REDDIT_AGENT
        )
        self.llm = LLMFilter(provider, debug=debug)

    def _log(self, msg: str):
        if self.debug:
            logger.debug(msg)
        elif "Error" in msg or "Warning" in msg:
            logger.error(msg)

    @staticmethod
    def parse_keywords(keywords: str) -> List[List[str]]:
        """
        Parse Boolean search string into groups of OR terms.
        Input: (uncle OR brother) AND (sleep OR rest)
        Output: [['uncle', 'brother'], ['sleep', 'rest']]
        """
        parsed_groups = []
        # Find all parenthesized groups
        paren_groups = re.findall(r"\(([^)]+)\)", keywords)

        for g in paren_groups:
            # Split by OR (with whitespace around it) or |
            terms = re.split(r"\s+OR\s+|\s+\|\s+", g, flags=re.IGNORECASE)
            clean_terms = [
                t.strip().lower().replace('"', "") for t in terms if t.strip()
            ]
            if clean_terms:
                parsed_groups.append(clean_terms)

        return parsed_groups

    @staticmethod
    def build_reddit_query(parsed_groups: List[List[str]]) -> str:
        """Builds a Reddit-compatible search query from parsed groups."""
        if not parsed_groups:
            return ""
        and_blocks = []
        for group in parsed_groups:
            # Strip ~N and ^N suffixes, then quote terms for Reddit
            or_terms = []
            for term in group:
                clean_term = term
                if "~" in term:
                    clean_term = term.split("~")[0].strip()
                if "^" in term:
                    clean_term = term.split("^")[0].strip()
                clean_term = clean_term.strip('"').strip()
                or_terms.append(f'"{clean_term}"')
            block = "(" + " OR ".join(or_terms) + ")"
            and_blocks.append(block)
        return " AND ".join(and_blocks)

    @staticmethod
    def matches_logic(text: str, parsed_groups: List[List[str]]) -> bool:
        """
        Validates if text matches the parsed Boolean logic.
        (A OR B) AND (C) -> parsed_groups = [[a, b], [c]]
        """
        if not parsed_groups:
            return True
        text_lower = text.lower()

        for group in parsed_groups:
            # Check if ANY term in the group exists in text
            if not any(term in text_lower for term in group):
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
        # 1. Parse keywords for client-side filtering
        parsed_groups = self.parse_keywords(keywords)
        # 2. Build Reddit-compatible query for API calls
        reddit_query = self.build_reddit_query(parsed_groups)
        print(reddit_query)
        if self.debug:
            self._log(f"DEBUG: Parsed Filter Groups: {parsed_groups}")
            self._log(f"DEBUG: Reddit Query: {reddit_query}")

        yield f"⚙️ Mode: Iterative Search\n🔎 Query: {keywords}\n🎯 Goal: Find {target_posts} posts total."

        all_matches = []
        seen_ids = set()
        total_matches = 0  # Track total matches across all subreddits

        def perform_fetch(query, limit):
            search_subs = (
                subreddits if "all" not in subreddits else DEFAULT_SEARCH_SUBREDDITS
            )
            yield f"ℹ️ Searching across {len(search_subs)} subreddits."
            nonlocal total_matches  # Allow modification of outer variable

            for sub in search_subs:
                self._log(f"Searching r/{sub}...")
                yield f"📡 Scanning r/{sub}..."
                try:
                    # Use a larger fetch limit because we filter locally
                    fetch_limit = max(limit * 2, 50)

                    for post in self.reddit.subreddit(sub).search(
                        query,
                        sort=sort_by,
                        time_filter=time_filter,
                        limit=fetch_limit,
                    ):
                        if post.id in seen_ids:
                            continue
                        seen_ids.add(post.id)

                        if (post_type == "text" and not post.is_self) or (
                            post_type == "media" and post.is_self
                        ):
                            continue

                        # Local filtering - only yield progress, not full post content
                        full_text = f"{post.title} {post.selftext}"
                        if self.matches_logic(full_text, parsed_groups):
                            total_matches += 1
                            # Just show progress, not full post content
                            yield f"📍 Found match #{total_matches}: {post.title[:60]}..."
                            p_data = {
                                "id": post.id,
                                "title": post.title,
                                "sub": post.subreddit.display_name,
                                "url": f"https://www.reddit.com{post.permalink}",
                                "content": post.selftext[:500] + "...",
                                "timestamp": post.created_utc,
                            }
                            # Store for later processing, don't yield to stream
                            all_matches.append((post, p_data))
                        elif self.debug:
                            self._log(
                                f"DEBUG: Filtered out {post.id} ({post.title[:30]}...)"
                            )

                        # Stop if we've reached the total limit across all subreddits
                        if total_matches >= limit:
                            yield f"🛑 Reached limit of {limit} matches."
                            return  # Exit the function entirely
                except Exception as e:
                    self._log(f"Error in r/{sub}: {e}")
                    continue

        # Execute Fetch - Use the built reddit_query, not the original keywords
        for _ in perform_fetch(reddit_query, manual_limit):
            pass

        if not all_matches:
            yield "\n❌ No posts found matching strict criteria."
            yield "💡 Tip: Reddit's search covers comments, but this tool filters by Title/Body. Try removing quotes or broad terms."
            return []

        yield f"✅ Found {len(all_matches)} candidate posts."

        if criteria:
            yield f"\n🤖 AI Analyzing {len(all_matches)} candidates..."
            processed, pmap = [], {}
            for post, p_data in all_matches:
                processed.append(
                    {
                        "id": p_data["id"],
                        "sub": p_data["sub"],
                        "title": p_data["title"],
                        "content": p_data["content"],
                    }
                )
                pmap[p_data["id"]] = post

            scored_results = []
            for i in range(0, len(processed), ai_chunk_size):
                batch = processed[i : i + ai_chunk_size]
                yield f"   Processing batch {i // ai_chunk_size + 1}..."
                results = self.llm.analyze(batch, criteria)
                for r in results:
                    yield f"<<<POST_SCORED>>>{json.dumps(r)}"
                    if r.get("score", 0) > 50:
                        scored_results.append(r)

            scored_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            final_posts = []
            for r in scored_results[:target_posts]:
                if r["id"] in pmap:
                    post = pmap[r["id"]]
                    final_posts.append(
                        {
                            "id": r["id"],
                            "title": post.title,
                            "sub": post.subreddit.display_name,
                            "url": f"https://www.reddit.com{post.permalink}",
                            "score": r.get("score", 0),
                            "content": post.selftext,
                        }
                    )
            yield f"   🎉 Approved {len(final_posts)} posts."
            yield f"<<<APPROVED_POSTS>>>{json.dumps(final_posts)}"
            yield "<<<DONE>>>"
            return final_posts

        # No AI criteria - return PRAW post objects
        return all_matches[:target_posts]

    def save_to_blacklist(self, posts: List, keywords: str, criteria: str):
        current_bl = {}
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f:
                    current_bl = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load blacklist file: {e}")

        for p in posts:
            current_bl[p.id] = {
                "id": p.id,
                "title": p.title,
                "url": f"https://www.reddit.com{p.permalink}",
                "keywords": keywords,
                "criteria": criteria,
                "timestamp": time.time(),
            }
        
        try:
            with open(BLACKLIST_FILE, "w") as f:
                json.dump(current_bl, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save blacklist: {e}")

    def discover_subreddits(
        self, keywords: str, limit_subs: int = 10, criteria: str = ""
    ) -> Generator[str, None, List[Dict]]:
        parsed_groups = self.parse_keywords(keywords)
        yield "🌍 Searching r/all..."

        # Create a simple query for initial discovery if complex logic fails
        simple_query = keywords
        if parsed_groups:
            simple_query = " ".join([g[0] for g in parsed_groups])

        sub_hits = {}
        sub_details = {}

        try:
            for post in self.reddit.subreddit("all").search(
                keywords, sort="new", limit=300
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
                        s_obj = sub_details[name]
                        desc = s_obj.public_description or ""
                        final_subs.append(
                            {"name": name, "hits": hits, "description": desc}
                        )
                    except Exception as e:
                        logger.warning(f"Error fetching details for r/{name}: {e}")
                        continue
            else:
                yield "🤖 AI analyzing..."
                for name, hits in sorted_subs:
                    if len(final_subs) >= limit_subs:
                        break
                    try:
                        s_obj = sub_details[name]
                        desc = getattr(s_obj, "public_description", "") or ""
                        prompt_data = {
                            "subreddit": name,
                            "description": desc,
                            "match_count": hits,
                        }
                        # Simple relevance check
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
                    except Exception as e:
                        logger.warning(f"Error during AI discovery for r/{name}: {e}")
                        continue
            return final_subs
        except Exception as e:
            yield f"❌ Error: {e}"
            return []


app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/rescore", methods=["POST"])
def api_rescore():
    data = request.json
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400
        
    posts = data.get("posts", [])
    criteria = data.get("criteria", "")
    provider = data.get("provider", "mistral")

    if not posts or not criteria:
        return jsonify({"error": "Missing posts or criteria"}), 400

    try:
        llm = LLMFilter(provider)
        results = llm.analyze(posts, criteria)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate_query", methods=["POST"])
def api_generate_query():
    data = request.json
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    desc = data.get("description")
    if not desc:
        return jsonify({"error": "description is required"}), 400
    provider = data.get("provider", "mistral")
    try:
        query_string = LLMFilter(provider).generate_boolean_string(desc)
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
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading blacklist: {e}")
    return jsonify({})


@app.route("/api/blacklist/clear", methods=["POST"])
def clear_blacklist():
    try:
        with open(BLACKLIST_FILE, "w") as f:
            json.dump({}, f)
        return jsonify({"status": "cleared"})
    except IOError as e:
        logger.error(f"Failed to clear blacklist: {e}")
        return jsonify({"error": "Failed to clear blacklist"}), 500


@app.route("/api/subreddits", methods=["GET"])
def get_subreddits():
    if os.path.exists(SUBREDDITS_FILE):
        try:
            with open(SUBREDDITS_FILE, "r") as f:
                return jsonify(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading subreddits file: {e}")
    
    # Fallback to DEFAULT_SUBS_ENV if file missing or corrupt
    return jsonify([s.strip() for s in DEFAULT_SUBS_ENV.split(",") if s.strip()])


@app.route("/api/subreddits", methods=["POST"])
def update_subreddits():
    if not isinstance(request.json, list):
        return jsonify({"error": "Subreddits must be a JSON list"}), 400
    try:
        with open(SUBREDDITS_FILE, "w") as f:
            json.dump(request.json, f, indent=2)
        return jsonify({"status": "saved"})
    except IOError as e:
        logger.error(f"Failed to save subreddits: {e}")
        return jsonify({"error": "Failed to save subreddits"}), 500


@app.route("/api/queries", methods=["GET"])
def get_queries():
    if not os.path.exists(SAVED_QUERIES_FILE):
        return jsonify({})
    try:
        with open(SAVED_QUERIES_FILE, "r") as f:
            return jsonify(json.load(f))
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error reading queries file: {e}")
        return jsonify({})


@app.route("/api/queries", methods=["POST"])
def save_query_route():
    data = request.json
    if not data or "name" not in data or "payload" not in data:
        return jsonify({"error": "Missing name or payload"}), 400
        
    name = data["name"]
    current = {}
    if os.path.exists(SAVED_QUERIES_FILE):
        try:
            with open(SAVED_QUERIES_FILE, "r") as f:
                current = json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Could not read existing queries, starting fresh")
            
    current[name] = data["payload"]
    try:
        with open(SAVED_QUERIES_FILE, "w") as f:
            json.dump(current, f, indent=2)
        return jsonify({"status": "saved"})
    except IOError as e:
        logger.error(f"Failed to save query: {e}")
        return jsonify({"error": "Failed to save query"}), 500


@app.route("/api/queries/<name>", methods=["DELETE"])
def delete_query(name):
    if os.path.exists(SAVED_QUERIES_FILE):
        try:
            with open(SAVED_QUERIES_FILE, "r") as f:
                data = json.load(f)
            if name in data:
                del data[name]
                with open(SAVED_QUERIES_FILE, "w") as f:
                    json.dump(data, f, indent=2)
            return jsonify({"status": "deleted"})
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error during query deletion: {e}")
            return jsonify({"error": "Failed to delete query"}), 500
    return jsonify({"status": "not found"}), 404


@app.route("/stream")
def stream():
    args = request.args
    subs_list = [
        s.strip() for s in args.get("subreddits", "").split(",") if s.strip()
    ] or ["ArtificialInteligence"]
    engine = RedditSearchEngine(
        provider=args.get("provider", "mistral"), debug=args.get("debug") == "true"
    )

    def generate():
        def send(msg):
            return f"data: {msg}\n\n"

        gen = engine.search(
            keywords=args.get("keywords", ""),
            criteria=args.get("criteria", ""),
            subreddits=subs_list,
            target_posts=int(args.get("target_posts", 10)),
            ai_chunk_size=int(args.get("ai_chunk", 5)),
            is_deep_scan=args.get("deep_scan") == "true",
            manual_limit=int(args.get("scan_limit", 100)),
            sort_by=args.get("sort", "new"),
            time_filter=args.get("time", "all"),
            post_type=args.get("post_type", "any"),
        )
        final_posts = []
        try:
            while True:
                yield send(next(gen))
        except StopIteration as e:
            final_posts = e.value

        # Send HTML formatted results for the frontend
        html_res = ""
        for p in final_posts:
            # Handle both PRAW objects and dictionary format
            if isinstance(p, dict):
                # Dictionary format (with AI criteria)
                title = p.get("title", "")
                sub = p.get("sub", "")
                url = p.get("url", "")
                content = p.get("content", "")
            else:
                # PRAW object format (without AI criteria)
                title = p.title
                sub = p.subreddit.display_name
                url = f"https://www.reddit.com{p.permalink}"
                content = p.selftext

            safe_body = escape(content).replace("\n", "<br>")
            html_res += f"""<div class="card"><h3>{escape(title)}</h3><span class="meta">r/{escape(sub)} | <a href="{url}" target="_blank">Open</a></span><hr style="border-color:#333"><div class="body-text">{safe_body}</div></div>"""

        yield send(f"<<<HTML_RESULT>>>{html_res.replace('\n', '||NEWLINE||')}")

    return Response(generate(), mimetype="text/event-stream")


@app.route("/stream_discovery")
def stream_discovery():
    args = request.args
    engine = RedditSearchEngine(provider=args.get("provider", "mistral"))

    def generate():
        def send(msg):
            return f"data: {msg}\n\n"

        gen = engine.discover_subreddits(
            args.get("keywords", ""),
            int(args.get("limit", 10)),
            args.get("criteria", ""),
        )
        final_subs = []
        try:
            while True:
                yield send(next(gen))
        except StopIteration as e:
            final_subs = e.value
        yield send("✨ Rendering results...")
        for sub in final_subs:
            yield send(f"<<<JSON_CARD>>>{json.dumps(sub)}")
        yield send("<<<DONE>>>")

    return Response(generate(), mimetype="text/event-stream")


def run_cli():
    """
    Main CLI entry point for Reddit Search Engine.
    Supports two modes:
    1. 'search' - Direct Boolean query search
    2. 'curate' - AI-powered search from natural language description
    """
    parser = argparse.ArgumentParser(
        description="Reddit AI Curator - Find high-quality Reddit discussions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search with Boolean query directly
  python app.py search --keywords "(assault OR attacked) AND (pool OR beach)" --subreddits TwoXChromosomes

  # AI-powered search from natural language description
  python app.py curate --description "First-person stories about assault at public pools by strangers"

  # Curate with custom settings
  python app.py curate --description "Detailed stories about workplace discrimination" \\
      --target_posts 15 --subreddits antiwork,AskReddit,TrueOffMyChest \\
      --time year --json
        """,
    )

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Command to execute"
    )

    # =========================================================================
    # SEARCH COMMAND - Direct Boolean query
    # =========================================================================
    search_parser = subparsers.add_parser(
        "search",
        help="Search with a direct Boolean query",
        description="Execute a Reddit search using a pre-defined Boolean query string.",
    )
    search_parser.add_argument(
        "--keywords",
        type=str,
        required=True,
        help="Boolean search string (e.g., '(term1 OR term2) AND term3')",
    )
    search_parser.add_argument(
        "--criteria",
        type=str,
        default="",
        help="AI filtering criteria to score and rank results",
    )
    search_parser.add_argument(
        "--subreddits",
        type=str,
        default=None,
        help="Comma-separated subreddits (default: uses DEFAULT_SUBS_ENV)",
    )
    search_parser.add_argument(
        "--target_posts",
        type=int,
        default=10,
        help="Target number of posts to return (default: 10)",
    )
    search_parser.add_argument(
        "--provider",
        type=str,
        default="mistral",
        choices=["mistral", "gemini"],
        help="LLM provider for AI filtering (default: mistral)",
    )
    search_parser.add_argument(
        "--json", action="store_true", help="Output results as JSON"
    )
    search_parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with verbose output"
    )
    search_parser.add_argument(
        "--sort",
        type=str,
        default="new",
        choices=["new", "relevance", "top", "hot", "comments"],
        help="Sort order (default: new)",
    )
    search_parser.add_argument(
        "--time",
        type=str,
        default="all",
        choices=["all", "day", "hour", "month", "week", "year"],
        help="Time filter (default: all)",
    )
    search_parser.add_argument(
        "--post_type",
        type=str,
        default="any",
        choices=["any", "text", "media"],
        help="Filter by post type (default: any)",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Manual fetch limit - max posts to scan (default: 100)",
    )
    search_parser.add_argument(
        "--ai_chunk",
        type=int,
        default=5,
        help="Batch size for AI analysis (default: 5)",
    )

    # =========================================================================
    # CURATE COMMAND - AI-powered search from description
    # =========================================================================
    curate_parser = subparsers.add_parser(
        "curate",
        help="AI-powered search from natural language description",
        description="Generate a search query from a natural language description and find relevant Reddit posts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
The 'curate' command automatically:
  1. Generates a Boolean search query from your description
  2. Scans Reddit for matching posts
  3. AI-scores results against your description
  4. Returns the highest-quality matching posts
        """,
    )
    curate_parser.add_argument(
        "--description",
        type=str,
        required=True,
        help="Natural language description of posts to find (REQUIRED)",
    )
    curate_parser.add_argument(
        "--target_posts",
        type=int,
        default=10,
        help="Target number of posts to return (default: 10)",
    )
    curate_parser.add_argument(
        "--subreddits",
        type=str,
        default=None,
        help="Comma-separated subreddits (default: uses DEFAULT_SUBS_ENV)",
    )
    curate_parser.add_argument(
        "--provider",
        type=str,
        default="mistral",
        choices=["mistral", "gemini"],
        help="LLM provider for query generation and scoring (default: mistral)",
    )
    curate_parser.add_argument(
        "--json", action="store_true", help="Output results as JSON"
    )
    curate_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode with verbose output (shows generated query)",
    )
    curate_parser.add_argument(
        "--sort",
        type=str,
        default="new",
        choices=["new", "relevance", "top", "hot", "comments"],
        help="Sort order (default: new)",
    )
    curate_parser.add_argument(
        "--time",
        type=str,
        default="all",
        choices=["all", "day", "hour", "month", "week", "year"],
        help="Time filter (default: all)",
    )
    curate_parser.add_argument(
        "--post_type",
        type=str,
        default="any",
        choices=["any", "text", "media"],
        help="Filter by post type (default: any)",
    )
    curate_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Manual fetch limit - max posts to scan (default: 100)",
    )
    curate_parser.add_argument(
        "--ai_chunk",
        type=int,
        default=5,
        help="Batch size for AI analysis (default: 5)",
    )
    curate_parser.add_argument(
        "--no_score",
        action="store_true",
        help="Skip AI scoring - return raw search results (faster, no LLM needed)",
    )

    # =========================================================================
    # DISCOVER COMMAND - Find relevant subreddits
    # =========================================================================
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover relevant subreddits for a topic",
        description="Find subreddits that frequently discuss a given topic.",
    )
    discover_parser.add_argument(
        "--keywords",
        type=str,
        required=True,
        help="Keywords or description to discover subreddits for",
    )
    discover_parser.add_argument(
        "--criteria",
        type=str,
        default="",
        help="AI criteria to filter subreddit relevance",
    )
    discover_parser.add_argument(
        "--limit_subs",
        type=int,
        default=10,
        help="Maximum number of subreddits to return (default: 10)",
    )
    discover_parser.add_argument(
        "--provider",
        type=str,
        default="mistral",
        choices=["mistral", "gemini"],
        help="LLM provider (default: mistral)",
    )
    discover_parser.add_argument(
        "--json", action="store_true", help="Output results as JSON"
    )

    args = parser.parse_args()

    if args.command == "search":
        _run_search_command(args)
    elif args.command == "curate":
        _run_curate_command(args)
    elif args.command == "discover":
        _run_discover_command(args)


def _run_search_command(args):
    """Execute the 'search' command with direct Boolean query."""
    engine = RedditSearchEngine(provider=args.provider, debug=args.debug)

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
        output = [
            {
                "id": p.id,
                "title": p.title,
                "subreddit": p.subreddit.display_name,
                "url": f"https://www.reddit.com{p.permalink}",
                "content": p.selftext,
            }
            for p in final_posts
        ]
        print(json.dumps(output, indent=2))
    else:
        print(f"\nFound {len(final_posts)} approved posts.")


def _run_curate_command(args):
    """
    Execute the 'curate' command - AI-powered search from description.

    This command:
    1. Generates a Boolean search query from the natural language description
    2. Scans Reddit for matching posts
    3. AI-scores results against the original description
    4. Returns the highest-quality matching posts
    """
    print(f"\n{'=' * 60}")
    print(f"🤖 REDDIT AI CURATOR - AUTO-CURATE MODE")
    print(f"{'=' * 60}")
    print(f"\n📝 Description: {args.description}")

    # Step 1: Generate Boolean query from description
    print(f"\n🔧 Step 1/3: Generating search query...")
    llm_filter = LLMFilter(provider=args.provider, debug=args.debug)

    generated_query = llm_filter.generate_boolean_string(args.description)

    if args.debug:
        print(f"   [DEBUG] Generated query: {generated_query}")

    if not generated_query or generated_query.startswith("Error:"):
        print(f"\n❌ Error generating query: {generated_query}")
        return

    print(f"   ✅ Query generated: {generated_query}")

    # Step 2: Search Reddit for matching posts
    print(f"\n🔍 Step 2/3: Scanning Reddit for matching posts...")
    engine = RedditSearchEngine(provider=args.provider, debug=args.debug)

    subs = (
        [s.strip() for s in args.subreddits.split(",")]
        if args.subreddits
        else DEFAULT_SUBS_ENV.split(",")
    )

    print(f"   📂 Scanning {len(subs)} subreddits...")
    if not args.json:
        print(f"   📊 Target: {args.target_posts} posts | Scan limit: {args.limit}")

    if args.no_score:
        # Skip AI scoring - return raw results
        gen = engine.search(
            keywords=generated_query,
            criteria="",  # No criteria = no scoring
            subreddits=subs,
            target_posts=args.target_posts,
            ai_chunk_size=args.ai_chunk,
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
            final_posts = e.value or []
    else:
        # Full AI-powered curation with scoring
        gen = engine.search(
            keywords=generated_query,
            criteria=args.description,  # Use description as scoring criteria
            subreddits=subs,
            target_posts=args.target_posts,
            ai_chunk_size=args.ai_chunk,
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

    # Step 3: Display final results
    if args.json:
        output = [
            {
                "id": p.get("id") or p.id,
                "title": p.get("title") or p.title,
                "subreddit": p.get("sub") or p.subreddit.display_name,
                "url": p.get("url") or f"https://www.reddit.com{p.permalink}",
                "content": p.get("content") or p.selftext,
                "score": p.get("score", "N/A"),
            }
            for p in final_posts
        ]
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'=' * 60}")
        print(f"✅ CURATE COMPLETE")
        print(f"{'=' * 60}")
        print(
            f"\n📊 Found {len(final_posts)} approved posts matching your description."
        )

        if final_posts and not args.no_score:
            print(f"\n🏆 Top Results:")
            print(f"{'-' * 60}")
            for i, p in enumerate(final_posts[:5], 1):
                score = p.get("score", "N/A")
                title = p.get("title", p.title)[:60]
                sub = p.get("sub", p.subreddit.display_name)
                url = p.get("url") or f"https://www.reddit.com{p.permalink}"
                print(f"\n{i}. {title}...")
                print(f"   📌 r/{sub} | Score: {score}")
                print(f"   🔗 {url}")

        print(f"\n💡 Tip: Use --json flag for machine-readable output")


def _run_discover_command(args):
    """Execute the 'discover' command to find relevant subreddits."""
    engine = RedditSearchEngine(provider=args.provider)

    gen = engine.discover_subreddits(
        args.keywords, limit_subs=args.limit_subs, criteria=args.criteria or ""
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
        print(f"\nFound {len(final_results)} relevant subreddits.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_cli()
    else:
        app.run(host="0.0.0.0", port=5000)
