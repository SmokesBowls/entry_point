"""
Risk Analyzer
Detects patterns that could cause false negatives in static analysis:
  - Dynamic imports (__import__, importlib)
  - exec/eval usage
  - File-based loading (config-driven module loading)
  - subprocess calls to Python scripts
"""
import re
from pathlib import Path

IGNORE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "reports"}

# Patterns indicating dynamic loading
DYNAMIC_PATTERNS = [
    (re.compile(r'\b__import__\s*\('), "dynamic_import", "Uses __import__()"),
    (re.compile(r'\bimportlib\.import_module\s*\('), "dynamic_import", "Uses importlib.import_module()"),
    (re.compile(r'\brunpy\.run_module\s*\('), "dynamic_import", "Uses runpy.run_module()"),
    (re.compile(r'\bexec\s*\('), "code_execution", "Uses exec()"),
    (re.compile(r'\beval\s*\('), "code_execution", "Uses eval()"),
    (re.compile(r'\bsubprocess\.\w+\('), "subprocess", "Uses subprocess"),
    (re.compile(r'\bos\.system\s*\('), "subprocess", "Uses os.system()"),
    (re.compile(r'\bos\.popen\s*\('), "subprocess", "Uses os.popen()"),
    (re.compile(r'\bload_source\s*\('), "dynamic_load", "Uses load_source()"),
    (re.compile(r'\bspec_from_file_location\s*\('), "dynamic_load", "Uses spec_from_file_location()"),
]


class RiskAnalyzer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def analyze(self) -> dict:
        """
        Scan all Python files for risky patterns.
        Returns dict of file_rel -> list of risk records.
        """
        risks = {}
        for p in self.repo_root.rglob("*.py"):
            if any(part in IGNORE_DIRS for part in p.parts):
                continue
            try:
                source = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            file_risks = []
            for pattern, category, description in DYNAMIC_PATTERNS:
                matches = list(pattern.finditer(source))
                if matches:
                    file_risks.append({
                        "category": category,
                        "description": description,
                        "count": len(matches),
                        "lines": [self._line_number(source, m.start()) for m in matches[:5]],
                    })

            if file_risks:
                rel = str(p.relative_to(self.repo_root))
                risks[rel] = file_risks

        return risks

    @staticmethod
    def _line_number(source: str, position: int) -> int:
        return source[:position].count("\n") + 1

    def get_summary(self) -> dict:
        """Get a summary of risk patterns across the repo."""
        risks = self.analyze()
        by_category = {}
        for file_risks in risks.values():
            for risk in file_risks:
                cat = risk["category"]
                by_category.setdefault(cat, 0)
                by_category[cat] += risk["count"]

        return {
            "files_with_risks": len(risks),
            "by_category": by_category,
            "high_risk_files": [f for f, r in risks.items() if any(
                ri["category"] in ("code_execution", "dynamic_import") for ri in r
            )],
        }
