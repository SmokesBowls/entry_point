import fnmatch
from pathlib import Path
from typing import Dict, List, Any, Set, Optional

class ScopeResolver:
    CONVENTIONS = {
        "tests": (["**/tests/**", "**/test/**", "**/*_test.py", "**/test_*.py"], 1.0),
        "tools": (["**/tools/**", "**/scripts/**", "**/bin/**", "**/cli/**"], 0.95),
        "archive": (["**/archive/**", "**/legacy/**", "**/old/**"], 0.98),
        "vendor": (["**/vendor/**", "**/third_party/**", "**/node_modules/**", "**/.venv/**"], 1.0),
        "docs": (["**/docs/**", "**/examples/**", "**/demo/**"], 0.9)
    }

    def __init__(self, repo_root: Path, file_indices: List[Dict[str, Any]], graph: Dict[str, Any]):
        self.repo_root = repo_root
        self.file_indices = file_indices
        self.graph = graph
        self.folder_metrics = {} # folder_path -> {metrics}

    def infer_scopes(self) -> Dict[str, Any]:
        """Resolves the primary engine scope(s) and tool domains."""
        # 1. Label by convention
        conventions = self._apply_conventions()
        
        # 2. Score non-excluded folders
        scores = {}
        candidate_folders = self._get_candidate_folders(conventions)
        
        for folder in candidate_folders:
            metrics = self._calculate_metrics(folder)
            scores[folder] = self._calculate_confidence(metrics)
            
        # 3. Resolve Final Scopes
        engine_scopes = [f for f, s in scores.items() if s > 0.75]
        
        # If none hit 0.75, take the best one if it's high enough, else fallback to root
        if not engine_scopes and scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0.4:
                engine_scopes = [best]
        
        if not engine_scopes:
            engine_scopes = ["."] # Fallback to global
            
        return {
            "engine_scopes": engine_scopes,
            "folder_scores": scores,
            "conventions": conventions
        }

    def _apply_conventions(self) -> Dict[str, str]:
        labels = {}
        for item in self.file_indices:
            path = item["file"]
            for label, (patterns, confidence) in self.CONVENTIONS.items():
                if any(fnmatch.fnmatch(path, p) for p in patterns):
                    labels[path] = label
                    break
        return labels

    def _get_candidate_folders(self, conventions: Dict[str, str]) -> List[str]:
        folders = {"."}
        for item in self.file_indices:
            path = item["file"]
            if path in conventions:
                continue
            
            p = Path(path)
            # We care about top-level and mid-level modules
            for parent in p.parents:
                rel_parent = str(parent)
                if rel_parent == "." or rel_parent == "": continue
                folders.add(rel_parent)
        return sorted(list(folders))

    def _calculate_metrics(self, folder_path: str) -> Dict[str, float]:
        # Filter files belonging to this folder tree
        prefix = folder_path + "/" if folder_path != "." else ""
        folder_files = [item for item in self.file_indices if item["file"].startswith(prefix)]
        
        if not folder_files:
            return {"runtime_hits": 0, "inbound_imports": 0, "tool_signature": 0, "test_touch_ratio": 0}

        # Metric A: Runtime Trace Hits
        hits = sum(1 for f in folder_files if "runtime_trace" in f.get("evidence", []))
        
        # Metric B: Inbound Imports (unique files outside this folder importing into it)
        inbound_set = set()
        for edge in self.graph.get("edges", []):
            if edge["to"].startswith(prefix) and not edge["from"].startswith(prefix):
                inbound_set.add(edge["from"])
        
        # Metric C: Tool Signature (fraction of entrypoints tagged tooling_cli)
        # Note: we might not have all tagging yet, so we look for 'cli' or 'main' entrypoints
        # For now, approximate with file names
        entry_files = [f for f in folder_files if f["file"].endswith((".py", ".js"))] # simplified
        tool_count = sum(1 for f in entry_files if any(x in f["file"].lower() for x in ["cli", "tool", "manage"]))
        tool_sig = tool_count / len(entry_files) if entry_files else 0
        
        # Metric D: Test Touch Ratio (fraction of imports coming from tests)
        total_imports = sum(1 for edge in self.graph.get("edges", []) if edge["to"].startswith(prefix))
        test_imports = sum(1 for edge in self.graph.get("edges", []) if edge["to"].startswith(prefix) and ("test" in edge["from"].lower()))
        test_ratio = test_imports / total_imports if total_imports else 0
        
        return {
            "runtime_hits": hits,
            "inbound_imports": len(inbound_set),
            "tool_signature": tool_sig,
            "test_touch_ratio": test_ratio,
            "file_count": len(folder_files)
        }

    def _calculate_confidence(self, metrics: Dict[str, float]) -> float:
        # Weighted sum
        # runtime_hits (+4), inbound_imports (+3), tool_signature (-2), test_touch_ratio (-1)
        # We need to normalize runtime_hits and inbound_imports relative to file count or just use caps
        
        h_score = min(1.0, metrics["runtime_hits"] / 5.0) * 4
        i_score = min(1.0, metrics["inbound_imports"] / 3.0) * 3
        t_score = metrics["tool_signature"] * -2
        r_score = metrics["test_touch_ratio"] * -1
        
        raw = h_score + i_score + t_score + r_score
        # Map roughly from [-3, 7] to [0, 1]
        normalized = (raw + 3) / 10
        return max(0.0, min(1.0, normalized))
