import ast
from pathlib import Path
from typing import Set, Dict, List

class StaticAnalyzer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def analyze_repo(self) -> Dict[Path, Set[Path]]:
        """
        Scans all Python files in the repo and returns a mapping:
        file_path -> set of imported absolute file paths (within the repo).
        """
        import_map = {}
        for py_file in self.repo_root.rglob("*.py"):
            imports = self.get_imports_from_file(py_file)
            resolved = self.resolve_imports(py_file, imports)
            if resolved:
                import_map[py_file] = resolved
        return import_map

    def get_imports_from_file(self, file_path: Path) -> List[str]:
        """Extracts import names using AST."""
        imports = []
        try:
            tree = ast.parse(file_path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
        except Exception:
            pass
        return imports

    def resolve_imports(self, current_file: Path, import_names: List[str]) -> Set[Path]:
        """
        Attempts to resolve import strings to Paths within the repo.
        This is a simplified resolver.
        """
        resolved_paths = set()
        for name in import_names:
            # Convert dot notation to path parts
            parts = name.split('.')
            
            # Check for package/module in repo relative to root
            potential_path = self.repo_root.joinpath(*parts)
            
            # Case 1: Package (folder with __init__.py)
            if (potential_path / "__init__.py").exists():
                resolved_paths.add((potential_path / "__init__.py").resolve())
            
            # Case 2: Module (.py file)
            module_file = potential_path.with_suffix(".py")
            if module_file.exists():
                resolved_paths.add(module_file.resolve())
                
            # Case 3: Relative imports (not fully handled here, but could be)
            # For simplicity, we mostly focus on imports that can be found from repo root
            # or relative to current file if it's a sibling
            sibling_module = current_file.parent.joinpath(*parts).with_suffix(".py")
            if sibling_module.exists():
                resolved_paths.add(sibling_module.resolve())

        return resolved_paths

if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    analyzer = StaticAnalyzer(root)
    results = analyzer.analyze_repo()
    
    print(f"Analyzed {len(results)} files for static imports.")
    for f, imports in results.items():
        if imports:
            print(f"{f.relative_to(root)} -> {[str(i.relative_to(root)) for i in imports]}")
