import ast
import json
from pathlib import Path
from typing import Set, List

class EntrypointDetector:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.common_entrypoint_names = {
            "main.py", "app.py", "server.py", "run.py", "start.py", "__main__.py",
            "manage.py", "wsgi.py", "asgi.py", "cli.py", "launch.py",
            "index.js", "main.js", "server.js", "start.js", "cli.js"
        }

    def detect_all(self) -> Set[Path]:
        entrypoints = set()
        entrypoints |= self.detect_by_name()
        entrypoints |= self.detect_python_main()
        entrypoints |= self.detect_from_configs()
        return entrypoints

    def detect_by_name(self) -> Set[Path]:
        detected = set()
        for p in self.repo_root.rglob("*"):
            if p.name in self.common_entrypoint_names:
                detected.add(p)
        return detected

    def detect_python_main(self) -> Set[Path]:
        entrypoints = set()
        for py_file in self.repo_root.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.If):
                        if (isinstance(node.test, ast.Compare) and
                            isinstance(node.test.left, ast.Name) and
                            node.test.left.id == "__name__" and
                            len(node.test.ops) == 1 and
                            isinstance(node.test.ops[0], ast.Eq) and
                            len(node.test.comparators) == 1 and
                            isinstance(node.test.comparators[0], ast.Constant) and
                            node.test.comparators[0].value == "__main__"):
                            entrypoints.add(py_file)
                            break
            except Exception:
                continue
        return entrypoints

    def detect_from_configs(self) -> Set[Path]:
        entrypoints = set()
        
        # package.json (Node.js)
        pkg_json = self.repo_root / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
                scripts = data.get("scripts", {})
                for cmd in scripts.values():
                    # Very naive extraction of filenames from scripts
                    for part in cmd.split():
                        if part.endswith((".js", ".ts")):
                            p = self.repo_root / part
                            if p.exists():
                                entrypoints.add(p)
                
                bin_data = data.get("bin", {})
                if isinstance(bin_data, str):
                    p = self.repo_root / bin_data
                    if p.exists():
                        entrypoints.add(p)
                elif isinstance(bin_data, dict):
                    for path in bin_data.values():
                        p = self.repo_root / path
                        if p.exists():
                            entrypoints.add(p)
            except Exception:
                pass

        # Dockerfile
        dockerfile = self.repo_root / "Dockerfile"
        if dockerfile.exists():
            entrypoints |= self.parse_dockerfile(dockerfile)

        # Makefile
        makefile = self.repo_root / "Makefile"
        if makefile.exists():
            entrypoints |= self.parse_makefile(makefile)

        return entrypoints

    def parse_dockerfile(self, path: Path) -> Set[Path]:
        entrypoints = set()
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith(("CMD", "ENTRYPOINT")):
                    # Naive extraction from CMD ["python", "app.py"]
                    if "[" in line and "]" in line:
                        try:
                            # Try to extract the list
                            list_part = line[line.find("["):line.find("]")+1]
                            items = json.loads(list_part)
                            for item in items:
                                if item.endswith((".py", ".js", ".sh")):
                                    p = self.repo_root / item
                                    if p.exists():
                                        entrypoints.add(p)
                        except:
                            pass
                    else:
                        # Non-json format: CMD python app.py
                        parts = line.split()
                        for part in parts[1:]:
                            if part.endswith((".py", ".js", ".sh")):
                                p = self.repo_root / part
                                if p.exists():
                                    entrypoints.add(p)
        except Exception:
            pass
        return entrypoints

    def parse_makefile(self, path: Path) -> Set[Path]:
        entrypoints = set()
        # This is very naive, basically looks for anything that looks like a script execution
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                for part in line.split():
                    if part.endswith((".py", ".js", ".sh")):
                        p = self.repo_root / part
                        if p.exists():
                            entrypoints.add(p)
        except Exception:
            pass
        return entrypoints

if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    detector = EntrypointDetector(root)
    found = detector.detect_all()
    print(f"Found {len(found)} entrypoints:")
    for f in found:
        print(f"  {f.relative_to(root)}")
