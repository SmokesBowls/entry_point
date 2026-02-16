"""
Phase 4.5: Entrypoint Tagging
Separates Intent (where it should live, based on path) from Role (what it
behaves like, based on AST/keyword scoring). Assigns eligible_for_primary.

Composite scoring uses multiple signals:
  - Graph coverage (how much of the codebase is reachable from this file)
  - Graph centrality (out-degree: how many core modules does this file import)
  - Role scoring (behavioral: boot/driver/cli/test keywords + imports)
  - Naming heuristics (launch_, main.py, server.py, app.py, etc.)
  - __main__ block presence
"""
import ast
import re
from pathlib import Path

# Role scoring signals
ROLE_SIGNALS = {
    "infrastructure_boot": {
        "imports": {"socket", "flask", "fastapi", "http.server", "uvicorn", "aiohttp",
                    "tornado", "bottle", "cherrypy", "gunicorn", "waitress", "starlette",
                    "websockets", "grpc", "xmlrpc"},
        "keywords": {"bind", "listen", "port", "server.start", "run_forever", "serve",
                     "app.run", "uvicorn.run", "serve_forever", "start_server"},
        "import_score": 5,
        "keyword_score": 4,
    },
    "core_logic_driver": {
        "imports": {"rules", "scene", "config", "engine", "state_machine", "kernel",
                    "runtime", "scheduler", "dispatcher", "pipeline", "processor"},
        "keywords": {"load_scene", "evaluate_rule", "run_cycle", "main_loop",
                     "execute_action", "process_frame", "tick", "update", "step",
                     "game_loop", "simulation", "run_engine"},
        "import_score": 5,
        "keyword_score": 4,
    },
    "tooling_cli": {
        "imports": {"argparse", "click", "typer", "fire", "optparse", "getopt"},
        "keywords": {"add_argument", "parse_args", "click.command", "click.group",
                     "typer.run", "fire.Fire", "parser.parse_args"},
        "import_score": 5,
        "keyword_score": 4,
    },
    "test_harness": {
        "imports": {"unittest", "pytest", "nose", "doctest", "hypothesis"},
        "keywords": {"TestCase", "assertEqual", "assert_called", "test_", "fixture",
                     "parametrize", "mock.patch", "PASS", "FAIL"},
        "import_score": 5,
        "keyword_score": 4,
    },
}

# Naming heuristics for engine-like files
ENGINE_NAME_PATTERNS = [
    (re.compile(r'(?:^|/)(?:launch|boot|start)[\w_]*\.py$', re.I), 0.15),
    (re.compile(r'(?:^|/)main\.py$', re.I), 0.10),
    (re.compile(r'(?:^|/)(?:server|app|wsgi|asgi)\.py$', re.I), 0.10),
    (re.compile(r'(?:^|/)(?:run|entry|init)[\w_]*\.py$', re.I), 0.08),
    (re.compile(r'(?:^|/)(?:engine|runtime|driver|core)[\w_]*\.py$', re.I), 0.08),
    (re.compile(r'(?:^|/)sim_runtime[\w_]*\.py$', re.I), 0.10),
]

# Deny patterns -- these should NEVER be engine candidates
DENY_PATTERNS = [
    re.compile(r'(?:^|/)tests?/', re.I),
    re.compile(r'(?:^|/)test_', re.I),
    re.compile(r'(?:^|/)docs?/', re.I),
    re.compile(r'(?:^|/)archive/', re.I),
    re.compile(r'(?:^|/)__pycache__/', re.I),
]

# Intent priority (highest first)
INTENT_PRIORITY = [
    ("archive", lambda p: "archive/" in p.lower() or "archive\\" in p.lower()),
    ("tests", lambda p: "/tests/" in p or p.startswith("tests/") or "/test_" in p.lower() or p.startswith("test_")),
    ("tools", lambda p: "/tools/" in p or p.startswith("tools/")),
    ("docs", lambda p: "/docs/" in p or p.startswith("docs/") or "/doc/" in p or p.startswith("doc/")),
    ("gui", lambda p: "/gui/" in p or p.startswith("gui/")),
]


