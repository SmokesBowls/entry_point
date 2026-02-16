"""
Phase 3: Structural Cartography
Aggregates file-level data into folder-level health metrics.
Detects independent execution domains (disconnected clusters).
"""
from pathlib import Path
from collections import defaultdict


# Health classification thresholds
HEALTH_RULES = {
    "core_runtime": lambda r: r["runtime_files"] > 0,
    "active_mixed": lambda r: r["active_files"] > 0 and r["legacy_files"] > 0,
    "fully_active": lambda r: r["active_files"] > 0 and r["legacy_files"] == 0,
    "full_removal_candidate": lambda r: r["active_files"] == 0,
}


class CartographyEngine:
    def __init__(self, repo_root: Path, file_data: list, graph: dict):
        """
        Args:
            repo_root: repository root path
            file_data: list of file dicts with: file, evidence, confidence, status, domain, intent
            graph: adjacency list from GraphEngine
        """
        self.repo_root = repo_root
        self.file_data = file_data
        self.graph = graph

    def aggregate_folders(self) -> dict:
        """
        Roll up file metrics into folder-level summaries.
        Returns dict of folder_path -> metrics.
        """
        folders = defaultdict(lambda: {
            "total_files": 0,
            "active_files": 0,
            "legacy_files": 0,
            "runtime_files": 0,
            "static_files": 0,
            "reference_files": 0,
            "health": "unknown",
            "active_ratio": 0.0,
            "score_avg": 0.0,
        })

        scores = defaultdict(list)

        for entry in self.file_data:
            rel = entry["file"]
            parts = rel.split("/")
            # Aggregate at each folder level
            folder = "/".join(parts[:-1]) if len(parts) > 1 else "."
            
            rec = folders[folder]
            rec["total_files"] += 1
            
            if entry["status"] == "ACTIVE":
                rec["active_files"] += 1
            else:
                rec["legacy_files"] += 1

            evidence = entry.get("evidence", [])
            if "runtime_trace" in evidence:
                rec["runtime_files"] += 1
            if "static_import" in evidence:
                rec["static_files"] += 1
            if "text_reference" in evidence:
                rec["reference_files"] += 1

            # Score: runtime=5, static=3, text_ref=1
            score = 0
            if "runtime_trace" in evidence:
                score += 5
            if "static_import" in evidence:
                score += 3
            if "text_reference" in evidence:
                score += 1
            scores[folder].append(score)

        # Calculate derived metrics
        for folder, rec in folders.items():
            if rec["total_files"] > 0:
                rec["active_ratio"] = round(rec["active_files"] / rec["total_files"], 2)
                s = scores.get(folder, [0])
                rec["score_avg"] = round(sum(s) / len(s), 1)

            # Classify health
            rec["health"] = self._classify_health(rec)

        return dict(folders)

    @staticmethod
    def _classify_health(rec: dict) -> str:
        """Assign a health label to a folder."""
        if rec["runtime_files"] > 0:
            return "core_runtime"
        if rec["active_files"] > 0 and rec["legacy_files"] > 0:
            return "active_mixed"
        if rec["active_files"] > 0:
            return "fully_active"
        return "full_removal_candidate"

    def detect_domains(self) -> list:
        """
        Detect independent execution domains (disconnected subgraphs).
        Returns list of domain dicts with their file members.
        """
        if not self.graph:
            return []

        # Build undirected version for connectivity
        undirected = defaultdict(set)
        for src, targets in self.graph.items():
            for tgt in targets:
                undirected[src].add(tgt)
                undirected[tgt].add(src)

        # BFS to find connected components
        visited = set()
        components = []

        active_nodes = {e["file"] for e in self.file_data if e["status"] == "ACTIVE"}

        for node in sorted(active_nodes):
            if node in visited:
                continue
            component = set()
            queue = [node]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for neighbor in undirected.get(current, set()):
                    if neighbor not in visited and neighbor in active_nodes:
                        queue.append(neighbor)

            if component:
                # Determine the domain label from the most common folder prefix
                prefixes = defaultdict(int)
                for f in component:
                    parts = f.split("/")
                    prefix = parts[0] if len(parts) > 1 else "root"
                    prefixes[prefix] += 1
                
                label = max(prefixes, key=prefixes.get)
                components.append({
                    "label": label,
                    "files": sorted(component),
                    "size": len(component),
                })

        return sorted(components, key=lambda c: c["size"], reverse=True)
