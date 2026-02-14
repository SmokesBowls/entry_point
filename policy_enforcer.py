import os
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Set, Tuple

class PolicyEnforcer:
    def __init__(self, repo_root: Path, file_indices: List[Dict[str, Any]], graph: Dict[str, Any], classified_entrypoints: List[Dict[str, Any]]):
        self.repo_root = repo_root
        self.file_indices = file_indices
        self.graph = graph
        self.classified_entrypoints = classified_entrypoints

    def detect_violations(self) -> Dict[str, Any]:
        return {
            "active_in_archive": self._check_active_in_archive(),
            "imports_from_archive": self._check_imports_from_archive(),
            "tests_touching_runtime": self._check_tests_touching_runtime(),
            "shadowed_by_archive": self._check_shadowing()
        }

    def _check_active_in_archive(self) -> List[str]:
        """Files in archive/ that are marked ACTIVE or have reachable coverage."""
        violations = []
        for item in self.file_indices:
            path = item["file"]
            if "archive/" in path.lower() and item.get("status") == "ACTIVE":
                violations.append(path)
        
        # Also check if any archive entrypoint has coverage > 0
        for entry in self.classified_entrypoints:
            if "intent:archive" in entry.get("intent_tags", []) and entry.get("coverage", {}).get("cover_nodes", 0) > 0:
                if entry["path"] not in violations:
                    violations.append(entry["path"])
                    
        return sorted(violations)

    def _check_imports_from_archive(self) -> List[Dict[str, str]]:
        """Active code/Runtime code importing from archive/."""
        violations = []
        for edge in self.graph["edges"]:
            src = edge["from"]
            dst = edge["to"]
            if "archive/" in dst.lower() and "archive/" not in src.lower():
                violations.append({"importer": src, "imported": dst})
        return violations

    def _check_tests_touching_runtime(self) -> Dict[str, Any]:
        """Files tagged intent:tests calling modules tagged intent:runtime."""
        detailed_violations = []
        
        # Build a map for fast intent lookup
        file_intents = {item["file"]: item.get("intent", "unknown") for item in self.file_indices}
        
        for edge in self.graph["edges"]:
            src = edge["from"]
            dst = edge["to"]
            
            src_intent = file_intents.get(src, "unknown")
            dst_intent = file_intents.get(dst, "unknown")
            
            # Heuristic fallbacks if intent is unknown
            if src_intent == "unknown":
                if "tests/" in src.lower() or os.path.basename(src).startswith("test_"):
                    src_intent = "test"
            
            if dst_intent == "unknown":
                if not any(x in dst.lower() for x in ["archive/", "tests/", "tools/", "docs/"]):
                    dst_intent = "runtime"

            if src_intent == "test" and dst_intent == "runtime":
                # Extract calls-level evidence
                for call in edge.get("calls", []):
                    detailed_violations.append({
                        "test_path": src,
                        "test_line": call.get("line"),
                        "runtime_path": dst,
                        "runtime_line": 0, # Note: Runtime line (definition) not yet supported
                        "symbol": call.get("symbol"),
                        "edge_type": edge.get("type", "unknown"),
                        "evidence": "runtime_trace",
                        "severity": "error",
                        "suggested_fix": "Replace direct runtime import/call with a mock fixture"
                    })

        # Generate summary stats
        summary = {
            "total_violations": len(detailed_violations),
            "by_test_file": defaultdict(int),
            "by_runtime_module": defaultdict(int)
        }
        
        for v in detailed_violations:
            summary["by_test_file"][v["test_path"]] += 1
            summary["by_runtime_module"][v["runtime_path"]] += 1
            
        return {
            "boundary_violations": detailed_violations,
            "summary": {
                "total_violations": summary["total_violations"],
                "by_test_file": dict(summary["by_test_file"]),
                "by_runtime_module": dict(summary["by_runtime_module"])
            }
        }

    def _check_shadowing(self) -> List[Dict[str, str]]:
        """Module name collisions between archive/ and others."""
        violations = []
        module_map = {} # module_name -> path
        
        for item in self.file_indices:
            path = item["file"]
            if not path.endswith(".py"): continue
            
            mod_name = os.path.basename(path)
            if mod_name not in module_map:
                module_map[mod_name] = []
            module_map[mod_name].append(path)
            
        for mod, paths in module_map.items():
            if len(paths) > 1:
                # Check if one is in archive and another is not
                in_archive = [p for p in paths if "archive/" in p.lower()]
                out_archive = [p for p in paths if "archive/" not in p.lower()]
                if in_archive and out_archive:
                    # In Python, usually the first one in sys.path wins. 
                    # We assume repo-root is before archive/ in pathing.
                    resolved = out_archive[0] 
                    for arch in in_archive:
                        for act in out_archive:
                            violations.append({
                                "module": mod,
                                "active_path": act,
                                "archived_path": arch,
                                "resolved_to": resolved
                            })
        return violations
