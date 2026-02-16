"""
Phase 5: Policy Enforcer
Detects architectural violations:
  - active_in_archive: Active code living in archive/ folders
  - imports_from_archive: Non-archive code importing from archive/
  - tests_touching_runtime: Test files importing runtime modules directly
  - shadowed_modules: Module name collisions between active and archived versions
"""
import ast
from pathlib import Path
from collections import defaultdict


class PolicyEnforcer:
    def __init__(self, repo_root: Path, file_data: list, graph: dict,
                 classified_entrypoints: list = None, surface_resolver=None):
        """
        Args:
            repo_root: repository root
            file_data: Phase 1 file records (with surface_id tags)
            graph: adjacency list from GraphEngine
            classified_entrypoints: Phase 4.5 classified entrypoint list
            surface_resolver: ScopeResolver instance for cross-surface analysis
        """
        self.repo_root = repo_root
        self.file_data = file_data
        self.graph = graph
        self.classified_entrypoints = classified_entrypoints or []
        self.surface_resolver = surface_resolver

    def detect_violations(self) -> dict:
        """Run all violation checks and return a unified report."""
        result = {
            "active_in_archive": self._detect_active_in_archive(),
            "imports_from_archive": self._detect_imports_from_archive(),
            "tests_touching_runtime": self._detect_tests_touching_runtime(),
            "shadowed_modules": self._detect_shadowed_modules(),
        }

        # Cross-surface violations (if resolver available)
        if self.surface_resolver:
            result["cross_surface"] = self._detect_cross_surface_violations()

        return result

    def _detect_active_in_archive(self) -> list:
        """Find ACTIVE files that live in archive/ folders."""
        violations = []
        for entry in self.file_data:
            if entry["status"] == "ACTIVE" and self._is_archive(entry["file"]):
                violations.append({
                    "file": entry["file"],
                    "evidence": entry.get("evidence", []),
                    "confidence": entry.get("confidence", "LOW"),
                })
        return violations

    def _detect_imports_from_archive(self) -> list:
        """Find non-archive files that import from archive/ paths."""
        violations = []
        for src, targets in self.graph.items():
            if self._is_archive(src):
                continue  # Skip archive -> archive imports
            for tgt in targets:
                if self._is_archive(tgt):
                    violations.append({
                        "importer": src,
                        "imported": tgt,
                    })
        return violations

    def _detect_tests_touching_runtime(self) -> dict:
        """Find test files that import runtime modules directly."""
        # Classify files by intent
        test_files = set()
        runtime_files = set()
        for entry in self.file_data:
            rel = entry["file"]
            if self._is_test(rel):
                test_files.add(rel)
            elif not self._is_archive(rel) and not self._is_test(rel):
                runtime_files.add(rel)

        violations = []
        by_test = defaultdict(int)
        by_runtime = defaultdict(int)

        for test_file in test_files:
            imports = self.graph.get(test_file, set())
            for imp in imports:
                if imp in runtime_files:
                    # Determine severity: core imports are errors, tools are warnings
                    is_core = any(seg in imp for seg in ("core/", "engine/", "runtime"))
                    severity = "error" if is_core else "warn"

                    violations.append({
                        # View Contract keys -- must match report_viewer.html exactly
                        "test_file": test_file,
                        "runtime_module": imp,
                        "symbol": imp.rsplit("/", 1)[-1].replace(".py", ""),
                        "edge_type": "static_import",
                        "severity": severity,
                        "evidence": "import graph",
                        "suggested_fix": f"Mock or isolate {imp} behind an interface.",
                    })
                    by_test[test_file] += 1
                    by_runtime[imp] += 1

        return {
            "violations": violations,
            "summary": {
                "total_violations": len(violations),
                "test_files_affected": len({v["test_file"] for v in violations}),
                "by_test_file": dict(by_test),
                "by_runtime_module": dict(by_runtime),
            },
        }

    def _detect_shadowed_modules(self) -> list:
        """Find module name collisions between archive and non-archive files."""
        # Group files by their leaf module name
        by_name = defaultdict(list)
        for entry in self.file_data:
            rel = entry["file"]
            if not rel.endswith(".py"):
                continue
            name = rel.split("/")[-1]
            by_name[name].append(rel)

        violations = []
        for name, paths in by_name.items():
            if len(paths) < 2:
                continue
            
            archive_paths = [p for p in paths if self._is_archive(p)]
            active_paths = [p for p in paths if not self._is_archive(p)]

            if archive_paths and active_paths:
                for active in active_paths:
                    for archived in archive_paths:
                        violations.append({
                            "module": name,
                            "active_path": active,
                            "archived_path": archived,
                        })

        return violations

    @staticmethod
    def _is_archive(path: str) -> bool:
        return "archive/" in path.lower() or path.lower().startswith("archive")

    @staticmethod
    def _is_test(path: str) -> bool:
        parts = path.lower().split("/")
        return any(p in ("tests", "test") for p in parts) or parts[-1].startswith("test_")

    def _detect_cross_surface_violations(self) -> dict:
        """Detect unauthorized cross-surface imports."""
        if not self.surface_resolver:
            return {"violations": [], "summary": {}}

        edge_info = self.surface_resolver.classify_edges(self.graph)
        cross_edges = edge_info["cross"]

        violations = []
        by_pair = defaultdict(int)

        for src, dst, src_surface, dst_surface in cross_edges:
            allowed = self.surface_resolver.is_cross_allowed(src_surface, dst_surface)
            severity = "warn" if allowed else "error"

            violations.append({
                "src_file": src,
                "dst_file": dst,
                "src_surface": src_surface,
                "dst_surface": dst_surface,
                "edge_type": "cross_surface_import",
                "severity": severity,
                "allowed": allowed,
                "suggested_fix": (
                    f"Allowed by config." if allowed
                    else f"Surface '{src_surface}' should not import from '{dst_surface}'. "
                         f"Add to cross_surface.allow in engine_target.yml if intentional."
                ),
            })
            by_pair[(src_surface, dst_surface)] += 1

        return {
            "violations": violations,
            "summary": {
                "total_cross_edges": len(cross_edges),
                "unauthorized": sum(1 for v in violations if not v["allowed"]),
                "allowed": sum(1 for v in violations if v["allowed"]),
                "by_pair": {f"{k[0]}->{k[1]}": v for k, v in by_pair.items()},
            },
        }
