"""
v2.2: Surface & Scope Resolver
Detects surfaces (independent codebases in one repo), assigns surface_id
to every file, and infers engine scope for each surface.

A "surface" is a top-level directory containing a significant codebase.
Surfaces are independent: they get separate graphs, separate metrics,
separate entrypoint rankings. Cross-surface edges are tracked explicitly.
"""
from pathlib import Path
from collections import defaultdict, Counter


class ScopeResolver:
    def __init__(self, repo_root: Path, file_data: list, graph: dict,
                 engine_target_config: dict = None):
        self.repo_root = repo_root
        self.file_data = file_data
        self.graph = graph
        self.target_config = engine_target_config or {}
        self._surface_cache = {}
        self._detected_roots = None  # Populated by detect_surfaces()

        # Surface config from engine_target.yml
        self.surface_config = self.target_config.get("surfaces", {})
        self.cross_allow = self.target_config.get("cross_surface", {}).get("allow", [])

    # ----------------------------------------------------------------
    # Surface detection
    # ----------------------------------------------------------------

    def detect_surfaces(self) -> dict:
        """
        Detect distinct surfaces (codebases) in the repo.

        Returns: {
            "surfaces": {
                "godotsim": {"root": "godotsim/", "file_count": 450, ...},
            },
            "unassigned_count": 5,
        }
        """
        if self.surface_config:
            result = self._detect_from_config()
            # Cache roots for resolve_surface
            self._detected_roots = sorted(
                [(sid, sdata["root"].rstrip("/")) for sid, sdata in result["surfaces"].items()],
                key=lambda x: -len(x[1])
            )
            return result

        folder_stats = defaultdict(lambda: {"files": 0, "py": 0, "runtime": 0, "active": 0})
        root_files = 0

        for entry in self.file_data:
            parts = entry["file"].split("/")
            if len(parts) <= 1:
                root_files += 1
                continue

            top = parts[0]
            if top.lower() in ("archive", "docs", "reports", ".git",
                                "__pycache__", "node_modules", "_quarantine"):
                continue

            folder_stats[top]["files"] += 1
            if entry["file"].endswith(".py"):
                folder_stats[top]["py"] += 1
            if entry.get("status") == "ACTIVE":
                folder_stats[top]["active"] += 1
            if "runtime_trace" in entry.get("evidence", []):
                folder_stats[top]["runtime"] += 1

        # A surface must have at least 3 Python files
        surfaces = {}
        for folder, stats in folder_stats.items():
            if stats["py"] >= 3:
                surfaces[folder] = {
                    "root": folder + "/",
                    "file_count": stats["files"],
                    "py_count": stats["py"],
                    "active_count": stats["active"],
                    "runtime_count": stats["runtime"],
                    "type": "auto_detected",
                }

        # Sub-surface detection: if a top-level folder contains multiple
        # distinct sub-directories each with 3+ py files, split it.
        # This catches cases like EndGame/ containing godotsim/ + enginality/
        if surfaces:
            for folder, sdata in list(surfaces.items()):
                # Only consider folders with enough files to justify splitting
                if sdata["py_count"] < 20:
                    continue

                sub_stats = defaultdict(lambda: {"files": 0, "py": 0, "active": 0, "runtime": 0})
                for entry in self.file_data:
                    if not entry["file"].startswith(folder + "/"):
                        continue
                    rest = entry["file"][len(folder) + 1:]
                    sub_parts = rest.split("/")
                    if len(sub_parts) <= 1:
                        continue
                    sub = sub_parts[0]
                    sub_stats[sub]["files"] += 1
                    if entry["file"].endswith(".py"):
                        sub_stats[sub]["py"] += 1
                    if entry.get("status") == "ACTIVE":
                        sub_stats[sub]["active"] += 1
                    if "runtime_trace" in entry.get("evidence", []):
                        sub_stats[sub]["runtime"] += 1

                # Need at least 2 significant sub-folders to justify splitting
                significant_subs = {k: v for k, v in sub_stats.items() if v["py"] >= 3}
                if len(significant_subs) >= 2:
                    # Replace parent with children
                    del surfaces[folder]
                    for sub, sstats in significant_subs.items():
                        sid = f"{folder}/{sub}"
                        surfaces[sid] = {
                            "root": sid + "/",
                            "file_count": sstats["files"],
                            "py_count": sstats["py"],
                            "active_count": sstats["active"],
                            "runtime_count": sstats["runtime"],
                            "type": "auto_split",
                            "parent": folder,
                        }

        result = {"surfaces": surfaces, "unassigned_count": root_files}

        # Cache roots for resolve_surface (longest first for prefix matching)
        self._detected_roots = sorted(
            [(sid, sdata["root"].rstrip("/")) for sid, sdata in surfaces.items()],
            key=lambda x: -len(x[1])
        )

        return result

    def _ensure_detected(self):
        """Ensure detect_surfaces has been called and roots are cached."""
        if self._detected_roots is None:
            self.detect_surfaces()

    def _detect_from_config(self) -> dict:
        """Build surface info from engine_target.yml surface config."""
        surfaces = {}
        for sid, conf in self.surface_config.items():
            root = conf.get("root", sid + "/")
            if not root.endswith("/"):
                root += "/"

            count = sum(1 for e in self.file_data if e["file"].startswith(root))
            py_count = sum(1 for e in self.file_data
                          if e["file"].startswith(root) and e["file"].endswith(".py"))

            surfaces[sid] = {
                "root": root,
                "file_count": count,
                "py_count": py_count,
                "type": conf.get("type", "configured"),
            }

        unassigned = sum(1 for e in self.file_data
                         if not any(e["file"].startswith(s["root"]) for s in surfaces.values()))
        return {"surfaces": surfaces, "unassigned_count": unassigned}

    # ----------------------------------------------------------------
    # Surface assignment
    # ----------------------------------------------------------------

    def resolve_surface(self, file_path: str) -> str:
        """Return surface_id for a file path. Cached.
        
        Priority: explicit config > auto-detected roots > top-level folder.
        Uses longest-prefix matching so nested configs like
        EndGame/godotsim/ beat EndGame/ when both are defined.
        """
        if file_path in self._surface_cache:
            return self._surface_cache[file_path]

        parts = file_path.split("/")
        if len(parts) <= 1:
            self._surface_cache[file_path] = "_root"
            return "_root"

        # Check explicit config first -- longest prefix wins
        if self.surface_config:
            best_sid = None
            best_len = 0
            for sid, conf in self.surface_config.items():
                root = conf.get("root", sid + "/").rstrip("/")
                if (file_path.startswith(root + "/") or file_path == root) and len(root) > best_len:
                    best_sid = sid
                    best_len = len(root)
            if best_sid:
                self._surface_cache[file_path] = best_sid
                return best_sid

        # Check auto-detected roots (includes auto-split sub-surfaces)
        self._ensure_detected()
        if self._detected_roots:
            for sid, root in self._detected_roots:  # Already sorted longest-first
                if file_path.startswith(root + "/") or file_path == root:
                    self._surface_cache[file_path] = sid
                    return sid

        # Fallback: top-level folder
        top = parts[0]
        self._surface_cache[file_path] = top
        return top

    def tag_files(self, file_data: list) -> list:
        """
        Add surface_id and surface_root to every file record.
        Mutates in place AND returns for chaining.
        """
        surfaces = self.detect_surfaces()
        surface_map = surfaces["surfaces"]

        for entry in file_data:
            sid = self.resolve_surface(entry["file"])
            entry["surface_id"] = sid
            if sid in surface_map:
                entry["surface_root"] = surface_map[sid]["root"]
            else:
                entry["surface_root"] = sid + "/"

        return file_data

    # ----------------------------------------------------------------
    # Cross-surface edge analysis
    # ----------------------------------------------------------------

    def classify_edges(self, graph: dict) -> dict:
        """
        Classify all edges as intra-surface or cross-surface.

        Returns: {
            "intra_count": int,
            "cross_count": int,
            "cross": [(src, dst, src_surface, dst_surface), ...],
            "cross_by_pair": {("godotsim", "godotengain"): [(src, dst), ...]},
        }
        """
        intra_count = 0
        cross = []
        cross_by_pair = defaultdict(list)

        for src, neighbors in graph.items():
            src_surface = self.resolve_surface(src)
            for dst in neighbors:
                dst_surface = self.resolve_surface(dst)
                if src_surface == dst_surface:
                    intra_count += 1
                else:
                    cross.append((src, dst, src_surface, dst_surface))
                    pair = (src_surface, dst_surface)
                    cross_by_pair[pair].append((src, dst))

        return {
            "intra_count": intra_count,
            "cross_count": len(cross),
            "cross": cross,
            "cross_by_pair": dict(cross_by_pair),
        }

    def is_cross_allowed(self, src_surface: str, dst_surface: str) -> bool:
        """Check if cross-surface edge is allowed by config."""
        for rule in self.cross_allow:
            if rule.get("from") == src_surface and rule.get("to") == dst_surface:
                return True
            if rule.get("from") == dst_surface and rule.get("to") == src_surface:
                return True
        return False

    # ----------------------------------------------------------------
    # Scope inference (backward compat)
    # ----------------------------------------------------------------

    def infer_scopes(self) -> dict:
        """
        Infer engine scopes by finding the top-level folders with the most
        runtime-traced or active files.

        Returns: {"engine_scopes": [list of folder paths], "confidence": str}
        """
        folder_counts = Counter()
        runtime_folders = Counter()

        for entry in self.file_data:
            if entry["status"] != "ACTIVE":
                continue
            parts = entry["file"].split("/")
            top = parts[0] if len(parts) > 1 else "."

            folder_counts[top] += 1
            if "runtime_trace" in entry.get("evidence", []):
                runtime_folders[top] += 1

        if not folder_counts:
            return {"engine_scopes": ["."], "confidence": "low"}

        scores = {}
        skip = {"archive", "docs", "tests", "test", ".git", "__pycache__",
                "reports", "node_modules", "_quarantine"}
        for folder, count in folder_counts.items():
            if folder.lower() in skip:
                continue
            runtime_count = runtime_folders.get(folder, 0)
            scores[folder] = runtime_count * 3 + count

        if not scores:
            return {"engine_scopes": ["."], "confidence": "low"}

        sorted_scopes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        max_score = sorted_scopes[0][1]

        engine_scopes = []
        for folder, score in sorted_scopes:
            if score >= max_score * 0.5:
                engine_scopes.append(folder)
            else:
                break

        engine_scopes = engine_scopes[:5]
        confidence = "high" if len(engine_scopes) == 1 else "medium"
        if max_score < 3:
            confidence = "low"

        return {"engine_scopes": engine_scopes, "confidence": confidence}

    # ----------------------------------------------------------------
    # Per-surface queries
    # ----------------------------------------------------------------

    def get_surface_graph(self, graph: dict, surface_id: str) -> dict:
        """Return subgraph containing only files from a specific surface."""
        surface_files = {e["file"] for e in self.file_data
                         if self.resolve_surface(e["file"]) == surface_id}
        subgraph = {}
        for node, neighbors in graph.items():
            if node in surface_files:
                subgraph[node] = {n for n in neighbors if n in surface_files}
        return subgraph

    def get_surface_files(self, surface_id: str) -> list:
        """Return file records for a specific surface."""
        return [e for e in self.file_data
                if self.resolve_surface(e["file"]) == surface_id]

    def get_surface_metrics(self, graph: dict) -> dict:
        """
        Compute per-surface summary metrics.

        Returns: {
            "godotsim": {
                "file_count": 450, "active": 320, "runtime": 45,
                "internal_edges": 200, "cross_edges_out": 12, "cross_edges_in": 8,
                "coverage": 0.71
            }, ...
        }
        """
        surfaces = self.detect_surfaces()["surfaces"]
        edge_info = self.classify_edges(graph)
        cross_edges = edge_info["cross"]

        metrics = {}
        for sid, sdata in surfaces.items():
            s_files = self.get_surface_files(sid)
            active = sum(1 for f in s_files if f.get("status") == "ACTIVE")
            runtime = sum(1 for f in s_files if "runtime_trace" in f.get("evidence", []))

            # Internal edges
            s_graph = self.get_surface_graph(graph, sid)
            internal_edges = sum(len(v) for v in s_graph.values())

            # Cross edges
            cross_out = sum(1 for _, _, ss, _ in cross_edges if ss == sid)
            cross_in = sum(1 for _, _, _, ds in cross_edges if ds == sid)

            total = len(s_files) or 1
            coverage = active / total

            metrics[sid] = {
                "file_count": len(s_files),
                "py_count": sdata.get("py_count", 0),
                "active": active,
                "runtime": runtime,
                "internal_edges": internal_edges,
                "cross_edges_out": cross_out,
                "cross_edges_in": cross_in,
                "coverage": round(coverage, 4),
            }

        return metrics
