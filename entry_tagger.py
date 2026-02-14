import os
import re
import ast
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple

class EntryTagger:
    INTENT_PRIORITY = ["archive", "tests", "tools", "docs", "runtime"]
    
    ROLE_SIGNALS = {
        "infrastructure_boot": {
            "imports": {"socket", "flask", "fastapi", "http.server", "uvicorn", "flask_restful"},
            "keywords": {"bind", "listen", "port", "server.start", "run_forever", "app.run", "main()"},
            "weight_import": 5,
            "weight_keyword": 4
        },
        "core_logic_driver": {
            "imports": {"rules", "scene", "config", "engine", "state_machine", "game_state", "analyzer", "graph_engine"},
            "keywords": {"load_scene", "evaluate_rule", "run_cycle", "main_loop", "execute_action", "process_event", "analyze", "resolve", "aggregate"},
            "weight_import": 5,
            "weight_keyword": 4
        },
        "tooling_cli": {
            "imports": {"argparse", "click", "typer", "fire"},
            "keywords": {"parser.add_argument", "click.command", "parser.parse_args", "click.option", "AppCLI", "args ="},
            "weight_import": 5,
            "weight_keyword": 4
        },
        "test_harness": {
            "imports": {"unittest", "pytest", "TestCase", "mock", "doctest"},
            "keywords": {"assertEqual", "assertTrue", "assertFalse", "pytest.mark", "TestRunner"},
            "weight_import": 5,
            "weight_keyword": 4
        }
    }

    def __init__(self, repo_root: Path, triangulation_output: Dict[str, Any] = None):
        self.repo_root = repo_root
        self.triangulation_output = triangulation_output or {}

    def tag_all(self, ranked_entries: List[Any] = None) -> List[Dict[str, Any]]:
        entries = ranked_entries or self.triangulation_output.get("chosen", [])
        tagged = []
        for entry in entries:
            # Handle both RankedEP objects and dicts
            if hasattr(entry, "path"):
                path = entry.path
                coverage = {
                    "cover_nodes": entry.cover_nodes,
                    "cover_ratio": entry.cover_ratio
                }
            else:
                path = entry.get("path")
                coverage = entry.get("coverage", {})

            if not path: continue
            
            intent = self._get_intent(path)
            best_role, scores, behavior_tags = self._infer_role(path)
            
            # v2.1: tooling_cli is now eligible for primary engines in runtime intent
            eligible = (best_role in ["infrastructure_boot", "core_logic_driver", "tooling_cli"]) and (intent == "runtime")
            
            # Application of the non-negotiable scope guardrail
            # If Triangulator already performed a scope check, it takes precedence
            in_engine_scope = getattr(entry, "in_engine_scope", True) if hasattr(entry, "in_engine_scope") else entry.get("in_engine_scope", True)
            if not in_engine_scope:
                eligible = False

            # Hard guardrails: never recommend archive/tests/docs/tool paths or validator/gui scripts as engine
            lowered_path = path.lower()
            forbidden_path_markers = ["archive/", "/archive/", "tests/", "/tests/", "validator", "validate", "gui", "ui"]
            if (intent in ["archive", "tests", "docs", "tools"]) or any(m in lowered_path for m in forbidden_path_markers) or best_role == "test_harness":
                eligible = False

            # primary_candidate_score = weighted blend of coverage and role suitability
            cov_ratio = coverage.get("cover_ratio", 0.0)
            role_suitability = min(1.0, scores.get(best_role, 0) / 12.0) if best_role != "unknown" else 0.0
            candidate_score = (0.6 * cov_ratio) + (0.4 * role_suitability)
            if not eligible: candidate_score *= 0.5 # Penalty for non-eligible types

            tagged.append({
                "path": path,
                "coverage": coverage,
                "intent_tags": [f"intent:{intent}"],
                "behavior_tags": [f"behavior:{tag}" for tag in behavior_tags],
                "role": best_role,
                "role_scores": scores,
                "primary_candidate_score": round(candidate_score, 4),
                "eligible_for_primary": eligible,
                "in_engine_scope": in_engine_scope
            })
        return tagged

    def _get_intent(self, path_str: str) -> str:
        p = path_str.lower()
        if "archive/" in p: return "archive"
        if "tests/" in p or os.path.basename(p).startswith("test_"): return "tests"
        if "tools/" in p: return "tools"
        if "docs/" in p: return "docs"
        return "runtime"

    def _infer_role(self, path_str: str) -> Tuple[str, Dict[str, int], List[str]]:
        abs_path = self.repo_root / path_str
        scores = {role: 0 for role in self.ROLE_SIGNALS}
        behavior_tags = []
        
        if not abs_path.exists():
            return "unknown", scores, []

        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content)
            
            # Static Analysis: Imports
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    imports.add(node.module or "")

            # Static Analysis: Keywords in Main-block and top level
            content_lower = content.lower()

            for role, signals in self.ROLE_SIGNALS.items():
                # Score imports
                matching_imports = imports.intersection(signals["imports"])
                scores[role] += len(matching_imports) * signals["weight_import"]
                
                # Score keywords
                for kw in signals["keywords"]:
                    if kw in content_lower:
                        scores[role] += signals["weight_keyword"]

            # Add context for tooling_cli
            if 'if __name__ == "__main__":' in content or "if __name__ == '__main__':" in content:
                 scores["tooling_cli"] += 4

            # Path-based test signal
            if "test_" in path_str.lower() or "/tests/" in path_str.lower():
                scores["test_harness"] += 5

            # Determine primary role
            best_role = max(scores, key=scores.get)
            if scores[best_role] == 0:
                best_role = "unknown"
            
            # Behavior tags (roles with significant scores)
            behavior_tags = [role for role, score in scores.items() if score >= 8]
            
            return best_role, scores, behavior_tags

        except Exception as e:
            return "error", scores, [str(e)]
