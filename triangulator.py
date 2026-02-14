import os
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Iterable

@dataclass
class RankedEP:
    path: str
    indegree: int
    outdegree: int
    reach_nodes: int
    cover_nodes: int
    cover_ratio: float

class Triangulator:
    COMMON_ENTRY_BASENAMES = {
        "main.py", "app.py", "server.py", "run.py", "start.py", "launch.py", "__main__.py",
        "manage.py", "wsgi.py", "asgi.py", "cli.py",
        "index.js", "main.js", "app.js", "server.js", "start.js", "cli.js",
    }

    def __init__(self, repo_root: Path, graph: Dict[str, Any], file_indices: List[Dict[str, Any]]):
        self.repo_root = repo_root
        self.graph = graph
        self.file_indices = file_indices
        self.adj, self.indeg, self.outdeg, self.nodes = self._build_graph(graph["edges"])

    def _build_graph(self, edges: List[Dict[str, Any]]) -> Tuple[Dict[str, Set[str]], Counter, Counter, Set[str]]:
        adj = defaultdict(set)
        indeg = Counter()
        outdeg = Counter()
        nodes = set()

        for e in edges:
            src = e["from"]
            dst = e["to"]
            nodes.add(src)
            nodes.add(dst)
            if dst not in adj[src]:
                adj[src].add(dst)
                outdeg[src] += 1
                indeg[dst] += 1
                indeg[src] += 0
                outdeg[dst] += 0
        return adj, indeg, outdeg, nodes

    def _reachable_set(self, start: str) -> Set[str]:
        if start not in self.adj:
            return set()
        seen = {start}
        q = deque([start])
        while q:
            cur = q.popleft()
            for nxt in self.adj.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        return seen

    def find_candidates(self) -> Set[str]:
        # graph roots
        roots = {n for n in self.nodes if self.indeg.get(n, 0) == 0 and self.outdeg.get(n, 0) > 0}

        # heuristic names
        by_base = defaultdict(list)
        for item in self.file_indices:
            p = item["file"]
            by_base[os.path.basename(p)].append(p)

        heur = set()
        for base in self.COMMON_ENTRY_BASENAMES:
            for p in by_base.get(base, []):
                heur.add(p)

        return roots | heur

    def get_target_set(self, mode: str = "active") -> Set[str]:
        out = set()
        for rec in self.file_indices:
            f = rec.get("file")
            if not f: continue
            status = rec.get("status", "")
            ev = rec.get("evidence", []) or []
            if mode == "active" and status == "ACTIVE":
                out.add(f)
            elif mode == "runtime" and "runtime_trace" in ev:
                out.add(f)
            elif mode == "active_or_runtime" and (status == "ACTIVE" or "runtime_trace" in ev):
                out.add(f)
        return out

    def rank_entrypoints(self, candidates: Iterable[str], target: Set[str], engine_scopes: List[str] = None) -> List[RankedEP]:
        ranked = []
        self.reach_cache = {}
        
        # Check if an entrypoint is within any of the engine scopes
        def is_in_engine_scope(path_str: str) -> bool:
            if not engine_scopes or engine_scopes == ["."]:
                return True
            for scope in engine_scopes:
                if path_str == scope or path_str.startswith(scope + "/"):
                    return True
            return False

        for ep in candidates:
            reach = self._reachable_set(ep)
            self.reach_cache[ep] = reach
            covered = reach.intersection(target)
            cover_n = len(covered)
            reach_n = len(reach) - (1 if ep in reach else 0)
            ratio = (cover_n / len(target)) if target else 0.0
            
            # Application of the non-negotiable guardrail rule
            in_scope = is_in_engine_scope(ep)
            
            ranked.append(
                RankedEP(
                    path=ep,
                    indegree=int(self.indeg.get(ep, 0)),
                    outdegree=int(self.outdeg.get(ep, 0)),
                    reach_nodes=reach_n,
                    cover_nodes=cover_n,
                    cover_ratio=ratio,
                )
            )
            # Tag the last added element with scope info (internal use)
            ranked[-1].in_engine_scope = in_scope

        # Sort: Primary sort by engine scope (in-scope first), then coverage
        ranked.sort(key=lambda r: (getattr(r, "in_engine_scope", True), r.cover_nodes, r.outdegree, r.reach_nodes), reverse=True)
        return ranked

    def select_engines(self, ranked: List[RankedEP], target: Set[str], config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Revised selection algorithm for v2: Primary + Greedy Secondary with thresholds."""
        cfg = {
            "primary_k": 1,
            "secondary_k": 2,
            "coverage_threshold": 0.90,
            "max_k": 10
        }
        if config: cfg.update(config)

        uncovered = set(target)
        chosen = []
        
        # 1. Take Primary Entrypoints
        eligible_ranked = [r for r in ranked if getattr(r, "in_engine_scope", True)]

        for i in range(min(len(eligible_ranked), cfg["primary_k"])):
            ep = eligible_ranked[i]
            reach = self.reach_cache.get(ep.path, set())
            gain = len(uncovered.intersection(reach))
            
            uncovered -= reach
            chosen.append(self._format_chosen(ep, gain, "primary"))

        # 2. Add Secondary Entrypoints (Greedy by marginal gain from remaining eligible)
        secondary_count = 0
        while len(chosen) < cfg["max_k"] and secondary_count < cfg["secondary_k"]:
            # Check coverage threshold
            covered_total = len(target) - len(uncovered)
            current_ratio = (covered_total / len(target)) if target else 1.0
            if current_ratio >= cfg["coverage_threshold"]:
                break

            # Find best marginal gain from remaining
            best = None
            best_gain = -1
            for r in eligible_ranked:
                if any(c["path"] == r.path for c in chosen): continue
                reach = self.reach_cache.get(r.path, set())
                gain = len(uncovered.intersection(reach))
                if gain > best_gain:
                    best_gain = gain
                    best = r
            
            if not best or best_gain <= 0:
                break
            
            uncovered -= self.reach_cache[best.path]
            chosen.append(self._format_chosen(best, best_gain, "secondary"))
            secondary_count += 1

        covered_total = len(target) - len(uncovered)
        return {
            "config": cfg,
            "target_total": len(target),
            "covered_total": covered_total,
            "covered_ratio": round((covered_total / len(target)) if target else 0.0, 6),
            "chosen": chosen
        }

    def _format_chosen(self, ep: RankedEP, gain: int, role: str) -> Dict[str, Any]:
        return {
            "path": ep.path,
            "role": role,
            "marginal_gain": gain,
            "total_cover_nodes": ep.cover_nodes,
            "cover_ratio": round(ep.cover_ratio, 6),
            "indegree": ep.indegree,
            "outdegree": ep.outdegree,
            "reach_nodes": ep.reach_nodes,
            "in_engine_scope": getattr(ep, "in_engine_scope", True),
        }

    def greedy_topk(self, ranked: List[RankedEP], target: Set[str], k: int) -> Dict[str, Any]:
        # Backwards compatibility wrapper
        return self.select_engines(ranked, target, {"primary_k": 1, "secondary_k": k-1, "max_k": k})
