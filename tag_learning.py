"""
Tag-Based Learning System for Reddit Curator

This module provides:
1. Tag extraction from high-scoring posts
2. Tag storage and retrieval
3. Query enhancement based on historical successes
"""
import os
import json
import time
from typing import List, Dict, Optional

TAGGED_RESULTS_FILE = "config/tagged_results.json"
MAX_STORED_RESULTS = 500


def load_tagged_results() -> Dict:
    """Load the tagged results database."""
    if os.path.exists(TAGGED_RESULTS_FILE):
        try:
            with open(TAGGED_RESULTS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_tagged_results(data: Dict):
    """Save the tagged results database, enforcing max size."""
    os.makedirs(os.path.dirname(TAGGED_RESULTS_FILE), exist_ok=True)
    
    # Enforce FIFO limit
    if len(data) > MAX_STORED_RESULTS:
        # Sort by timestamp, keep newest
        sorted_items = sorted(data.items(), key=lambda x: x[1].get("timestamp", 0), reverse=True)
        data = dict(sorted_items[:MAX_STORED_RESULTS])
    
    with open(TAGGED_RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def extract_tags_prompt(post: Dict) -> str:
    """Generate prompt for tag extraction."""
    return f"""Analyze this Reddit post and extract 5-10 semantic tags that capture the specific story elements.
Tags should be concrete nouns, actions, or situations (not generic categories).

GOOD tags: "party", "passed out", "sibling", "pretending to sleep", "touched inappropriately"
BAD tags: "assault", "trauma", "story", "post" (too generic)

Post Title: {post.get('title', '')}
Post Content: {post.get('content', '')[:2000]}

Return a JSON object:
{{"tags": ["tag1", "tag2", ...], "effective_terms": ["phrase1", "phrase2", ...]}}

"effective_terms" are specific phrases from the post that seem important for searching similar content.
"""


def find_similar_posts(description: str, tagged_db: Dict, top_k: int = 5) -> List[Dict]:
    """
    Find posts with tags that match the description.
    Uses simple keyword matching for now (could be upgraded to embeddings).
    """
    if not tagged_db:
        return []
    
    description_lower = description.lower()
    desc_words = set(description_lower.split())
    
    scored_posts = []
    for post_id, post_data in tagged_db.items():
        tags = post_data.get("tags", [])
        effective_terms = post_data.get("effective_terms", [])
        
        # Score based on tag overlap
        tag_score = sum(1 for tag in tags if tag.lower() in description_lower)
        term_score = sum(1 for term in effective_terms if term.lower() in description_lower)
        
        # Also check word overlap
        word_score = len(desc_words.intersection(set(t.lower() for t in tags)))
        
        total_score = tag_score * 3 + term_score * 2 + word_score
        
        if total_score > 0:
            scored_posts.append({
                "post_id": post_id,
                "score": total_score,
                "tags": tags,
                "effective_terms": effective_terms,
                "content": post_data.get("content", "")[:1000]
            })
    
    # Sort by score, return top_k
    scored_posts.sort(key=lambda x: x["score"], reverse=True)
    return scored_posts[:top_k]


def analyze_vocabulary(similar_posts: List[Dict]) -> Dict:
    """
    Analyze vocabulary patterns from similar high-scoring posts.
    Returns suggested terms for query generation.
    """
    all_terms = []
    all_tags = []
    
    for post in similar_posts:
        all_terms.extend(post.get("effective_terms", []))
        all_tags.extend(post.get("tags", []))
    
    # Count frequency
    from collections import Counter
    term_counts = Counter(all_terms)
    tag_counts = Counter(all_tags)
    
    return {
        "suggested_terms": [t for t, c in term_counts.most_common(10)],
        "common_tags": [t for t, c in tag_counts.most_common(10)],
        "sample_content": similar_posts[0].get("content", "") if similar_posts else ""
    }


def highlight_keywords(content: str, keywords: List[str]) -> str:
    """
    Wrap matching keywords in <mark> tags for highlighting.
    Case-insensitive matching.
    """
    import re
    
    highlighted = content
    for keyword in keywords:
        if len(keyword) < 3:  # Skip very short words
            continue
        # Escape regex special chars
        escaped = re.escape(keyword)
        pattern = re.compile(f"({escaped})", re.IGNORECASE)
        highlighted = pattern.sub(r'<mark>\1</mark>', highlighted)
    
    return highlighted
