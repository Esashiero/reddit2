import os
import json
import sys
import time
import re
import hashlib
import logging
import argparse
import requests
import praw
import prawcore
import concurrent.futures
import threading
import queue
from typing import List, Dict, Any, Generator, Optional, Tuple, Set
from collections import deque
from functools import lru_cache
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, request, jsonify, Response
from report_generator import _generate_html_report
from tag_learning import (
    load_tagged_results, save_tagged_results, 
    find_similar_posts, analyze_vocabulary, highlight_keywords,
    extract_tags_prompt
)
from markupsafe import escape
from dotenv import load_dotenv, find_dotenv
from mistralai import Mistral

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
SAVED_QUERIES_FILE = "config/saved_queries.json"
SUBREDDITS_FILE = "config/subreddits.json"
BLACKLIST_FILE = "config/blacklist.json"
FAVORITES_FILE = "config/favorites.json"

DEFAULT_SUBS_ENV = os.getenv(
    "REDDIT_SUBREDDITS", "offmychest,sexualassault,TwoXChromosomes,amiwrong,relationship_advice,confessions,india,indiasocial,advice,relationships,lifeadvice,trueoffmychest,self,rapecounseling,vent,questions,familyissues,family"
)
REDDIT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_AGENT = os.getenv("REDDIT_USER_AGENT", "script:flask_app:v12_fixed")
MISTRAL_KEY = os.getenv("MISTRAL_API_KEY", "")
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY", "")


