import json
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, List, Set, Any

class CartographyEngine:
    def __init__(self, repo_root: Path, file_indices: List[Dict[str, Any]], graph: Dict[str, Any]):
        self.repo_root = repo_root
        self.file_indices = file_indices
        self.graph = graph
        self.folders = {}
        self.domains = {}

    def aggregate_folders(self) -> Dict[str, Any]:
        """Compute per-folder health and metrics."""
        folder_stats = defaultdict(lambda: {
            "total_files": 0,
            "active_files": 0,
            "legacy_files": 0,
            "runtime_files": 0,
            "static_files": 0,
            "reference_files": 0,
            "score_sum": 0,
            "health": "unknown"
        })

        for item in self.file_indices:
            file_path = Path(item["file"])
            confidence = item["confidence"]
            evidence = item["evidence"]
            domain = item.get("domain", "unknown")
            
            # Use confidence to simulate a score for weighting
            score = {"HIGH": 5, "MED": 3, "LOW-MED": 1, "LOW": 0}.get(confidence, 0)

            # Generate folder hierarchy at all levels
            for depth in range(1, len(file_path.parts)):
                folder = "/".join(file_path.parts[:depth])
                
                stats = folder_stats[folder]
                stats["total_files"] += 1
                stats["score_sum"] += score
                stats["domain"] = domain # Note: Last file's domain might overwrite, but usually folders are in one domain
                
                if item["status"] == "ACTIVE":
                    stats["active_files"] += 1
                else:
                    stats["legacy_files"] += 1
                
                if "runtime_trace" in evidence: stats["runtime_files"] += 1
                if "static_import" in evidence: stats["static_files"] += 1
                if "text_reference" in evidence: stats["reference_files"] += 1

        # Calculate final health and averages
        for folder, stats in folder_stats.items():
            if stats["total_files"] == 0: continue
            
            stats["active_ratio"] = round(stats["active_files"] / stats["total_files"], 2)
            stats["score_avg"] = round(stats["score_sum"] / stats["total_files"], 1)
            
            # Heuristic health detection
            if stats["runtime_files"] > 0:
                stats["health"] = "core_runtime"
            elif stats["active_ratio"] > 0.7:
                stats["health"] = "active"
            elif stats["active_ratio"] > 0.3:
                stats["health"] = "mixed"
            elif stats["legacy_files"] == stats["total_files"]:
                stats["health"] = "full_removal_candidate"
            else:
                stats["health"] = "partial_prune_candidate"

            # Remove sum for final output
            del stats["score_sum"]

        self.folders = dict(sorted(folder_stats.items()))
        return self.folders

    def detect_domains(self) -> Dict[str, List[str]]:
        """Find completely disconnected execution clusters (connected components) and name them by domain."""
        # Build undirected graph
        adjacency = defaultdict(set)
        for edge in self.graph["edges"]:
            adjacency[edge["from"]].add(edge["to"])
            adjacency[edge["to"]].add(edge["from"])

        visited = set()
        components = []

        all_nodes = [n["id"] for n in self.graph["nodes"]]
        for node in all_nodes:
            if node not in visited:
                component = []
                queue = deque([node])
                while queue:
                    curr = queue.popleft()
                    if curr in visited: continue
                    visited.add(curr)
                    component.append(curr)
                    for neighbor in adjacency[curr]:
                        if neighbor not in visited:
                            queue.append(neighbor)
                if len(component) > 1:
                    components.append(component)

        # Mapping for fast domain lookup
        file_to_domain = {item["file"]: item.get("domain", "unknown") for item in self.file_indices}

        # Name domains by most common domain in the cluster
        named_domains = {}
        for i, comp in enumerate(components):
            domain_votes = defaultdict(int)
            for file in comp:
                domain_votes[file_to_domain.get(file, "unknown")] += 1
            
            winner = max(domain_votes.items(), key=lambda x: x[1])[0]
            if winner == "unknown":
                # Fallback to parent folder if domain unknown
                roots = defaultdict(int)
                for file in comp:
                    root = file.split("/")[0] if "/" in file else "root"
                    roots[root] += 1
                winner = max(roots.items(), key=lambda x: x[1])[0]

            if winner in named_domains:
                winner = f"{winner}_cluster_{i}"
            
            named_domains[winner] = sorted(comp)

        self.domains = named_domains
        return self.domains

if __name__ == "__main__":
    # Test stub would go here
    pass
