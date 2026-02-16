"""
Phase 1: Text Reference Scanner
Scans non-code files (docs, configs, assets) for references to code files.
Catches things like Godot .tscn/.gd references, Markdown mentions, etc.
"""
import re
from pathlib import Path

IGNORE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "reports", ".tox"}

# Extensions to scan for references
SCANNABLE_EXTS = {
    ".txt", ".md", ".rst", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini",
    ".tscn", ".tres", ".gd", ".godot", ".import",
    ".html", ".xml", ".csv",
    ".sh", ".bat", ".ps1",
    ".dockerfile", ".env",
}

# Extensions that represent code files we might find references TO
CODE_EXTS = {".py", ".gd", ".js", ".ts", ".rs", ".go", ".java", ".cs", ".rb", ".lua"}


class TextScanner:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def scan_all(self, all_files: set) -> dict:
        """
        Scan text files for references to code files.
        
        Args:
            all_files: set of Path objects (all files in the repo)
            
        Returns:
            dict mapping referenced file relative path -> list of reference records
        """
        # Build a lookup of known file relative paths
        known_paths = set()
        known_stems = {}  # stem -> [relative paths]
        for f in all_files:
            try:
                rel = f.relative_to(self.repo_root).as_posix()
                known_paths.add(rel)
                stem = f.stem
                known_stems.setdefault(stem, []).append(rel)
            except ValueError:
                continue

        references = {}

        for f in all_files:
            if any(part in IGNORE_DIRS for part in f.parts):
                continue
            if f.suffix.lower() not in SCANNABLE_EXTS:
                continue

            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            scanner_rel = str(f.relative_to(self.repo_root))

            # Strategy 1: Direct path mentions
            for known in known_paths:
                if known in text and known != scanner_rel:
                    references.setdefault(known, []).append({
                        "kind": "text_reference",
                        "referrer": scanner_rel,
                        "match_type": "path",
                    })

            # Strategy 2: Module-style references (e.g., "core.engine" -> "core/engine.py")
            module_pattern = re.compile(r'\b([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+)\b')
            for match in module_pattern.finditer(text):
                mod = match.group(1)
                # Convert dotted path to file path
                as_path = mod.replace(".", "/") + ".py"
                if as_path in known_paths and as_path != scanner_rel:
                    references.setdefault(as_path, []).append({
                        "kind": "text_reference",
                        "referrer": scanner_rel,
                        "match_type": "module_dot",
                    })

        return references
