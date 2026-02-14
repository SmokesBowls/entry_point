import json
import re
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, List, Set, Any

class GraphEngine:
    def __init__(self, repo_root: Path, phase_one_data: List[Dict[str, Any]], relational_data: List[tuple] = None):
        self.repo_root = repo_root
        self.phase_one = phase_one_data
        self.relational_data = relational_data or []
        self.graph = {"nodes": [], "edges": []}
        self.root_clusters = defaultdict(list)

    def build_graph(self) -> Dict[str, Any]:
        """Convert Phase One evidence and relational tuples into a directed dependency graph."""
        all_files = [item["file"] for item in self.phase_one]
        
        # Add nodes
        for file in all_files:
            self.graph["nodes"].append({
                "id": file,
                "type": self._get_file_type(file)
            })

        # Process Relational Data (High Fidelity Edges)
        for r_data in self.relational_data:
            if len(r_data) == 5:
                caller, line, symbol, callee, count = r_data
            else:
                caller, callee, count = r_data
                line, symbol = 0, "unknown"

            if caller == "unknown": continue
            
            # If callee is internal, add a direct edge
            if not callee.startswith("ext:") and not callee.startswith("INTENDED_"):
                self._add_edge(caller, callee, "runtime_import", {
                    "hits": count,
                    "line": line,
                    "symbol": symbol
                })

        return self.graph

    def _add_edge(self, source: str, target: str, edge_type: str, metadata: Dict[str, Any] = None):
        if source == target: return
        # Prevent duplicates, but update hits and store evidence
        for edge in self.graph["edges"]:
            if edge["from"] == source and edge["to"] == target:
                if metadata:
                    edge["hits"] = edge.get("hits", 0) + metadata.get("hits", 1)
                    if "calls" not in edge: edge["calls"] = []
                    edge["calls"].append({
                        "line": metadata.get("line"),
                        "symbol": metadata.get("symbol"),
                        "hits": metadata.get("hits")
                    })
                return

        metadata = metadata or {}
        self.graph["edges"].append({
            "from": source,
            "to": target,
            "type": edge_type,
            "hits": metadata.get("hits", 1),
            "calls": [{
                "line": metadata.get("line"),
                "symbol": metadata.get("symbol"),
                "hits": metadata.get("hits")
            }]
        })

    def classify_roots(self) -> Dict[str, List[str]]:
        """Categorize execution entrypoints into clusters."""
        entrypoints = self._find_entrypoints()
        for ep in entrypoints:
            rel_path = str(ep.relative_to(self.repo_root))
            content = ""
            try:
                content = ep.read_text()
            except:
                pass
            
            if "test" in rel_path.lower():
                self.root_clusters["tests"].append(rel_path)
            elif "main" in content or "if __name__ == '__main__':" in content:
                self.root_clusters["production"].append(rel_path)
            else:
                self.root_clusters["cli_tools"].append(rel_path)
        
        return dict(self.root_clusters)

    def get_transitive_closure(self, roots: List[str]) -> Set[str]:
        """Compute the set of all files reachable from the given roots."""
        closure = set(roots)
        queue = deque(roots)
        
        # Build adjacency list for efficient traversal
        adj = defaultdict(list)
        for edge in self.graph["edges"]:
            adj[edge["from"]].append(edge["to"])
            
        while queue:
            current = queue.popleft()
            for neighbor in adj.get(current, []):
                if neighbor not in closure:
                    closure.add(neighbor)
                    queue.append(neighbor)
        
        return closure

    def _find_entrypoints(self) -> List[Path]:
        # Reuse logic from entrypoint_detector if available, or simplified here
        patterns = ["main.py", "app.py", "server.py", "run.py", "__main__.py", "index.js"]
        found = []
        for p in self.repo_root.rglob("*"):
            if p.name in patterns or (p.suffix == ".py" and "if __name__ == '__main__':" in (p.read_text() if p.is_file() else "")):
                found.append(p)
        return found

    def _get_file_type(self, path_str: str) -> str:
        ext = Path(path_str).suffix
        types = {
            ".py": "python",
            ".js": "javascript",
            ".gd": "gdscript",
            ".tscn": "godot_scene"
        }
        return types.get(ext, "other")

if __name__ == "__main__":
    import sys
    # Example usage (test)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    # Dummy data for test
    dummy_data = [{"file": "main.py", "evidence": ["runtime_trace"], "status": "ACTIVE"}]
    engine = GraphEngine(root, dummy_data)
    print(engine.build_graph())
    print(engine.classify_roots())
