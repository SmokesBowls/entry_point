import re
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Set

class RiskAnalyzer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.risky_patterns = [
            (r"__import__\s*\(", "Dynamic Import"),
            (r"importlib\.import_module\s*\(", "Dynamic Import"),
            (r"exec\s*\(", "Execution of String"),
            (r"eval\s*\(", "Evaluation of String"),
            (r"getattr\s*\(", "Dynamic Attribute Access"),
            (r"setattr\s*\(", "Dynamic Attribute Modification")
        ]

    def scan_risks(self, files: List[str]) -> List[Dict[str, Any]]:
        """Identify code blocks with dynamic loading or execution risks."""
        risks = []
        for file_rel in files:
            p = self.repo_root / file_rel
            if not p.is_file():
                continue
            try:
                content = p.read_text()
                for pattern, risk_name in self.risky_patterns:
                    if re.search(pattern, content):
                        risks.append({
                            "file": file_rel,
                            "type": risk_name,
                            "pattern": pattern
                        })
            except:
                pass
        return risks

    def detect_redundancy(self, files: List[str]) -> Dict[str, List[str]]:
        """Detect identical files and shadowed versioned files."""
        hashes = {}
        redundant = {}
        
        for file_rel in files:
            p = self.repo_root / file_rel
            if not p.is_file():
                continue
            try:
                # Basic content hash (normalized for whitespace)
                content = p.read_text()
                norm_content = "".join(content.split())
                h = hashlib.sha256(norm_content.encode()).hexdigest()
                
                if h in hashes:
                    if h not in redundant:
                        redundant[h] = [hashes[h]]
                    redundant[h].append(file_rel)
                else:
                    hashes[h] = file_rel
            except:
                pass
                
        # Also detect shadowed versioned files (e.g. Engine.py vs Engine_v2.py)
        # This is more heuristic-based.
        
        return redundant

if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    analyzer = RiskAnalyzer(root)
    # Test with itself
    print(analyzer.scan_risks(["main.py", "risk_analyzer.py"]))
