import json
import os
from typing import Dict, List, Tuple


class KEIStore:
    def __init__(self, storage_path: str = "benchmarks/kei_memory.json"):
        self.storage_path = storage_path
        self.memory = self._load_memory()

    def _load_memory(self) -> Dict[str, Dict[str, float]]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def save_memory(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(self.memory, f, indent=2)

    def update_efficacy(self, keyword: str, subreddit: str, score: float):
        if keyword not in self.memory:
            self.memory[keyword] = {}

        if subreddit in self.memory[keyword]:
            old_score = self.memory[keyword][subreddit]
            self.memory[keyword][subreddit] = (old_score + score) / 2
        else:
            self.memory[keyword][subreddit] = score

        self.save_memory()

    def get_efficacy(self, keyword: str, subreddit: str) -> float:
        return self.memory.get(keyword, {}).get(subreddit, 0.0)

    def get_top_keywords(
        self, subreddit: str, limit: int = 10
    ) -> List[Tuple[str, float]]:
        keywords = []
        for kw, subs in self.memory.items():
            if subreddit in subs:
                keywords.append((kw, subs[subreddit]))

        return sorted(keywords, key=lambda x: x[1], reverse=True)[:limit]


class SubredditProfiler:
    def __init__(
        self,
        storage_path: str = "benchmark_module/knowledge_store/subreddit_index.json",
    ):
        self.storage_path = storage_path
        self.index = self._load_index()

    def _load_index(self) -> Dict:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def save_index(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(self.index, f, indent=2)

    def update_profile(self, subreddit: str, metadata: Dict, tags: List[str]):
        self.index[subreddit] = {
            "subscribers": metadata.get("subscribers"),
            "description": metadata.get("description"),
            "tags": tags,
            "last_updated": metadata.get("last_updated"),
        }
        self.save_index()

    def get_profile(self, subreddit: str) -> Dict:
        return self.index.get(subreddit, {})