def load_favorites() -> Dict:
    """Load the user favorites database."""
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_favorites(data: Dict):
    """Save the user favorites database."""
    os.makedirs(os.path.dirname(FAVORITES_FILE), exist_ok=True)
    with open(FAVORITES_FILE, "w") as f:
        json.dump(data, f, indent=2)


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
                error_msg = str(e)
                if "429" in error_msg:
                    logger.warning(f"Rate limited by {self.provider}, retrying in {delay}s...")
                    time.sleep(delay)
                    retries -= 1
                    delay *= 2
                elif "<!DOCTYPE" in error_msg or "<html" in error_msg.lower():
                    logger.error(f"LLM Error ({self.provider}): API returned HTML (likely 500/502/503 Server Error).")
                    return []
                else:
                    logger.error(f"LLM Error ({self.provider}): {error_msg}")
                    if self.debug:
                        logger.debug(f"Raw Content: {content}")
                    return []
        return []

    def expand_query(self, original_keywords: str, criteria: str) -> str:
        # Implementation could be expanded, but keeping simple for now
        return original_keywords

    def extract_core_characteristics(self, description: str) -> Optional[Dict[str, List[str]]]:
        """
        Extracts mandatory characteristics from the description that must be preserved.
        Returns a dict of theme groups: {"relationship": ["brother", "sibling"], ...}
        """
        sys_p = (
            "Analyze the following Reddit search description. Identify 2-4 CORE, NON-NEGOTIABLE characteristics or themes. "
            "For each characteristic, provide 2-4 synonyms or related terms that preserve the EXACT same meaning. "
            "These will be used to enforce constraints on Boolean search queries.\n\n"
            "Example Description: 'woman assaulted while sleeping by their brother who pulled their shirt up'\n"
            "Example Output: {\n"
            "  \"core_constraints\": [\n"
            "    {\"theme\": \"sleep state\", \"terms\": [\"sleeping\", \"asleep\", \"passed out\", \"unconscious\"]},\n"
            "    {\"theme\": \"relationship\", \"terms\": [\"brother\", \"sibling\"]},\n"
            "    {\"theme\": \"specific action\", \"terms\": [\"shirt up\", \"pulled shirt\", \"clothing displaced\"]}\n"
            "  ]\n"
            "}\n"
            "Return ONLY a JSON object."
        )
        
        try:
            if self.provider == "mistral" and hasattr(self, "client"):
                res = self.client.chat.complete(
                    model="mistral-large-latest",
                    messages=[
                        {"role": "system", "content": sys_p},
                        {"role": "user", "content": description},
                    ],
                    response_format={"type": "json_object"},
                )
                content = str(res.choices[0].message.content)
            elif hasattr(self, "api_key"):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.api_key}"
                pl = {
                    "contents": [{"parts": [{"text": description}]}],
                    "system_instruction": {"parts": [{"text": sys_p}]},
                    "generationConfig": {"response_mime_type": "application/json"},
                }
                res = requests.post(url, json=pl, headers={"Content-Type": "application/json"})
                content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            else:
                return None

            data = json.loads(content)
            return data
        except Exception as e:
            logger.error(f"Error extracting core characteristics: {e}")
            return None

    def extract_tags(self, post: Dict) -> Optional[Dict]:
        """
        Extract semantic tags from a high-scoring post for the learning system.
        Returns {"tags": [...], "effective_terms": [...]}
        """
        prompt = extract_tags_prompt(post)
        
        try:
            if self.provider == "mistral" and hasattr(self, "client"):
                res = self.client.chat.complete(
                    model="mistral-large-latest",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                content = str(res.choices[0].message.content)
            elif hasattr(self, "api_key"):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
                pl = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"response_mime_type": "application/json"},
                }
                res = requests.post(url, json=pl, headers={"Content-Type": "application/json"})
                content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            else:
                return None

            return json.loads(content)
        except Exception as e:
            logger.warning(f"Tag extraction failed: {e}")
            return None

    def generate_query_variations(self, description: str, num_variations: int = 5, core_constraints: Optional[Dict] = None, vocabulary_context: Optional[Dict] = None) -> List[Dict[str, str]]:
        """
        Generates multiple search query variations for better recall.
        Returns a list of dicts: {"type": "...", "query": "...", "reasoning": "..."}
        """
        constraint_text = ""
        if core_constraints and "core_constraints" in core_constraints:
            constraint_text = "\nCRITICAL CONSTRAINTS - Every query variation MUST include at least one term from EACH of these groups:\n"
            for group in core_constraints["core_constraints"]:
                constraint_text += f"- Theme '{group['theme']}': ({' OR '.join(group['terms'])})\n"

        vocab_text = ""
        if vocabulary_context:
            suggested = vocabulary_context.get("suggested_terms", [])
            if suggested:
                vocab_text = f"\nLEARNED VOCABULARY - These terms have worked well in similar searches: {', '.join(suggested[:8])}\n"

        sys_p = (
            f"You are an expert Reddit Search Engineer. Generate {num_variations} DIFFERENT high-precision Boolean Search Queries.\n\n"
            "AXES OF VARIATION:\n"
            "1. BROAD: Less restrictive, high recall.\n"
            "2. SPECIFIC: High precision, detailed constraints.\n"
            "3. SYNONYM: Alternative vocabulary/slang.\n"
            "4. NARRATIVE: Focus on storytelling markers (e.g., 'happened to me', 'first time').\n"
            "5. JARGON: Niche community terminology.\n\n"
            "REDDIT SYNTAX: (A OR B) AND (C OR D). Max 3 AND groups, Max 3 terms per OR group.\n"
            f"{constraint_text}"
            f"{vocab_text}\n"
            "Return a JSON object with a 'queries' key containing a list of objects with 'type', 'query', and 'reasoning'."
        )
        
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
                            {"role": "user", "content": description},
                        ],
                        response_format={"type": "json_object"},
                    )
                    content = str(res.choices[0].message.content)
                elif hasattr(self, "api_key"):
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.api_key}"
                    pl = {
                        "contents": [{"parts": [{"text": description}]}],
                        "system_instruction": {"parts": [{"text": sys_p}]},
                        "generationConfig": {"response_mime_type": "application/json"},
                    }
                    res = requests.post(url, json=pl, headers={"Content-Type": "application/json"})
                    content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    return []

                try:
                    data = json.loads(content)
                    queries = data.get("queries", [])
                    if not queries:
                        # Fallback for alternative JSON structures
                        if isinstance(data, list):
                            queries = data
                    return queries[:num_variations]
                except json.JSONDecodeError:
                    match = re.search(r"({.*})", content, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        return data.get("queries", [])[:num_variations]
                    raise
            except Exception as e:
                if "429" in str(e):
                    time.sleep(delay)
                    retries -= 1
                    delay *= 2
                else:
                    logger.error(f"Error generating query variations: {e}")
                    if self.debug: logger.debug(f"Raw variations content: {content}")
                    return []
        return []

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

def load_subreddits_config() -> List[str]:
    """Load subreddits from file or fallback to env/defaults."""
    if os.path.exists(SUBREDDITS_FILE):
        try:
            with open(SUBREDDITS_FILE, "r") as f:
                subs = json.load(f)
                if isinstance(subs, list) and subs:
                    return [s.strip() for s in subs if s.strip()]
        except Exception as e:
            logger.warning(f"Error loading subreddits file: {e}")
            
    # Fallback
    return [s.strip() for s in DEFAULT_SUBS_ENV.split(",") if s.strip()]

class ConcurrentSearchPipeline:
    def __init__(self, engine, llm_filter, criteria, target_posts=10, ai_chunk_size=5):
        self.engine = engine
        self.llm = llm_filter
        self.criteria = criteria
        self.target_posts = target_posts
        self.ai_chunk_size = ai_chunk_size
        
        self.found_posts = queue.Queue()
        self.scored_results = []
        self.scored_lock = threading.Lock()
        self.is_running = True
        self.seen_ids = set()
        
        # Load Blacklist into seen_ids to skip already processed content
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f:
                    bl = json.load(f)
                    for pid in bl:
                        self.seen_ids.add(pid)
            except:
                pass
        
        # Stats tracking
        self.stats = {
            "fetched": 0,
            "analyzed": 0,
            "scores": {
                "high": 0,   # >= 80
                "medium": 0, # 60-79
                "low": 0     # < 60
            },
            "per_sub": {} # sub: {"fetched": 0, "approved": 0}
        }
        
    def _search_worker(self, query, subreddits, sort_by, time_filter, post_type, limit=100):
        try:
            # If subreddits is just ["all"] or empty, use the configured default list
            search_subs = subreddits
            if not search_subs or (len(search_subs) == 1 and search_subs[0] == "all"):
                 search_subs = DEFAULT_SEARCH_SUBREDDITS
            
            # Use configured subreddits if we are in a broader mode
            # But the caller usually handles this. Let's just trust the passed subreddits list
            # unless it explicitly asks for 'default' expansion.
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(search_subs), 10)) as executor:
                futures = []
                for sub in search_subs:
                    if not self.is_running: break
                    futures.append(executor.submit(self._search_sub, sub, query, sort_by, time_filter, post_type, limit))
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Thread error in search: {e}")
        finally:
            self.found_posts.put(None) # End of search sentinel

    def _search_sub(self, sub, query, sort_by, time_filter, post_type, limit=100):
        try:
            # Use lowercase for consistent mapping in stats
            sub_key = sub.lower()
            with self.scored_lock:
                if sub_key not in self.stats["per_sub"]:
                    self.stats["per_sub"][sub_key] = {"fetched": 0, "approved": 0}

            # We use a limited window per sub for speed
            search_api = self.engine.reddit.subreddit(sub).search(
                query, sort=sort_by, time_filter=time_filter, limit=limit
            )
            for post in search_api:
                if not self.is_running: break
                
                with self.scored_lock:
                    if post.id in self.seen_ids: continue
                    self.seen_ids.add(post.id)
                
                if (post_type == "text" and not post.is_self) or (post_type == "media" and post.is_self):
                    continue
                
                p_data = {
                    "id": post.id,
                    "title": post.title,
                    "sub": post.subreddit.display_name,
                    "url": f"https://www.reddit.com{post.permalink}",
                    "content": post.selftext,
                    "timestamp": post.created_utc,
                    "upvotes": post.score,
                    "num_comments": post.num_comments
                }
                with self.scored_lock:
                    self.stats["fetched"] += 1
                    self.stats["per_sub"][sub_key]["fetched"] += 1
                
                self.found_posts.put((post, p_data))
                
                # Check early termination based on already scored results
                with self.scored_lock:
                    if len([r for r in self.scored_results if r.get('score', 0) >= 80]) >= self.target_posts:
                        self.is_running = False
                        break
        except Exception as e:
            logger.warning(f"Error scanning r/{sub}: {e}")

    def _process_batch_gen(self, batch):
        posts_to_analyze = [p[1] for p in batch]
        results = self.llm.analyze(posts_to_analyze, self.criteria)
        
        with self.scored_lock:
            pmap = {p[1]['id']: p[1] for p in batch} # Map ID to p_data (dict)
            for r in results:
                post_data = pmap.get(r['id'])
                if post_data:
                    # Merge metadata into result
                    r.update(post_data)
                    
                    # Content Quality Signals
                    bonus = 0
                    if len(r.get('content', '')) > 800: bonus += 7
                    if r.get('upvotes', 0) > 200: bonus += 5
                    if r.get('num_comments', 0) > 20: bonus += 3
                    
                    # 5. Feedback Bias (Learning Feature)
                    bias = self.engine._get_subreddit_bias(r.get('sub', ''))
                    score = min(100, (r.get('score', 0) * bias) + bonus)
                    r['score'] = score
                    
                    # Update stats
                    self.stats["analyzed"] += 1
                    sub_key = r.get('sub', '').lower()
                    if score >= 80:
                        self.stats["scores"]["high"] += 1
                        if sub_key in self.stats["per_sub"]:
                            self.stats["per_sub"][sub_key]["approved"] += 1
                    elif score >= 60:
                        self.stats["scores"]["medium"] += 1
                    else:
                        self.stats["scores"]["low"] += 1
                
                self.scored_results.append(r)
                yield f"<<<POST_SCORED>>>{json.dumps(r)}"
            
            if len([r for r in self.scored_results if r.get('score', 0) >= 80]) >= self.target_posts:
                self.is_running = False

    def run_tournament(self, variations, subreddits, sort_by, time_filter, post_type):
        yield "🏆 Starting Query Tournament (5 competing variations):"
        for i, var in enumerate(variations, 1):
            yield f"   {i}. [{var['type']}] \"{var['query']}\""
        yield ""
        
        performance = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(variations)) as executor:
            future_to_var = {
                executor.submit(self._test_variation, var, subreddits, sort_by, time_filter, post_type): var 
                for var in variations
            }
            for future in concurrent.futures.as_completed(future_to_var):
                var = future_to_var[future]
                try:
                    stats = future.result()
                    # New weighted score
                    v_score = (stats['high_quality'] * 10) + (stats['avg_score'] * 0.5)
                    performance[var['query']] = {**stats, "v_score": v_score, "type": var['type']}
                    yield f"   📊 Variant '{var['type']}': {stats['high_quality']} matches found (avg {stats['avg_score']:.1f}) | Score: {v_score:.1f}"
                except Exception as e:
                    logger.error(f"Tournament error: {e}")
        
        if not performance: return [variations[0]['query']]
        
        # Sort by variant score descending
        sorted_variants = sorted(performance.items(), key=lambda x: x[1]['v_score'], reverse=True)
        winner = sorted_variants[0][0]
        yield f"✅ Tournament Winner: \"{winner}\""
        
        # Return top 3 queries
        return [q for q, s in sorted_variants[:3]]

    def _test_variation(self, var, subreddits, sort_by, time_filter, post_type):
        # Increased sample size: test across 3 subs, up to 50 posts total
        test_subs = subreddits[:3] if "all" not in subreddits else DEFAULT_SEARCH_SUBREDDITS[:3]
        found = []
        for sub in test_subs:
            try:
                # Per-variant sample size increased to 20 per sub (max 60 total)
                for p in self.engine.reddit.subreddit(sub).search(var['query'], sort=sort_by, time_filter=time_filter, limit=20):
                    if (post_type == "text" and not p.is_self) or (post_type == "media" and p.is_self): continue
                    found.append({
                        "id": p.id, 
                        "title": p.title, 
                        "content": p.selftext[:500],
                        "sub": p.subreddit.display_name,
                        "upvotes": p.score,
                        "num_comments": p.num_comments
                    })
                    if len(found) >= 50: break
                if len(found) >= 50: break
            except: continue
        
        if not found: return {"avg_score": 0, "high_quality": 0}
        
        # We need to analyze them via LLMFilter.analyze to get real scores
        results = self.llm.analyze(found, self.criteria)
        
        # Score the variant results using the same logic as real search
        scored = []
        for r in results:
            pmap = {p['id']: p for p in found}
            p_data = pmap.get(r['id'])
            if p_data:
                bonus = 0
                if len(p_data['content']) > 400: bonus += 7
                if p_data['upvotes'] > 200: bonus += 5
                
                bias = self.engine._get_subreddit_bias(p_data['sub'])
                r['score'] = min(100, (r.get('score', 0) * bias) + bonus)
                scored.append(r)

        avg = sum(r.get('score', 0) for r in scored) / len(scored) if scored else 0
        hq = len([r for r in scored if r.get('score', 0) >= 75]) # Slightly lower threshold for tournament
        return {"avg_score": avg, "high_quality": hq}

    def execute(self, query, subreddits, sort_by="new", time_filter="all", post_type="any", limit=100):
        # 0. Show Configuration
        yield f"\n🔍 Search Pass Configuration:"
        yield f"   Query: {query}"
        yield f"   Sort: {sort_by} | Time: {time_filter} | Limit: {limit}/sub"
        
        # Reset running state if we're adding another pass
        self.is_running = True
        
        search_t = threading.Thread(
            target=self._search_worker, 
            args=(query, subreddits, sort_by, time_filter, post_type, limit)
        )
        search_t.start()
        
        batch = []
        while self.is_running or not self.found_posts.empty():
            try:
                item = self.found_posts.get(timeout=0.5)
                if item is None: break
                
                batch.append(item)
                if len(batch) >= self.ai_chunk_size:
                    yield from self._process_batch_gen(batch)
                    batch = []
            except queue.Empty:
                if not self.is_running: break
                continue
            
            # Key Fix: Stop processing queue immediately if target met
            if not self.is_running:
                break
        
        if batch:
            yield from self._process_batch_gen(batch)
            
        self.is_running = False
        search_t.join()
        
        with self.scored_lock:
            final = sorted(self.scored_results, key=lambda x: x.get('score', 0), reverse=True)
            yield f"✅ Pass Complete. Total candidates analyzed: {self.stats['analyzed']} ({self.stats['scores']['high']} high-quality)"
            return final


