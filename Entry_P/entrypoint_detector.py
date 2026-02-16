"""
Phase 1: Entrypoint Detection
Finds all potential entrypoints in a repository using multiple heuristics:
  - Python files with `if __name__ == "__main__"` blocks
  - Config-referenced scripts (Dockerfile, Makefile, package.json, pyproject.toml)
  - Filename heuristics (main.py, run.py, server.py, app.py, cli.py, launch*.py)
"""
import ast
import re
import json
from pathlib import Path

IGNORE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "reports", ".tox", ".mypy_cache"}

HEURISTIC_NAMES = {
    "main.py", "app.py", "run.py", "server.py", "cli.py", "manage.py",
    "wsgi.py", "asgi.py", "setup.py", "__main__.py",
}

HEURISTIC_PREFIXES = ("launch", "start", "boot", "entry", "run_")


class EntrypointDetector:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def detect_all(self) -> set:
        """Returns a set of Path objects that are candidate entrypoints."""
        entrypoints = set()
        entrypoints.update(self._detect_main_blocks())
        entrypoints.update(self._detect_config_refs())
        entrypoints.update(self._detect_heuristic_names())
        return entrypoints

    def _py_files(self):
        for p in self.repo_root.rglob("*.py"):
            if any(part in IGNORE_DIRS for part in p.parts):
                continue
            yield p

    def _detect_main_blocks(self) -> set:
        """Find Python files containing `if __name__ == '__main__'`."""
        found = set()
        for p in self._py_files():
            try:
                source = p.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source, filename=str(p))
                for node in ast.walk(tree):
                    if isinstance(node, ast.If):
                        if self._is_main_check(node):
                            found.add(p)
                            break
            except (SyntaxError, UnicodeDecodeError, ValueError):
                continue
        return found

    @staticmethod
    def _is_main_check(node: ast.If) -> bool:
        """Check if an If node is `if __name__ == '__main__'`."""
        test = node.test
        if isinstance(test, ast.Compare):
            left = test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                for comp in test.comparators:
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        return True
            # Reverse: '__main__' == __name__
            if len(test.comparators) == 1:
                comp = test.comparators[0]
                if isinstance(comp, ast.Name) and comp.id == "__name__":
                    if isinstance(left, ast.Constant) and left.value == "__main__":
                        return True
        return False

    def _detect_config_refs(self) -> set:
        """Find entrypoints referenced in Dockerfile, Makefile, package.json, pyproject.toml."""
        found = set()
        config_files = [
            self.repo_root / "Dockerfile",
            self.repo_root / "Makefile",
            self.repo_root / "package.json",
            self.repo_root / "pyproject.toml",
            self.repo_root / "setup.cfg",
            self.repo_root / "Procfile",
        ]
        py_pattern = re.compile(r'[\w/\\.-]+\.py')

        for cfg in config_files:
            if cfg.exists():
                try:
                    text = cfg.read_text(encoding="utf-8", errors="ignore")
                    for match in py_pattern.findall(text):
                        candidate = self.repo_root / match
                        if candidate.exists():
                            found.add(candidate.resolve())
                except Exception:
                    continue

        # Also check package.json scripts
        pkg_json = self.repo_root / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                for val in scripts.values():
                    for match in py_pattern.findall(val):
                        candidate = self.repo_root / match
                        if candidate.exists():
                            found.add(candidate.resolve())
            except Exception:
                pass

        return found

    def _detect_heuristic_names(self) -> set:
        """Find files with common entrypoint names."""
        found = set()
        for p in self._py_files():
            name = p.name.lower()
            if name in HEURISTIC_NAMES:
                found.add(p)
            elif any(name.startswith(prefix) for prefix in HEURISTIC_PREFIXES):
                found.add(p)
        return found
