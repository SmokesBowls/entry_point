import re
from pathlib import Path
from typing import Set

class TextScanner:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        # Relevant extensions for text references
        self.text_extensions = {".md", ".json", ".yaml", ".yml", ".txt", ".cfg", ".tscn", ".gd", ".unity", ".prefab"}

    def scan_all(self, file_list: Set[Path]) -> Set[Path]:
        """
        Scans all text files in the repo for mentions of files in the provided list.
        Returns a set of files that were referenced.
        """
        referenced_files = set()
        
        # Pre-calculate file names and relative paths to look for
        file_names = {p.name: p for p in file_list}
        rel_paths = {str(p.relative_to(self.repo_root)): p for p in file_list}
        
        # Combine into a larger search set
        search_terms = set(file_names.keys()) | set(rel_paths.keys())

        for p in self.repo_root.rglob("*"):
            if p.suffix in self.text_extensions and p.is_file():
                try:
                    content = p.read_text()
                    # Using a simple word-based search for performance
                    # A more robust regex might be needed for specific path patterns
                    for term in search_terms:
                        if term in content:
                            if term in rel_paths:
                                referenced_files.add(rel_paths[term])
                            elif term in file_names:
                                referenced_files.add(file_names[term])
                except Exception:
                    continue
        
        return referenced_files

if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    # Dummy file list for testing: all files in repo
    all_files = {p for p in root.rglob("*") if p.is_file()}
    
    scanner = TextScanner(root)
    found = scanner.scan_all(all_files)
    print(f"Found {len(found)} files referenced in text files.")
    for f in found:
        print(f"  {f.relative_to(root)}")
