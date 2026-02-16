"""
Phase 1: Static AST Analysis
Parses all Python files to find import statements and build an import graph.
Returns the set of files that are imported by other files in the repo.
"""
import ast
import os
from pathlib import Path

IGNORE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "reports", ".tox", ".mypy_cache"}


class StaticAnalyzer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._module_map = {}  # module_name -> Path
        self._edges = []       # (importer_path, imported_path)
        self._build_module_map()

    def _py_files(self):
        for p in self.repo_root.rglob("*.py"):
            if any(part in IGNORE_DIRS for part in p.parts):
                continue
            yield p

    def _build_module_map(self):
        """Build mapping from dotted module names to file paths."""
        for p in self._py_files():
            rel = p.relative_to(self.repo_root)
            parts = list(rel.parts)
            # Convert path to module name
            if parts[-1] == "__init__.py":
                mod_name = ".".join(parts[:-1])
            else:
                parts[-1] = parts[-1].rsplit(".", 1)[0]  # strip .py
                mod_name = ".".join(parts)

            if mod_name:
                self._module_map[mod_name] = p
                # Also register the leaf name alone for fallback resolution
                leaf = parts[-1]
                if leaf not in self._module_map:
                    self._module_map[leaf] = p

    def _resolve_import(self, module_name: str, importer: Path = None) -> Path | None:
        """Resolve a module name to a file path in the repo."""
        # Direct lookup
        if module_name in self._module_map:
            return self._module_map[module_name]

        # Try prefix matching (e.g., "core.engine" when import is "core.engine.func")
        parts = module_name.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in self._module_map:
                return self._module_map[candidate]

        # Try relative resolution from importer's package
        if importer:
            importer_dir = importer.parent
            for i in range(len(parts), 0, -1):
                candidate_path = importer_dir / "/".join(parts[:i])
                if candidate_path.with_suffix(".py").exists():
                    return candidate_path.with_suffix(".py")
                init = candidate_path / "__init__.py"
                if init.exists():
                    return init

        return None

    def analyze_repo(self) -> set:
        """
        Analyze all Python files for imports.
        Returns the set of Paths that are statically imported by other files.
        Also populates self._edges as (importer, imported) tuples.
        """
        imported_files = set()
        self._edges = []

        for p in sorted(self._py_files()):
            try:
                source = p.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source, filename=str(p))
            except (SyntaxError, ValueError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = self._resolve_import(alias.name, p)
                        if target and target != p:
                            imported_files.add(target)
                            self._edges.append((p, target))
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    # Handle relative imports (level > 0)
                    if node.level > 0:
                        target = self._resolve_relative_import(node.level, module_name, p)
                    else:
                        target = self._resolve_import(module_name, p)
                        
                    if target and target != p:
                        imported_files.add(target)
                        self._edges.append((p, target))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        target = self._resolve_import(node.args[0].value, p)
                        if target and target != p:
                            imported_files.add(target)
                            self._edges.append((p, target))

        # Ensure deterministic edge order
        self._edges = sorted(list(set(self._edges)))
        return imported_files

    def _resolve_relative_import(self, level: int, module: str, importer: Path) -> Path | None:
        """Resolve a 'from ..module import X' style relative import."""
        # Find the base directory based on level
        base = importer.parent
        for _ in range(level - 1):
            base = base.parent
            if base == self.repo_root.parent: # Safety break
                return None
        
        # Now try to resolve module inside base
        if not module:
            # from . import X
            init = base / "__init__.py"
            return init if init.exists() else None
        
        parts = module.split(".")
        target_path = base / "/".join(parts)
        
        # Check for file.py or folder/__init__.py
        py_file = target_path.with_suffix(".py")
        if py_file.exists():
            return py_file
        
        init_file = target_path / "__init__.py"
        if init_file.exists():
            return init_file
            
        return None

    def get_edges(self) -> list:
        """Return the import edges as list of (Path, Path) tuples."""
        return list(self._edges)

    def get_imports_for(self, filepath: Path) -> list:
        """Get all files imported by a given file."""
        return [target for src, target in self._edges if src == filepath]
