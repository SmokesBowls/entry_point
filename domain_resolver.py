import fnmatch
from pathlib import Path
from typing import Dict, List, Any, Optional

class DomainResolver:
    def __init__(self, repo_root: Path, user_rules: Optional[Dict[str, Any]] = None):
        self.repo_root = repo_root
        self.user_rules = user_rules.get("domains", []) if user_rules else []
        
        # Sort user rules by priority (desc), then pattern length (desc)
        # This ensures the most specific/highest priority rule wins.
        # Note: We'll need to flatten patterns for easy sorting if we want pure specificity, 
        # but the spec says "collect all matching rules... sort remaining matches".
        # So we'll iterate and filter during the resolve step.

    def resolve(self, file_path_str: str) -> Dict[str, Any]:
        """Resolves a file path to a defined domain using the 3-tier precedence logic."""
        # Tier 1: User Rules
        matches = []
        for rule in self.user_rules:
            if self._matches_rule(file_path_str, rule):
                matches.append(rule)
        
        if matches:
            # Precedence: 1. Priority (desc), 2. Longest include pattern, 3. Alphabetical name
            # We'll calculate "longest pattern" by taking the max length of all matching includes for that rule
            def sort_key(r):
                matching_includes = [p for p in r.get("include", []) if fnmatch.fnmatch(file_path_str, p)]
                max_len = max(len(p) for p in matching_includes) if matching_includes else 0
                return (-r.get("priority", 0), -max_len, r.get("name", ""))
            
            winner = sorted(matches, key=sort_key)[0]
            return {
                "domain": winner.get("name", "unknown"),
                "intent": winner.get("intent", "unknown"),
                "role_hint": winner.get("role_hint"),
                "source": "user_rule"
            }

        # Tier 2: Built-in Heuristics
        heuristics = [
            (lambda p: "test" in p.lower() or "spec" in p.lower(), "testing", "test"),
            (lambda p: "tool" in p.lower() or "cli" in p.lower() or "bin/" in p.lower(), "tooling", "tools"),
            (lambda p: "core" in p.lower() or "engine" in p.lower() or "runtime" in p.lower() or "main.py" in p.lower() or "launch_" in p.lower(), "core", "runtime"),
            (lambda p: "doc" in p.lower() or "readme" in p.lower(), "documentation", "docs"),
            (lambda p: "config" in p.lower() or "settings" in p.lower(), "configuration", "config"),
            (lambda p: "archive" in p.lower() or "legacy" in p.lower() or "old" in p.lower(), "legacy", "archived")
        ]
        
        for check, name, intent in heuristics:
            if check(file_path_str):
                return {
                    "domain": name,
                    "intent": intent,
                    "source": "heuristic"
                }

        # Tier 3: Fallback (Immediate parent folder)
        p = Path(file_path_str)
        if len(p.parts) > 1:
            domain = p.parts[0] # Use top level folder
            return {
                "domain": domain,
                "intent": "runtime",
                "source": "fallback_folder"
            }

        if file_path_str.endswith(".py"):
            return {
                "domain": "core",
                "intent": "runtime",
                "source": "fallback_root"
            }

        return {
            "domain": "unknown",
            "intent": "unknown",
            "source": "fallback"
        }

    def _matches_rule(self, path: str, rule: Dict[str, Any]) -> bool:
        # Check excludes first
        excludes = rule.get("exclude", [])
        for pattern in excludes:
            if fnmatch.fnmatch(path, pattern):
                return False
        
        # Check includes
        includes = rule.get("include", [])
        for pattern in includes:
            if fnmatch.fnmatch(path, pattern):
                return True
        
        return False
