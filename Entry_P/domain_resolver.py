"""
Domain Resolver
3-tier domain resolution for files:
  1. User config rules (highest priority) from entrypoint_domains.yml
  2. Built-in heuristics (universal keyword/path matching)
  3. Fallback to top-level folder name

Built-in heuristics are intentionally generic. Project-specific domains
(e.g., game engines, ML pipelines, web frameworks) belong in
entrypoint_domains.yml so this tool works on ANY Python codebase.
"""
import fnmatch
from pathlib import Path

BUILTIN_HEURISTICS = {
    "core_engine": {
        "keywords": ["engine", "runtime", "core", "kernel", "main", "app"],
        "path_patterns": ["**/core/**", "**/engine/**", "**/src/**"],
    },
    "testing": {
        "keywords": ["test", "spec", "fixture", "mock", "conftest"],
        "path_patterns": ["**/tests/**", "**/test/**", "**/spec/**"],
    },
    "documentation": {
        "keywords": ["doc", "readme", "guide", "manual", "example"],
        "path_patterns": ["**/docs/**", "**/doc/**", "**/examples/**"],
    },
    "migration_tools": {
        "keywords": ["migrate", "migration", "upgrade", "convert", "alembic"],
        "path_patterns": ["**/migration*/**", "**/upgrade/**"],
    },
    "configuration": {
        "keywords": ["config", "settings", "env", "setup"],
        "path_patterns": ["**/config/**", "**/conf/**"],
    },
    "cli": {
        "keywords": ["cli", "command", "manage", "console"],
        "path_patterns": ["**/cli/**", "**/commands/**", "**/management/**"],
    },
    "api": {
        "keywords": ["api", "endpoint", "route", "view", "handler", "controller"],
        "path_patterns": ["**/api/**", "**/routes/**", "**/views/**", "**/handlers/**"],
    },
    "data_layer": {
        "keywords": ["model", "schema", "orm", "database", "db", "repository"],
        "path_patterns": ["**/models/**", "**/schemas/**", "**/db/**"],
    },
    "utilities": {
        "keywords": ["util", "helper", "common", "shared", "lib"],
        "path_patterns": ["**/utils/**", "**/helpers/**", "**/lib/**", "**/common/**"],
    },
}

# Intent inference from path
INTENT_RULES = [
    ("archive", ["archive/"]),
    ("tests", ["tests/", "test_"]),
    ("tools", ["tools/"]),
    ("docs", ["docs/", "doc/"]),
]


class DomainResolver:
    def __init__(self, repo_root: Path, user_config: dict = None):
        self.repo_root = repo_root
        self.user_config = user_config or {}

    def resolve(self, rel_path: str) -> dict:
        """
        Resolve domain, intent, and source for a file.
        Returns: {"domain": str, "intent": str, "source": str}
        """
        domain, source = self._resolve_domain(rel_path)
        intent = self._resolve_intent(rel_path)
        return {"domain": domain, "intent": intent, "source": source}

    def _resolve_domain(self, rel_path: str) -> tuple:
        """Returns (domain_name, source) where source is 'user_config', 'heuristic', or 'fallback'."""
        # Tier 1: User config
        user_domains = self.user_config.get("domains", [])
        if isinstance(user_domains, list):
            matching = []
            for rule in user_domains:
                includes = rule.get("include", [])
                excludes = rule.get("exclude", [])
                if self._matches_patterns(rel_path, includes, excludes):
                    matching.append(rule)

            if matching:
                matching.sort(
                    key=lambda r: (r.get("priority", 0), -len(str(r.get("include", [""])[0]))),
                    reverse=True,
                )
                return matching[0]["name"], "user_config"

        # Tier 2: Built-in heuristics
        path_lower = rel_path.lower()
        best_score = 0
        best_domain = None

        for domain, rules in BUILTIN_HEURISTICS.items():
            score = 0
            for kw in rules.get("keywords", []):
                if kw in path_lower:
                    score += 1
            for pat in rules.get("path_patterns", []):
                if fnmatch.fnmatch(rel_path, pat):
                    score += 2
            if score > best_score:
                best_score = score
                best_domain = domain

        if best_domain and best_score >= 1:
            return best_domain, "heuristic"

        # Tier 3: Fallback to top-level folder
        parts = rel_path.split("/")
        if len(parts) > 1:
            return parts[0], "fallback"
        return "root", "fallback"

    def _resolve_intent(self, rel_path: str) -> str:
        """Determine intent from path (archive > tests > tools > docs > runtime)."""
        path_lower = rel_path.lower()
        for intent, markers in INTENT_RULES:
            for marker in markers:
                if marker in path_lower:
                    return intent
        return "runtime"

    @staticmethod
    def _matches_patterns(path: str, includes: list, excludes: list) -> bool:
        """Check if path matches include patterns and doesn't match exclude patterns."""
        matched = any(fnmatch.fnmatch(path, pat) for pat in includes)
        if not matched:
            return False
        excluded = any(fnmatch.fnmatch(path, pat) for pat in excludes)
        return not excluded
