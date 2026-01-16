import json
import os
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import uuid

@dataclass
class BenchmarkRun:
    run_id: str
    timestamp: float
    description: str
    variations: List[Dict]
    analysis: Optional[str] = None

class BenchmarkStorage:
    def __init__(self, base_dir: str = "benchmarks"):
        self.base_dir = base_dir
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

    def save_run(self, run: BenchmarkRun) -> str:
        """Save a benchmark run to disk."""
        # Create a directory for this specific run for easier organization
        run_date = time.strftime("%Y%m%d_%H%M%S", time.localtime(run.timestamp))
        run_dir = os.path.join(self.base_dir, f"run_{run_date}_{run.run_id[:8]}")
        
        if not os.path.exists(run_dir):
            os.makedirs(run_dir)

        file_path = os.path.join(run_dir, "results.json")
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(asdict(run), f, indent=2)
            
        return run_dir

    def load_run(self, run_dir_name: str) -> Optional[BenchmarkRun]:
        """Load a benchmark run from a directory name."""
        file_path = os.path.join(self.base_dir, run_dir_name, "results.json")
        if not os.path.exists(file_path):
            return None
            
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return BenchmarkRun(**data)

    def list_runs(self) -> List[str]:
        """List all available benchmark runs."""
        if not os.path.exists(self.base_dir):
            return []
        
        runs = [
            d for d in os.listdir(self.base_dir) 
            if os.path.isdir(os.path.join(self.base_dir, d)) and d.startswith("run_")
        ]
        return sorted(runs, reverse=True)
