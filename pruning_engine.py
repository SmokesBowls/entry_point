import os
import json
from pathlib import Path
from typing import List, Dict, Any, Set

class PruningEngine:
    def __init__(self, repo_root: Path, file_indices: List[Dict[str, Any]], violations: Dict[str, Any], entrypoint_analysis: Dict[str, Any]):
        self.repo_root = repo_root
        self.file_indices = file_indices
        self.violations = violations
        self.entrypoint_analysis = entrypoint_analysis

    def generate_plan(self) -> Dict[str, Any]:
        """
        Categorizes files into full_removal, partial_prune, and move_candidates.
        """
        plan = {
            "full_removal_candidates": self._get_full_removal_folders(),
            "partial_prune_candidates": self._get_partial_prunes(),
            "move_candidates": self._get_move_candidates()
        }
        return plan

    def _get_full_removal_folders(self) -> List[str]:
        """Folders where EVERY file is LEGACY and has 0 coverage."""
        # We'll use the folder health from cartography if we had it here, 
        # but we can derive it from file_indices.
        folder_map = {} # folder -> [status, status, ...]
        for item in self.file_indices:
            path = Path(item["file"])
            folder = str(path.parent)
            if folder == ".": continue
            if folder not in folder_map:
                folder_map[folder] = []
            folder_map[folder].append(item["status"])
            
        full_removals = []
        for folder, statuses in folder_map.items():
            if all(s == "LEGACY" for s in statuses) and "archive/" in folder.lower():
                full_removals.append(folder)
        
        return sorted(full_removals)

    def _get_partial_prunes(self) -> List[Dict[str, Any]]:
        """Folders that are mostly legacy but have some active files."""
        folder_map = {}
        for item in self.file_indices:
            path = Path(item["file"])
            folder = str(path.parent)
            if folder == ".": continue
            if folder not in folder_map:
                folder_map[folder] = []
            folder_map[folder].append(item)

        partials = []
        for folder, items in folder_map.items():
            active = [it["file"] for it in items if it["status"] == "ACTIVE"]
            legacy = [it["file"] for it in items if it["status"] == "LEGACY"]
            
            if active and legacy and "archive/" in folder.lower():
                partials.append({
                    "folder": folder,
                    "files_to_remove": legacy,
                    "files_to_keep": active
                })
        return partials

    def _get_move_candidates(self) -> List[Dict[str, str]]:
        """Active files in archive/ that should be moved to tools/ or runtime/."""
        candidates = []
        active_in_arch = self.violations.get("active_in_archive", [])
        
        for path in active_in_arch:
            # Determine destination based on role (heuristic)
            # Find the classified info for this path
            info = next((e for e in self.entrypoint_analysis.get("classified", []) if e["path"] == path), None)
            
            dest_root = "tools/"
            if info and info.get("role") in ["infrastructure_boot", "core_logic_driver"]:
                dest_root = "runtime/"
            
            # Preserve subpath but strip archive/
            rel_dest = path.replace("archive/", "", 1)
            dest = f"{dest_root}{rel_dest}"
            
            candidates.append({
                "source": path,
                "destination": dest,
                "reason": f"Active {info.get('role') or 'file'} found in archive"
            })
        return candidates

    def generate_script(self, plan: Dict[str, Any]) -> str:
        """Generates a bash script to execute the plan."""
        lines = [
            "#!/bin/bash",
            "# PROPOSED PRUNE SCRIPT - RUN ON A COPY OF THE REPO FIRST",
            "set -e",
            ""
        ]
        
        # 1. Moves first (to save active files before folder nuking)
        if plan["move_candidates"]:
            lines.append("# --- MOVE ACTIVE FILES OUT OF ARCHIVE ---")
            for c in plan["move_candidates"]:
                dest_dir = os.path.dirname(c["destination"])
                lines.append(f"mkdir -p {dest_dir}")
                lines.append(f"mv {c['source']} {c['destination']}")
            lines.append("")

        # 2. Partial Prunes
        if plan["partial_prune_candidates"]:
            lines.append("# --- PARTIAL PRUNES ---")
            for p in plan["partial_prune_candidates"]:
                lines.append(f"# Folder: {p['folder']}")
                for f in p["files_to_remove"]:
                    lines.append(f"rm {f}")
            lines.append("")

        # 3. Full Removals (Only if not already cleared by partials)
        if plan["full_removal_candidates"]:
            lines.append("# --- FULL FOLDER REMOVALS ---")
            for f in plan["full_removal_candidates"]:
                lines.append(f"rm -rf {f}")
            lines.append("")

        lines.append("echo '✅ Prune script completed. Please run tests to verify integrity.'")
        return "\n".join(lines)
