"""
Phase 4: Entrypoint Triangulator
Ranks entrypoints by how much of the active codebase they "cover" (reach).
Uses greedy set-cover to find the minimum set of entrypoints that achieves
maximum coverage of active/runtime files.
"""
from pathlib import Path
from collections import deque


class Triangulator:
    def __init__(self, repo_root: Path, graph: dict, file_data: list):
        """
        Args:
            repo_root: repository root path
            graph: adjacency list from GraphEngine {file_rel: set of imported file_rels}
            file_data: Phase 1 file records
        """
        self.repo_root = repo_root
        self.graph = graph
        self.file_data = file_data

    def get_target_set(self, mode: str = "active_or_runtime") -> set:
        """
        Get the set of files we're trying to cover.
        
        Modes:
            active_or_runtime: all files that are ACTIVE or have runtime_trace
            active_only: only ACTIVE files
            runtime_only: only files with runtime_trace evidence
        """
        target = set()
        for entry in self.file_data:
            if mode == "active_or_runtime":
                if entry["status"] == "ACTIVE" or "runtime_trace" in entry.get("evidence", []):
                    target.add(entry["file"])
            elif mode == "active_only":
                if entry["status"] == "ACTIVE":
                    target.add(entry["file"])
            elif mode == "runtime_only":
                if "runtime_trace" in entry.get("evidence", []):
                    target.add(entry["file"])
        return target

    def find_candidates(self, detected_entrypoints: set = None) -> list:
        """
        Find candidate entrypoints -- files that are graph roots or ACTIVE.
        
        If detected_entrypoints is provided, candidates MUST also be in that set.
        This prevents library files with high centrality from being promoted.
        """
        has_incoming = set()
        for node, neighbors in self.graph.items():
            has_incoming.update(neighbors)

        roots = set(self.graph.keys()) - has_incoming

        for entry in self.file_data:
            if entry["status"] == "ACTIVE" and entry["file"].endswith(".py"):
                roots.add(entry["file"])

        # Constrain to detected entrypoints if provided
        if detected_entrypoints:
            roots = roots.intersection(detected_entrypoints)

        return sorted(roots)

    def _compute_reach(self, start: str) -> set:
        """BFS to compute all files reachable from a starting node."""
        visited = set()
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for neighbor in self.graph.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        return visited

    def rank_entrypoints(self, candidates: list, target: set, engine_scopes: list = None) -> list:
        """
        Rank each candidate by how many target files it reaches.
        
        Args:
            candidates: list of candidate file paths
            target: set of files we're trying to cover
            engine_scopes: optional list of folder prefixes to scope to
            
        Returns:
            list of dicts: [{"path": str, "coverage": {"cover_nodes": int, "cover_ratio": float}}]
        """
        if not target:
            return []

        ranked = []
        for candidate in candidates:
            reachable = self._compute_reach(candidate)
            covered = reachable.intersection(target)

            # If engine_scopes provided, also compute scoped coverage
            in_scope = True
            if engine_scopes and engine_scopes != ["."]:
                in_scope = any(
                    candidate == scope or candidate.startswith(scope + "/")
                    for scope in engine_scopes
                )

            ranked.append({
                "path": candidate,
                "coverage": {
                    "cover_nodes": len(covered),
                    "cover_ratio": len(covered) / len(target) if target else 0.0,
                },
                "in_engine_scope": in_scope,
            })

        # Sort by coverage descending, then by path for determinism
        ranked.sort(key=lambda x: (-x["coverage"]["cover_nodes"], x["path"]))
        return ranked

    def select_engines(self, ranked: list, target: set, config: dict = None) -> dict:
        """
        Greedy set-cover: pick top-K entrypoints that maximize coverage.
        
        Args:
            ranked: list from rank_entrypoints
            target: target file set
            config: {"max_k": int, "coverage_threshold": float}
            
        Returns:
            dict with selected engines and coverage stats
        """
        config = config or {}
        max_k = config.get("max_k", 10)
        threshold = config.get("coverage_threshold", 0.95)

        selected = []
        covered = set()
        remaining_target = set(target)

        # Greedy selection
        for _ in range(max_k):
            if not remaining_target:
                break

            best = None
            best_gain = 0

            for entry in ranked:
                path = entry["path"]
                if any(s["path"] == path for s in selected):
                    continue

                reachable = self._compute_reach(path)
                gain = len(reachable.intersection(remaining_target))
                if gain > best_gain:
                    best_gain = gain
                    best = entry

            if best is None or best_gain == 0:
                break

            selected.append(best)
            reachable = self._compute_reach(best["path"])
            covered.update(reachable.intersection(target))
            remaining_target -= reachable

            # Check threshold
            ratio = len(covered) / len(target) if target else 0.0
            if ratio >= threshold:
                break

        total_coverage = len(covered) / len(target) if target else 0.0

        return {
            "selected": selected,
            "all_ranked": ranked[:50],  # Keep top 50 for reference
            "coverage_summary": {
                "total_target": len(target),
                "total_covered": len(covered),
                "coverage_ratio": round(total_coverage, 4),
                "engines_selected": len(selected),
            },
        }
