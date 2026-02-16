"""
Phase 6: Pruning Engine
Generates a safe, reviewable pruning plan and shell script.
Safety hierarchy: move active files first, then delete legacy, then remove empty folders.
"""
import os
from pathlib import Path
import shutil
import uuid
from collections import defaultdict
from undo_manager import UndoManager


class PruningEngine:
    def __init__(self, repo_root: Path, file_data: list, graph: dict):
        self.repo_root = repo_root
        self.file_data = file_data
        self.graph = graph

    def generate_plan(self, engine_roots: list) -> dict:
        """
        Generate a pruning plan.
        
        Args:
            engine_roots: list of file paths that are engine entrypoints (must preserve)
            
        Returns:
            dict with full_removal_candidates, partial_prune_candidates, move_candidates
        """
        engine_set = set(engine_roots)

        # Classify folders
        folder_files = defaultdict(list)
        for entry in self.file_data:
            parts = entry["file"].split("/")
            folder = "/".join(parts[:-1]) if len(parts) > 1 else "."
            folder_files[folder].append(entry)

        full_removal = []
        partial_prune = []
        move_candidates = []

        # Folders that should never be suggested for full removal
        protected_prefixes = {"docs", "doc", "tests", "test", "tools", ".uacf_undo", "."}

        for folder, files in sorted(folder_files.items()):
            active = [f for f in files if f["status"] == "ACTIVE"]
            legacy = [f for f in files if f["status"] == "LEGACY"]

            # Skip root-level and engine-containing folders
            if folder == ".":
                continue
            if any(f["file"] in engine_set for f in files):
                continue

            # Skip protected folders for full removal
            top_folder = folder.split("/")[0].lower()
            is_protected = top_folder in protected_prefixes

            if not active and legacy and not is_protected:
                # Entire folder is legacy and not protected
                full_removal.append({
                    "folder": folder,
                    "file_count": len(legacy),
                    "files": [f["file"] for f in legacy],
                })
            elif active and legacy:
                # Mixed folder - partial prune
                partial_prune.append({
                    "folder": folder,
                    "files_to_remove": [f["file"] for f in legacy],
                    "files_to_keep": [f["file"] for f in active],
                })

            # Check for active-in-archive that should be moved
            for f in active:
                if "archive/" in f["file"].lower() or f["file"].lower().startswith("archive"):
                    # Suggest moving out of archive
                    dest = self._suggest_destination(f["file"])
                    move_candidates.append({
                        "source": f["file"],
                        "destination": dest,
                        "reason": "active file in archive",
                    })

        return {
            "full_removal_candidates": full_removal,
            "partial_prune_candidates": partial_prune,
            "move_candidates": move_candidates,
            "summary": {
                "folders_to_remove": len(full_removal),
                "files_to_remove": sum(r["file_count"] for r in full_removal) + sum(len(p["files_to_remove"]) for p in partial_prune),
                "files_to_move": len(move_candidates),
            },
        }

    def apply_plan(self, plan: dict, dry_run: bool = False) -> dict:
        """
        Apply the pruning plan using Python operations.
        Logs to UndoManager for traceability and undo support.
        """
        undo = UndoManager(self.repo_root)
        session_id = str(uuid.uuid4())
        results = {
            "session_id": session_id,
            "dry_run": dry_run,
            "actions": []
        }

        print(f"{'[DRY-RUN] ' if dry_run else ''}Applying pruning plan (Session: {session_id[:8]})...")

        # Phase 1: Moves (safety first)
        for m in plan.get("move_candidates", []):
            src = m["source"]
            dst = m["destination"]
            msg = f"Move {src} -> {dst}"
            if dry_run:
                results["actions"].append({"type": "move", "status": "dry_run", "msg": msg})
                print(f"  [DRY] {msg}")
            else:
                success = undo.move_file(src, dst, session_id=session_id)
                results["actions"].append({"type": "move", "status": "done" if success else "failed", "msg": msg})
                print(f"  {'✅' if success else '❌'} {msg}")

        # Phase 2: Partial prunes
        for p in plan.get("partial_prune_candidates", []):
            for f in p["files_to_remove"]:
                msg = f"Delete {f} (partial prune)"
                if dry_run:
                    results["actions"].append({"type": "delete", "status": "dry_run", "msg": msg})
                    print(f"  [DRY] {msg}")
                else:
                    success = undo.move_to_trash(f, session_id=session_id)
                    results["actions"].append({"type": "delete", "status": "done" if success else "failed", "msg": msg})
                    print(f"  {'✅' if success else '❌'} {msg}")

        # Phase 3: Full folder removals
        for r in plan.get("full_removal_candidates", []):
            folder = r["folder"]
            msg = f"Delete folder {folder} ({r['file_count']} files)"
            if dry_run:
                results["actions"].append({"type": "delete_folder", "status": "dry_run", "msg": msg})
                print(f"  [DRY] {msg}")
            else:
                success = undo.move_to_trash(folder, session_id=session_id)
                results["actions"].append({"type": "delete_folder", "status": "done" if success else "failed", "msg": msg})
                print(f"  {'✅' if success else '❌'} {msg}")

        return results

    def materialize(self, plan: dict):
        """
        [STABLE API] Materialize the pruning plan.
        In the current version, this is handled interactively via GUI/CLI,
        so this method serves as a descriptive warning if called in-process.
        """
        print("[WARN] PruningEngine: direct script materialization is deprecated.")
        print("       Use 'uacf clean' or the GUI to apply this plan.")

    def generate_script(self, plan: dict):
        """[COMPATIBILITY SHIM] For legacy calls in main.py"""
        return self.materialize(plan)

    @staticmethod
    def _suggest_destination(archive_path: str) -> str:
        """Suggest a non-archive destination for an active file in archive/."""
        # Remove archive/ prefix and suggest tools/ or runtime/
        parts = archive_path.split("/")
        # Find and remove the 'archive' segment
        clean_parts = [p for p in parts if p.lower() != "archive"]
        
        if any(kw in archive_path.lower() for kw in ("anim", "rig", "asset", "tool")):
            return "tools/" + "/".join(clean_parts)
        return "runtime/" + "/".join(clean_parts)