class RedditSearchEngine:
    def __init__(self, provider: str = "mistral", debug: bool = False):
        self.provider = provider
        self.debug = debug
        self.reddit = praw.Reddit(
            client_id=REDDIT_ID, client_secret=REDDIT_SECRET, user_agent=REDDIT_AGENT
        )
        self.llm = LLMFilter(provider, debug=debug)

    def _get_subreddit_bias(self, sub: str) -> float:
        """Calculate score multiplier based on historical feedback."""
        try:
            fb_file = "feedback.json"
            if not os.path.exists(fb_file): return 1.0
            with open(fb_file, "r") as f:
                data = json.load(f)
            if sub not in data: return 1.0
            pos = data[sub].get("positive", 0)
            neg = data[sub].get("negative", 0)
            total = pos + neg
            if total == 0: return 1.0
            ratio = (pos - neg) / total
            return 1.0 + (ratio * 0.25) # Max +25% boost, -25% penalty
        except Exception: return 1.0

    def _log_feedback(self, sub: str, feedback_type: str):
        """Persist user feedback for a subreddit."""
        try:
            fb_file = "feedback.json"
            fb_data = {}
            if os.path.exists(fb_file):
                with open(fb_file, "r") as f:
                    fb_data = json.load(f)
            if sub not in fb_data:
                fb_data[sub] = {"positive": 0, "negative": 0}
            fb_data[sub][feedback_type] = fb_data[sub].get(feedback_type, 0) + 1
            with open(fb_file, "w") as f:
                json.dump(fb_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error logging feedback: {e}")

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
        use_tournament: bool = False,
        exhaustive: bool = False,
        no_fallback: bool = False
    ) -> Generator[str, None, List]:
        """
        Orchestrates parallel search and scoring.
        """
        start_time = time.time()
        
        # 0. Initial Status
        yield f"🚀 Concurrent Pipeline Activated\n🔎 Initial Query: {keywords}\n🎯 Target: {target_posts} posts"
        
        pipeline = ConcurrentSearchPipeline(self, self.llm, criteria or keywords, target_posts, ai_chunk_size)
        
        # 1. Multi-Query Tournament
        top_queries = [keywords]
        if use_tournament and criteria:
            yield "🎯 Analyzing description for core characteristics..."
            core_constraints = self.llm.extract_core_characteristics(criteria)
            
            if core_constraints and "core_constraints" in core_constraints:
                themes = [c["theme"] for c in core_constraints["core_constraints"]]
                yield f"   🔒 Identified Mandatory constraints: {', '.join(themes)}"
            
            # Learning System: Check for similar past successes
            vocabulary_context = None
            tagged_db = load_tagged_results()
            favorites_db = load_favorites()
            
            # Combine tagged historical successes and favorites for better learning
            training_data = {**tagged_db, **favorites_db}
            
            if training_data:
                similar = find_similar_posts(criteria, training_data, top_k=8)
                if similar:
                    vocabulary_context = analyze_vocabulary(similar)
                    yield f"   📚 Learning from {len(similar)} similar results/favorites..."
                    
                    # Also influence the criteria for better scoring later
                    if vocabulary_context and vocabulary_context['suggested_terms']:
                        criteria = f"{criteria}\n(Preferred context: {', '.join(vocabulary_context['suggested_terms'])})"
            
            variations = self.llm.generate_query_variations(
                criteria, 
                num_variations=5, 
                core_constraints=core_constraints,
                vocabulary_context=vocabulary_context
            )
            if variations:
                gen = pipeline.run_tournament(variations, subreddits, sort_by, time_filter, post_type)
                try:
                    while True:
                        yield next(gen)
                except StopIteration as e:
                    top_queries = e.value or [keywords]
            else:
                yield "⚠️ Variation generation failed, falling back to original keywords."
        
        # 2. Tiered Search Cascade
        final_posts = []
        current_threshold = 80
        
        # Helper check for quota
        def quota_met():
            if exhaustive: return False
            return len([p for p in final_posts if p.get('score', 0) >= current_threshold]) >= target_posts

        # List of sorts to try in order
        sort_cascade = [sort_by]
        if not no_fallback:
            additional_sorts = ["relevance", "top", "hot", "comments"]
            sort_cascade.extend([s for s in additional_sorts if s != sort_by])

        # Tier 1 & 2: Tournament Queries + Sorts
        for q_idx, query in enumerate(top_queries):
            if quota_met(): break
            
            for s_idx, current_sort in enumerate(sort_cascade):
                if quota_met(): break
                
                # In Tier 1 (Winner), try all sorts. In Tier 2, maybe just top 1-2 sorts unless exhaustive
                if q_idx > 0 and s_idx > 1 and not exhaustive: break
                
                label = "Primary" if q_idx == 0 else f"Secondary #{q_idx}"
                yield f"\n📡 Starting {label} Search Pass (sort={current_sort})..."
                
                limit = 500 if exhaustive else manual_limit
                gen = pipeline.execute(query, subreddits, current_sort, time_filter, post_type, limit=limit)
                
                try:
                    while True:
                        yield next(gen)
                except StopIteration as e:
                    # Pipeline already has all results in pipeline.scored_results
                    final_posts = pipeline.scored_results

        # Tier 3: Expanded Parameters (if still needed)
        if not quota_met() and not no_fallback:
            yield f"\n🔄 Quota not met ({len([p for p in final_posts if p.get('score', 0) >= 80])}/{target_posts}). Attempting Tier 3 (Expanded Parameters)..."
            # Try winner query with 'all' time and higher limit
            gen = pipeline.execute(top_queries[0], subreddits, "top", "all", post_type, limit=500)
            try:
                while True:
                    yield next(gen)
            except StopIteration as e:
                final_posts = pipeline.scored_results

        # Tier 4: Adaptive Scoring (Threshold lowering)
        if not quota_met() and not no_fallback:
            yield f"\n⚠️ Quota still not met. Attempting Tier 4 (Adaptive Scoring)..."
            for threshold in [70, 60]:
                current_threshold = threshold
                yield f"   📉 Relaxing quality threshold to ≥{threshold}..."
                if quota_met():
                    yield f"   ✅ Quota met with threshold {threshold}."
                    break

        # Final Cleanup & Stats
        pipeline.is_running = False
            
        # 4. Metrics Logging (Learning features)
        duration = time.time() - start_time
        overall_query = top_queries[0] if top_queries else keywords
        self._log_search_metrics(overall_query, criteria or keywords, subreddits, len(final_posts), duration)
        
        # Show Detailed Stats
        yield "\n📊 Search Statistics:"
        yield f"   - Posts fetched from Reddit: {pipeline.stats['fetched']}"
        yield f"   - Posts analyzed by LLM: {pipeline.stats['analyzed']}"
        yield f"   - Distribution: {pipeline.stats['scores']['high']} High, {pipeline.stats['scores']['medium']} Medium, {pipeline.stats['scores']['low']} Low"
        
        # 5. Tag Extraction & Enrichment for Learning System
        if final_posts:
            tagged_db = load_tagged_results()
            
            # First, enrich all posts with tags if they exist in DB
            for p in final_posts:
                if p['id'] in tagged_db:
                    p['tags'] = tagged_db[p['id']].get('tags', [])

            # Then, extract new tags for high-scorers not yet in DB
            high_scorers_to_extract = [p for p in final_posts if p.get('score', 0) >= 80 and p['id'] not in tagged_db]
            
            if high_scorers_to_extract:
                yield f"🏷️ Extracting tags from {len(high_scorers_to_extract[:3])} new high-scoring posts..."
                for post in high_scorers_to_extract[:3]:
                    tags = self.llm.extract_tags(post)
                    if tags:
                        post['tags'] = tags.get('tags', [])
                        tagged_db[post['id']] = {
                            "title": post.get('title', ''),
                            "content": post.get('content', '')[:2000],
                            "score": post.get('score', 0),
                            "original_query": overall_query,
                            "tags": post['tags'],
                            "effective_terms": tags.get('effective_terms', []),
                            "timestamp": post.get('timestamp') or time.time()
                        }
                save_tagged_results(tagged_db)
                yield f"   ✅ Learning complete."
        
        # 6. Blacklist high-scorers (>85) to avoid processing them in next runs
        high_scorers_to_bl = [p for p in final_posts if p.get('score', 0) >= 85]
        if high_scorers_to_bl:
            self.save_to_blacklist(high_scorers_to_bl, overall_query, criteria or keywords)
            yield f"   🔒 {len(high_scorers_to_bl)} posts added to blacklist (already processed)."

        # Final sorting by score descending
        if final_posts:
            final_posts = sorted(final_posts, key=lambda x: x.get('score', 0), reverse=True)
            
        yield "<<<DONE>>>"
        return final_posts

    def _log_search_metrics(self, keywords, criteria, subreddits, count, duration):
        try:
            entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "query": keywords,
                "criteria": criteria,
                "subs_count": len(subreddits),
                "subs": subreddits[:10],
                "result_count": count,
                "duration_sec": round(duration, 2)
            }
            log_file = "search_log.json"
            data = []
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    try: data = json.load(f)
                    except: pass
            data.append(entry)
            with open(log_file, "w") as f:
                json.dump(data[-50:], f, indent=2)
        except Exception as e:
            logger.error(f"Metric logging error: {e}")

    def save_to_blacklist(self, posts: List, keywords: str, criteria: str):
        current_bl = {}
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, "r") as f:
                    current_bl = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load blacklist file: {e}")

        for p in posts:
            pid = p.get('id') if isinstance(p, dict) else p.id
            title = p.get('title') if isinstance(p, dict) else p.title
            url = p.get('url') if isinstance(p, dict) else f"https://www.reddit.com{p.permalink}"
            
            current_bl[pid] = {
                "id": pid,
                "title": title,
                "url": url,
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


@app.route("/api/favorites", methods=["GET"])
def get_favorites_api():
    return jsonify(load_favorites())


@app.route("/api/favorites", methods=["POST"])
def add_favorite_api():
    post = request.json
    if not post or 'id' not in post:
        return jsonify({"error": "Invalid post data"}), 400
    
    favs = load_favorites()
    favs[post['id']] = post
    save_favorites(favs)
    return jsonify({"status": "favorited"})


@app.route("/api/favorites/<post_id>", methods=["DELETE"])
def remove_favorite_api(post_id):
    favs = load_favorites()
    if post_id in favs:
        del favs[post_id]
        save_favorites(favs)
        return jsonify({"status": "removed"})
    return jsonify({"error": "Not found"}), 404


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
            use_tournament=args.get("tournament") == "true",
            exhaustive=args.get("exhaustive") == "true",
            no_fallback=args.get("no_fallback") == "true"
        )
        final_posts = []
        it = iter(gen)
        while True:
            try:
                msg = next(it)
                if msg.startswith("<<<POST_SCORED>>>"):
                    try:
                        data = json.loads(msg.replace("<<<POST_SCORED>>>", ""))
                        clean_msg = f"   ⭐ [{data.get('score', 0):.1f}] r/{data.get('sub')}: {data.get('title', '')[:40]}..."
                        yield send(clean_msg)
                    except: pass
                elif msg.startswith("<<<"): 
                    pass # hide other protocol messages
                else:
                    yield send(msg)
            except StopIteration as e:
                final_posts = e.value
                break

        if final_posts:
             # Save to results/ folder if running from web too
            os.makedirs("results", exist_ok=True)
            # Use timestamp + query/criteria for filename
            q_safe = "".join(c for c in (args.get("criteria") or args.get("keywords") or "results") if c.isalnum() or c in (' ', '_'))[:50].strip().replace(" ", "_")
            filename = f"results/{time.strftime('%Y%m%d_%H%M%S')}_{q_safe}.html"
            _generate_html_report(final_posts, q_safe, filename)
            yield send(f"💾 Saved report: {filename}")

        # Send HTML formatted results/JSON for the frontend to render the list
        yield send(f"<<<APPROVED_POSTS>>>{json.dumps(final_posts)}")

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


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.json
    if not data or "subreddit" not in data or "type" not in data:
        return jsonify({"error": "Missing subreddit or type"}), 400
    
    sub = data["subreddit"]
    fb_type = data["type"] # "positive" or "negative"
    if fb_type not in ["positive", "negative"]:
        return jsonify({"error": "Invalid feedback type"}), 400
        
    engine = RedditSearchEngine()
    engine._log_feedback(sub, fb_type)
    return jsonify({"status": "success"})


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
    search_parser.add_argument(
        "--tournament",
        action="store_true",
        help="Enable Query Tournament to test multiple variations (default: False)",
    )
    search_parser.add_argument(
        "--exhaustive",
        action="store_true",
        help="Try all sort methods and variants for maximum recall (slower)",
    )
    search_parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable automatic fallback cascade if quota not met",
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
        "--exhaustive",
        action="store_true",
        help="Try all sort methods and variants for maximum recall (slower)",
    )
    curate_parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable automatic fallback cascade if quota not met",
    )
    curate_parser.add_argument(
        "--no_score",
        action="store_true",
        help="Skip AI scoring - return raw search results (faster, no LLM needed)",
    )
    curate_parser.add_argument(
        "--tournament",
        action="store_true",
        default=True,
        help="Enable Query Tournament to test multiple variations (default: True for curate)",
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
        use_tournament=args.tournament,
        exhaustive=args.exhaustive,
        no_fallback=args.no_fallback
    )
    final_posts = []
    it = iter(gen)
    while True:
        try:
            msg = next(it)
            if not args.json:
                print(msg)
        except StopIteration as e:
            final_posts = e.value
            break

    if final_posts:
        # Save results to file
        os.makedirs("results", exist_ok=True)
        sanitized_q = "".join(c for c in args.keywords if c.isalnum() or c in (' ', '_'))[:50].strip().replace(" ", "_")
        filename_json = f"results/{time.strftime('%Y%m%d_%H%M%S')}_{sanitized_q}.json"
        filename_html = f"results/{time.strftime('%Y%m%d_%H%M%S')}_{sanitized_q}.html"
        
        output_data = [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "subreddit": p.get("sub"),
                "url": p.get("url"),
                "content": p.get("content"),
                "score": p.get("score"),
            }
            for p in final_posts
        ]
        
        with open(filename_json, "w") as f:
            json.dump(output_data, f, indent=2)
        
        # Extract terms from query for highlighting
        import re
        highlight_terms = re.findall(r'"([^"]+)"|([a-zA-Z]+)', args.keywords)
        highlight_terms = [t[0] or t[1] for t in highlight_terms if t[0] or t[1]]
        highlight_terms = [t for t in highlight_terms if t.upper() not in ('AND', 'OR', 'NOT')]
            
        _generate_html_report(final_posts, args.keywords, filename_html, highlight_terms=highlight_terms)
            
        print(f"\n💾 Results saved to:")
        print(f"   - JSON: {filename_json}")
        print(f"   - HTML: {filename_html}")

    if args.json:
        output = [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "subreddit": p.get("sub"),
                "url": p.get("url"),
                "content": p.get("content"),
                "score": p.get("score"),
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

    if args.subreddits:
        subs = [s.strip() for s in args.subreddits.split(",")]
    else:
        subs = load_subreddits_config()

    print(f"   📂 Scanning {len(subs)} subreddits: {', '.join(subs[:5])}{'...' if len(subs)>5 else ''}")
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
            use_tournament=False, # Tournament doesn't make sense without criteria
            exhaustive=args.exhaustive,
            no_fallback=args.no_fallback
        )
        final_posts = []
        it = iter(gen)
        while True:
            try:
                msg = next(it)
                if not args.json:
                    print(msg)
            except StopIteration as e:
                final_posts = e.value or []
                break
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
            use_tournament=args.tournament,
            exhaustive=args.exhaustive,
            no_fallback=args.no_fallback
        )
        final_posts = []
        it = iter(gen)
        while True:
            try:
                msg = next(it)
                if not args.json:
                    if msg.startswith("<<<POST_SCORED>>>"):
                        try:
                            # Parse structured log and print pretty summary
                            data = json.loads(msg.replace("<<<POST_SCORED>>>", ""))
                            score = data.get("score", 0)
                            title = data.get("title", "")[:60]
                            sub = data.get("sub", "")
                            print(f"   ⭐ [{score:.1f}] r/{sub}: {title}...")
                        except: pass
                    elif msg.startswith("<<<"): 
                        pass # Ignore other protocol messages
                    else:
                        print(msg)
            except StopIteration as e:
                final_posts = e.value
                break

    # Step 3: Display final results
    if final_posts:
        # Save results to file
        os.makedirs("results", exist_ok=True)
        sanitized_desc = "".join(c for c in args.description if c.isalnum() or c in (' ', '_'))[:50].strip().replace(" ", "_")
        filename_json = f"results/{time.strftime('%Y%m%d_%H%M%S')}_{sanitized_desc}.json"
        filename_html = f"results/{time.strftime('%Y%m%d_%H%M%S')}_{sanitized_desc}.html"
        
        output_data = [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "subreddit": p.get("sub"),
                "url": p.get("url"),
                "content": p.get("content"),
                "score": p.get("score", "N/A"),
            }
            for p in final_posts
        ]
        
        with open(filename_json, "w") as f:
            json.dump(output_data, f, indent=2)
        
        # Extract terms from description for highlighting
        import re
        highlight_terms = args.description.split()
        highlight_terms = [t.strip('.,!?()') for t in highlight_terms if len(t) > 3]
        # Also add key terms from the generated query if available
        if hasattr(args, '_generated_query'):
            q_terms = re.findall(r'"([^"]+)"|([a-zA-Z]+)', args._generated_query)
            highlight_terms.extend([t[0] or t[1] for t in q_terms if t[0] or t[1]])
        highlight_terms = list(set([t for t in highlight_terms if t.upper() not in ('AND', 'OR', 'NOT', 'THE', 'WAS', 'WHO', 'WHILE')]))
            
        _generate_html_report(final_posts, args.description, filename_html, highlight_terms=highlight_terms)
            
        print(f"\n💾 Results saved to:")
        print(f"   - JSON: {filename_json}")
        print(f"   - HTML: {filename_html}")

    if args.json:
        output = [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "subreddit": p.get("sub"),
                "url": p.get("url"),
                "content": p.get("content"),
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
                title = p.get("title", "")[:60]
                sub = p.get("sub", "")
                url = p.get("url", "")
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
