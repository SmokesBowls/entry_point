import json
import shutil
from pathlib import Path
from typing import Set, Dict, List, Any

class Reporter:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.report_dir = self.repo_root / "reports"
        if not self.report_dir.exists():
            self.report_dir.mkdir(parents=True)

    def generate(self, 
                 all_files: Set[Path], 
                 runtime_files: Set[Path], 
                 static_imports: Dict[Path, Set[Path]], 
                 text_refs: Set[Path],
                 file_indices: List[Dict[str, Any]],
                 phase_two_data: Dict[str, Any] = None,
                 cartography_data: Dict[str, Any] = None,
                 triangulation_data: Dict[str, Any] = None,
                 policy_data: Dict[str, Any] = None,
                 metadata: Dict[str, Any] = None) -> Path:
        """
        Generates usage_index.json refactored into Evidence, Structure, Entrypoints, and Policy.
        """
        # Flatten static imports
        static_imported_files = set()
        for imports in static_imports.values():
            static_imported_files.update(imports)

        files_info = []
        summary = {
            "total_files": len(all_files),
            "core_active": 0,
            "secondary_active": 0,
            "weakly_referenced": 0,
            "likely_legacy": 0,
            "safe_to_remove": 0
        }

        for item in file_indices:
            file_path = self.repo_root / item["file"]
            rel_path = item["file"]
            evidence = item.get("evidence", [])
            confidence = item.get("confidence", "LOW")
            status = item.get("status", "LEGACY")
            
            # Safe to remove check from phase two
            if phase_two_data and rel_path in phase_two_data.get("safe_reduction", {}):
                summary["safe_to_remove"] += 1

            files_info.append({
                "file": rel_path,
                "confidence": confidence,
                "evidence": evidence,
                "status": status,
                "domain": item.get("domain", "unknown"),
                "intent": item.get("intent", "unknown"),
                "domain_source": item.get("domain_source", "unknown")
            })

        report_data = {
            "metadata": metadata or {},
            "summary": summary,
            "evidence": {
                "runtime_files": [str(f.relative_to(self.repo_root)) for f in runtime_files],
                "static_imports": {str(k.relative_to(self.repo_root)): [str(v.relative_to(self.repo_root)) for v in vs] for k, vs in static_imports.items()},
                "text_references": [str(f.relative_to(self.repo_root)) for f in text_refs],
                "all_files": files_info
            },
            "structure": {
                "graph": phase_two_data.get("graph", {}) if phase_two_data else {},
                "folders": cartography_data.get("folders", {}) if cartography_data else {},
                "domains": cartography_data.get("domains", {}) if cartography_data else {},
                "risks": phase_two_data.get("risks", []) if phase_two_data else {},
                "redundancy": phase_two_data.get("redundancy", {}) if phase_two_data else {}
            },
            "entrypoints": triangulation_data or {},
            "policy": policy_data or {}
        }

        output_file = self.report_dir / "usage_index.json"
        with open(output_file, "w") as f:
            json.dump(report_data, f, indent=2)
        
        # Copy HTML viewer template
        try:
            viewer_src = Path(__file__).parent / "reports" / "report_viewer.html"
            viewer_dst = self.report_dir / "index.html"
            if viewer_src.exists():
                shutil.copy(viewer_src, viewer_dst)
        except Exception:
            pass # Non-critical
        
        return output_file

if __name__ == "__main__":
    # Test dummy generator
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    reporter = Reporter(root)
    reporter.generate(set(), set(), {}, set())