class EntryTagger:
    def __init__(self, repo_root: Path, triangulation_data: dict = None, 
                 graph: dict = None, trace_meta: dict = None):
        """
        Args:
            repo_root: repository root path
            triangulation_data: output from Triangulator.select_engines()
            graph: adjacency list from GraphEngine (for centrality scoring)
            trace_meta: trace metadata with completeness info (optional)
        """
        self.repo_root = repo_root
        self.triangulation_data = triangulation_data or {}
        self.graph = graph or {}
        self.trace_meta = trace_meta or {}

    def tag_all(self) -> list:
        """
        Tag all entrypoints with intent, role, eligibility, and composite score.
        Returns list of classified entrypoint dicts.
        """
        entries = self.triangulation_data.get("all_ranked", [])
        if not entries:
            entries = self.triangulation_data.get("selected", [])

        trace_partial = self.trace_meta.get("partial", False)
        trace_completeness = self.trace_meta.get("completeness", 1.0)

        classified = []
        for entry in entries:
            path = entry["path"]
            intent = self._get_intent(path)
            role, scores, behavior_tags = self._infer_role(path)
            eligible = self._check_eligible(intent, role)
            denied = self._is_denied(path)

            # If denied by pattern, force ineligible
            if denied:
                eligible = False

            # Composite score: coverage + centrality + naming + role
            coverage_ratio = entry.get("coverage", {}).get("cover_ratio", 0.0)
            centrality = self._compute_centrality(path)
            naming_boost = self._naming_score(path)
            role_boost = self._role_boost(role, scores)
            has_main = self._has_main_block(path)

            # Weighted composite
            composite = (
                coverage_ratio * 0.35 +       # graph reach (trace-dependent)
                centrality * 0.25 +            # how central in import graph (trace-dependent)
                naming_boost * 0.15 +          # filename heuristics (static)
                role_boost * 0.15 +            # behavioral scoring (static)
                (0.10 if has_main else 0.0)    # has __main__ block (static)
            )

            # Static confidence: the portion of the score from deterministic signals
            # If trace is partial, graph-dependent scores may be understated
            static_confidence = naming_boost * 0.15 + role_boost * 0.15 + (0.10 if has_main else 0.0)
            graph_confidence = coverage_ratio * 0.35 + centrality * 0.25

            # Eligibility gate: ineligible files get halved
            if not eligible:
                composite *= 0.3

            classified.append({
                "path": path,
                "coverage": entry.get("coverage", {}),
                "intent_tags": [f"intent:{intent}"],
                "behavior_tags": behavior_tags,
                "role": role,
                "role_scores": scores,
                "eligible_for_primary": eligible,
                "primary_candidate_score": round(composite, 4),
                "in_engine_scope": entry.get("in_engine_scope", True),
                "score_breakdown": {
                    "coverage": round(coverage_ratio, 4),
                    "centrality": round(centrality, 4),
                    "naming": round(naming_boost, 4),
                    "role": round(role_boost, 4),
                    "has_main": has_main,
                    # Trace confidence: static portion is deterministic,
                    # graph portion may be understated if trace was incomplete
                    "static_signal": round(static_confidence, 4),
                    "graph_signal": round(graph_confidence, 4),
                    "trace_partial": trace_partial,
                },
            })

        classified.sort(key=lambda x: -x["primary_candidate_score"])
        return classified

    def _compute_centrality(self, rel_path: str) -> float:
        """
        Compute a 0-1 centrality score based on how many edges this node has.
        High out-degree = imports many things = likely a driver/orchestrator.
        """
        if not self.graph:
            return 0.0
        out_degree = len(self.graph.get(rel_path, set()))
        if out_degree == 0:
            return 0.0
        # Normalize against the max out-degree in the graph
        max_degree = max(len(v) for v in self.graph.values()) if self.graph else 1
        return min(out_degree / max(max_degree, 1), 1.0)

    def _naming_score(self, rel_path: str) -> float:
        """Score based on filename/path heuristics."""
        total = 0.0
        for pattern, boost in ENGINE_NAME_PATTERNS:
            if pattern.search(rel_path):
                total += boost
        return min(total, 1.0)

    def _role_boost(self, role: str, scores: dict) -> float:
        """Convert role scores to a 0-1 boost."""
        if role in ("infrastructure_boot", "core_logic_driver"):
            best = max(scores.values()) if scores else 0
            # 12 is the theoretical max per the scoring table
            return min(best / 12.0, 1.0)
        if role == "tooling_cli":
            return 0.3  # lower boost -- it's a tool, not an engine
        return 0.0

    def _has_main_block(self, rel_path: str) -> bool:
        """Check if file has if __name__ == '__main__'."""
        full_path = self.repo_root / rel_path
        if not full_path.exists() or full_path.suffix != ".py":
            return False
        try:
            source = full_path.read_text(encoding="utf-8", errors="ignore")
            return '__name__' in source and '__main__' in source
        except Exception:
            return False

    def _is_denied(self, rel_path: str) -> bool:
        """Check if a path matches any deny pattern."""
        for pattern in DENY_PATTERNS:
            if pattern.search(rel_path):
                return True
        return False

    def _get_intent(self, rel_path: str) -> str:
        """Determine intent from path."""
        for intent, check in INTENT_PRIORITY:
            if check(rel_path):
                return intent
        return "runtime"

    def _infer_role(self, rel_path: str) -> tuple:
        """
        Infer the behavioral role of a file by scoring it.
        Returns: (role, scores_dict, behavior_tags)
        """
        full_path = self.repo_root / rel_path
        source = ""
        if full_path.exists() and full_path.suffix == ".py":
            try:
                source = full_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        scores = {}
        for role_name, signals in ROLE_SIGNALS.items():
            score = 0

            if source:
                try:
                    tree = ast.parse(source, filename=rel_path)
                    imported_modules = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imported_modules.add(alias.name.split(".")[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imported_modules.add(node.module.split(".")[0])

                    if imported_modules.intersection(signals["imports"]):
                        score += signals["import_score"]
                except (SyntaxError, ValueError):
                    pass

            source_lower = source.lower()
            for kw in signals["keywords"]:
                if kw.lower() in source_lower:
                    score += signals["keyword_score"]
                    break

            if role_name == "test_harness":
                fname = rel_path.split("/")[-1].lower()
                if fname.startswith("test_") or "/tests/" in rel_path.lower():
                    score += 5

            if role_name == "tooling_cli" and 'if __name__' in source:
                has_argparse = 'argparse' in source or 'add_argument' in source
                if has_argparse:
                    score += 4

            scores[role_name] = score

        best_role = max(scores, key=scores.get) if scores else "unknown"
        best_score = scores.get(best_role, 0)

        behavior_tags = []
        for role_name, score in scores.items():
            if score > 0 and (score == best_score or score >= best_score * 0.7):
                behavior_tags.append(f"behavior:{role_name}")

        if best_score == 0:
            fname = rel_path.split("/")[-1].lower()
            if fname.startswith("test_") or "/tests/" in rel_path:
                best_role = "test_harness"
            elif any(kw in rel_path.lower() for kw in ("server", "app", "launch", "boot")):
                best_role = "infrastructure_boot"
            else:
                best_role = "core_logic_driver"

        return best_role, scores, behavior_tags

    @staticmethod
    def _check_eligible(intent: str, role: str) -> bool:
        """Determine if an entrypoint is eligible to be a primary engine candidate."""
        if intent == "archive":
            return False
        if role == "test_harness":
            return False
        if intent in ("tests", "docs"):
            return False
        if intent == "runtime" and role in ("infrastructure_boot", "core_logic_driver"):
            return True
        if intent == "runtime" and role == "tooling_cli":
            return True  # CLI tools can be engine entrypoints
        if intent in ("tools", "gui") and role in ("infrastructure_boot", "core_logic_driver"):
            return True  # tools/gui that behave like engines
        return False
