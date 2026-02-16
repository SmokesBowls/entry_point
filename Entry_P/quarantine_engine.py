"""
Quarantine Engine -- Controlled Isolation Protocol

Classifies every file in the repo into tiers based on scan evidence,
then generates reversible move scripts with manifests.

Tiers:
  T0 (CORE)    -- Engine entrypoints + their reachable imports. DO NOT TOUCH.
  T1 (PERIPH)  -- Out-of-scope surfaces (gui/, trae/, blender/, etc). Low risk.
  T2 (SHADOW)  -- archive/, *_old.py, *_v1.py, legacy patterns. Medium risk.
  T3 (GHOST)   -- Zero evidence: no imports, no runtime hits, no text refs.

Usage:
  From main.py with --quarantine flag, or standalone:
    q = QuarantineEngine(repo_root, file_data, graph, engine_candidates, engine_scopes)
    plan = q.build_plan()
    q.write_scripts(plan)
"""
import json
import os
import re
from collections import defaultdict
from pathlib import Path


# Patterns that indicate legacy/shadow files
SHADOW_PATTERNS = [
    re.compile(r'_old\.py$', re.I),
    re.compile(r'_v\d+\.py$', re.I),
    re.compile(r'_backup\.py$', re.I),
    re.compile(r'_deprecated\.py$', re.I),
    re.compile(r'_legacy\.py$', re.I),
    re.compile(r'_bak\.py$', re.I),
    re.compile(r'\.bak$', re.I),
    re.compile(r'_copy\.py$', re.I),
    re.compile(r'_orig\.py$', re.I),
]

# Directories that are always periphery (T1) unless in engine scope
DEFAULT_PERIPHERY = {
    "gui", "tools", "scripts", "docs", "doc", "examples", "samples",
    "bench", "benchmark", "vendor", "third_party", "external",
}


class QuarantineEngine:
    def __init__(self, repo_root, file_data, graph, engine_candidates,
                 engine_scopes, engine_target_config=None):
        """
        Args:
            repo_root: Path to repository root
            file_data: list of dicts from Phase 1 (p1_temp_data)
            graph: adjacency dict from GraphEngine
            engine_candidates: list of classified entrypoints (from EntryTagger)
            engine_scopes: list of scope prefixes (e.g. ["godotengain/engainos"])
            engine_target_config: dict from engine_target.yml (optional)
        """
        self.repo_root = Path(repo_root)
        self.file_data = file_data
        self.graph = graph
        self.engine_candidates = engine_candidates
        self.engine_scopes = engine_scopes or ["."]
        self.target_config = engine_target_config or {}

        # Quarantine directory -- OUTSIDE the repo as a sibling
        repo_name = self.repo_root.name
        self.quarantine_dir = self.repo_root.parent / f"_quarantine_{repo_name}"

        # Pre-compute file lookup
        self.file_map = {f["file"]: f for f in file_data}

        # Pre-compute reachable set from engine entrypoints
        self.core_files = self._compute_core_set()

    def _compute_core_set(self):
        """
        BFS from all eligible engine entrypoints through the import graph.
        Everything reachable is T0 (core). Do not touch.
        """
        core = set()

        # Start from engine candidates
        seeds = set()
        for ep in self.engine_candidates:
            if ep.get("eligible_for_primary"):
                seeds.add(ep["path"])

        # BFS through graph
        queue = list(seeds)
        while queue:
            node = queue.pop(0)
            if node in core:
                continue
            core.add(node)
            for neighbor in self.graph.get(node, set()):
                if neighbor not in core:
                    queue.append(neighbor)

        return core

    def build_plan(self):
        """
        Classify every file into a tier and build the quarantine plan.

        Returns dict:
        {
            "t0_core": [...],      # files to KEEP (do not move)
            "t1_periphery": [...], # low-risk moves
            "t2_shadow": [...],    # medium-risk moves
            "t3_ghost": [...],     # zero-evidence files
            "summary": {...}
        }
        """
        t0 = []  # Core -- keep
        t1 = []  # Periphery -- move first
        t2 = []  # Shadow -- move second
        t3 = []  # Ghost -- automated prune

        exclude_dirs = set(self.target_config.get("exclude", []))

        for entry in self.file_data:
            path = entry["file"]
            evidence = entry.get("evidence", [])
            status = entry.get("status", "LEGACY")
            confidence = entry.get("confidence", "LOW")

            tier_info = {
                "file": path,
                "evidence": evidence,
                "status": status,
                "confidence": confidence,
                "domain": entry.get("domain", "unknown"),
            }

            # T0: Core -- reachable from engine entrypoints
            if path in self.core_files:
                tier_info["reason"] = "reachable from engine entrypoint"
                t0.append(tier_info)
                continue

            # T0: Anything in engine scope with HIGH confidence
            in_scope = self._in_engine_scope(path)
            if in_scope and confidence == "HIGH":
                tier_info["reason"] = "in-scope + runtime traced"
                t0.append(tier_info)
                continue

            # T0: Anything in engine scope with evidence
            if in_scope and evidence and status == "ACTIVE":
                tier_info["reason"] = "in-scope + active with evidence"
                t0.append(tier_info)
                continue

            # Check path segments for classification
            parts = path.replace("\\", "/").lower().split("/")
            top_dir = parts[0] if parts else ""

            # T2: Archive or legacy patterns
            if "archive" in parts or self._matches_shadow(path):
                tier_info["reason"] = "archive or legacy pattern"
                t2.append(tier_info)
                continue

            # T1: Explicitly excluded directories
            if top_dir in exclude_dirs:
                tier_info["reason"] = f"excluded by engine_target.yml ({top_dir}/)"
                t1.append(tier_info)
                continue

            # T1: Default periphery directories
            if top_dir in DEFAULT_PERIPHERY:
                tier_info["reason"] = f"periphery directory ({top_dir}/)"
                t1.append(tier_info)
                continue

            # T1: Out of engine scope entirely
            if not in_scope and self.engine_scopes != ["."]:
                tier_info["reason"] = "outside engine scope"
                t1.append(tier_info)
                continue

            # T3: In scope but zero evidence
            if not evidence and status == "LEGACY":
                tier_info["reason"] = "zero evidence (no imports, no runtime, no text refs)"
                t3.append(tier_info)
                continue

            # T0: Everything else in scope with some signal stays
            tier_info["reason"] = "in-scope with partial evidence"
            t0.append(tier_info)

        # Sort each tier by path
        for tier in (t0, t1, t2, t3):
            tier.sort(key=lambda x: x["file"])

        plan = {
            "t0_core": t0,
            "t1_periphery": t1,
            "t2_shadow": t2,
            "t3_ghost": t3,
            "summary": {
                "total_files": len(self.file_data),
                "t0_keep": len(t0),
                "t1_move_low_risk": len(t1),
                "t2_move_med_risk": len(t2),
                "t3_move_zero_evidence": len(t3),
                "total_movable": len(t1) + len(t2) + len(t3),
                "engine_scopes": self.engine_scopes,
                "core_entrypoints": [ep["path"] for ep in self.engine_candidates
                                     if ep.get("eligible_for_primary")],
                "quarantine_dir": str(self.quarantine_dir),
            }
        }
        return plan

    def write_scripts(self, plan, output_dir=None):
        """
        Write quarantine plan, move script, and restore script.

        Files generated:
          reports/quarantine_plan.json  -- full tier breakdown
          reports/quarantine.sh         -- move script (run tier by tier)
          reports/restore.sh            -- instant restore from manifest
        """
        out = Path(output_dir) if output_dir else self.repo_root / "reports"
        out.mkdir(parents=True, exist_ok=True)

        # 1. Write plan JSON
        plan_path = out / "quarantine_plan.json"
        with open(plan_path, "w") as f:
            json.dump(plan, f, indent=2)

        # 2. Write quarantine.sh
        script_path = out / "quarantine.sh"
        self._write_move_script(plan, script_path)

        # 3. Write restore.sh
        restore_path = out / "restore.sh"
        self._write_restore_script(restore_path)

        # 4. Print summary
        s = plan["summary"]
        print(f"\n>> Quarantine Plan\n")
        print(f"   T0 (CORE - keep):       {s['t0_keep']:>4} files")
        print(f"   T1 (periphery - move):  {s['t1_move_low_risk']:>4} files  [low risk]")
        print(f"   T2 (shadow - move):     {s['t2_move_med_risk']:>4} files  [medium risk]")
        print(f"   T3 (ghost - move):      {s['t3_move_zero_evidence']:>4} files  [zero evidence]")
        print(f"   Total movable:          {s['total_movable']:>4} / {s['total_files']} files")
        print()
        print(f"   Quarantine: {self.quarantine_dir}")
        print(f"   (outside repo -- files removed from scan)")
        print()
        print(f"   Core entrypoints (T0 seeds):")
        for ep in s["core_entrypoints"][:5]:
            print(f"     - {ep}")
        print()
        print(f"   Scripts generated:")
        print(f"     {script_path}   -- run tiers: bash quarantine.sh tier1")
        print(f"     {restore_path}  -- undo all:  bash restore.sh")
        print(f"     {plan_path}")

        return plan_path, script_path, restore_path

    def _write_move_script(self, plan, script_path):
        """Generate the quarantine bash script with tier support."""
        lines = [
            "#!/bin/bash",
            "# Quarantine script -- generated by Repository Integrity Engine",
            "# Usage:",
            "#   bash quarantine.sh tier1          # Move periphery (low risk)",
            "#   bash quarantine.sh tier2          # Move shadows (medium risk)",
            "#   bash quarantine.sh tier3          # Move ghosts (zero evidence)",
            "#   bash quarantine.sh all            # Move everything movable",
            "#",
            "# Each tier writes to _quarantine/move_manifest.json for restore.",
            "# Run restore.sh to undo all moves.",
            "",
            'set -e',
            f'REPO_ROOT="{self.repo_root}"',
            f'QUARANTINE_DIR="{self.quarantine_dir}"',
            'MANIFEST="$QUARANTINE_DIR/move_manifest.json"',
            '',
            '# Initialize manifest if it does not exist',
            'mkdir -p "$QUARANTINE_DIR"',
            'if [ ! -f "$MANIFEST" ]; then',
            '    echo "[]" > "$MANIFEST"',
            'fi',
            '',
            'move_file() {',
            '    local src="$1"',
            '    local tier="$2"',
            '    local dst="$QUARANTINE_DIR/$tier/$src"',
            '    if [ ! -e "$REPO_ROOT/$src" ]; then',
            '        return',
            '    fi',
            '    mkdir -p "$(dirname "$dst")"',
            '    mv "$REPO_ROOT/$src" "$dst"',
            '    # Append to manifest',
            "    python3 -c '",
            "import json, sys",
            "with open(sys.argv[1], \"r\") as f: data = json.load(f)",
            'data.append({"src": sys.argv[2], "dst": sys.argv[3], "tier": sys.argv[4]})',
            "with open(sys.argv[1], \"w\") as f: json.dump(data, f, indent=2)",
            "' \"$MANIFEST\" \"$REPO_ROOT/$src\" \"$dst\" \"$tier\"",
            '    echo "  moved: $src"',
            '}',
            '',
        ]

        # Tier 1 function
        lines.append('move_tier1() {')
        lines.append('    echo ">> Moving T1: Periphery (low risk)..."')
        for entry in plan["t1_periphery"]:
            lines.append(f'    move_file "{entry["file"]}" "tier1"')
        lines.append('    echo "  T1 done."')
        lines.append('}')
        lines.append('')

        # Tier 2 function
        lines.append('move_tier2() {')
        lines.append('    echo ">> Moving T2: Shadows (medium risk)..."')
        for entry in plan["t2_shadow"]:
            lines.append(f'    move_file "{entry["file"]}" "tier2"')
        lines.append('    echo "  T2 done."')
        lines.append('}')
        lines.append('')

        # Tier 3 function
        lines.append('move_tier3() {')
        lines.append('    echo ">> Moving T3: Ghosts (zero evidence)..."')
        for entry in plan["t3_ghost"]:
            lines.append(f'    move_file "{entry["file"]}" "tier3"')
        lines.append('    echo "  T3 done."')
        lines.append('}')
        lines.append('')

        # Main dispatch
        lines.extend([
            'case "${1:-help}" in',
            '    tier1) move_tier1 ;;',
            '    tier2) move_tier2 ;;',
            '    tier3) move_tier3 ;;',
            '    all)',
            '        move_tier1',
            '        move_tier2',
            '        move_tier3',
            '        ;;',
            '    *)',
            '        echo "Usage: bash quarantine.sh [tier1|tier2|tier3|all]"',
            '        echo ""',
            f'        echo "  tier1: {len(plan["t1_periphery"])} files (periphery, low risk)"',
            f'        echo "  tier2: {len(plan["t2_shadow"])} files (shadows, medium risk)"',
            f'        echo "  tier3: {len(plan["t3_ghost"])} files (ghosts, zero evidence)"',
            f'        echo "  all:   {plan["summary"]["total_movable"]} files total"',
            '        ;;',
            'esac',
            '',
            'echo ""',
            'echo "Manifest updated: $MANIFEST"',
            'echo "To undo: bash restore.sh"',
        ])

        with open(script_path, "w") as f:
            f.write("\n".join(lines) + "\n")

    def _write_restore_script(self, restore_path):
        """Generate the restore bash script."""
        lines = [
            "#!/bin/bash",
            "# Restore script -- reverses all quarantine moves",
            "# Generated by Repository Integrity Engine",
            "",
            'set -e',
            f'REPO_ROOT="{self.repo_root}"',
            f'MANIFEST="{self.quarantine_dir}/move_manifest.json"',
            '',
            'if [ ! -f "$MANIFEST" ]; then',
            '    echo "No manifest found at $MANIFEST"',
            '    echo "Nothing to restore."',
            '    exit 1',
            'fi',
            '',
            'echo ">> Restoring from manifest..."',
            '',
            'python3 << \'PYEOF\'',
            'import json, shutil, os',
            f'manifest_path = "{self.quarantine_dir}/move_manifest.json"',
            'with open(manifest_path, "r") as f:',
            '    moves = json.load(f)',
            '',
            'if not moves:',
            '    print("Manifest is empty. Nothing to restore.")',
            '    exit()',
            '',
            '# Reverse order so deepest paths restore first',
            'for m in reversed(moves):',
            '    src = m["src"]',
            '    dst = m["dst"]',
            '    if not os.path.exists(dst):',
            '        print(f"  skip (missing): {dst}")',
            '        continue',
            '    os.makedirs(os.path.dirname(src), exist_ok=True)',
            '    shutil.move(dst, src)',
            '    print(f"  restored: {os.path.basename(src)}")',
            '',
            '# Clear manifest',
            'with open(manifest_path, "w") as f:',
            '    json.dump([], f)',
            '',
            'print(f"\\nRestored {len(moves)} items.")',
            'print("Manifest cleared.")',
            'PYEOF',
            '',
            'echo ">> Restore complete."',
        ]

        with open(restore_path, "w") as f:
            f.write("\n".join(lines) + "\n")

    def _in_engine_scope(self, path):
        """Check if a path is within any engine scope."""
        if self.engine_scopes == ["."]:
            return True
        return any(path == s or path.startswith(s + "/") for s in self.engine_scopes)

    def _matches_shadow(self, path):
        """Check if a file matches shadow/legacy naming patterns."""
        for pattern in SHADOW_PATTERNS:
            if pattern.search(path):
                return True
        return False

    # --- Python-native move/restore (no bash scripts) ---

    def _ledger_path(self):
        """Path to the transaction ledger in quarantine directory."""
        return self.quarantine_dir / ".rie_ledger.json"

    def _load_ledger(self):
        """Load or initialize the transaction ledger."""
        lp = self._ledger_path()
        if lp.exists():
            try:
                with open(lp, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"version": 1, "moves": [], "created": None}

    def _save_ledger(self, ledger):
        """Atomically write the transaction ledger."""
        import shutil as _shutil
        lp = self._ledger_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        tmp = lp.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(ledger, f, indent=2)
        _shutil.move(str(tmp), str(lp))

    def apply(self, plan, tiers=None, dry_run=False):
        """
        Move files using Python shutil -- no bash scripts.
        
        Args:
            plan: output from build_plan()
            tiers: list of tiers to move, e.g. ["t3"] or ["t1", "t2", "t3"]
                   Default: ["t3"] (safest first)
            dry_run: if True, return what would be moved without touching files
            
        Returns:
            dict with moved files, errors, and ledger state
        """
        import shutil as _shutil
        from datetime import datetime as _dt

        if tiers is None:
            tiers = ["t3"]

        # Normalize tier names
        tier_map = {"tier1": "t1", "tier2": "t2", "tier3": "t3",
                    "t1": "t1", "t2": "t2", "t3": "t3"}
        normalized = []
        for t in tiers:
            nt = tier_map.get(t.lower(), t.lower())
            if nt in ("t1", "t2", "t3"):
                normalized.append(nt)
        if not normalized:
            return {"error": "No valid tiers specified", "moved": [], "errors": []}

        # Collect files to move
        tier_key_map = {"t1": "t1_periphery", "t2": "t2_shadow", "t3": "t3_ghost"}
        files_to_move = []
        for tier in normalized:
            key = tier_key_map.get(tier, "")
            # Plan may have tiers at top level or nested under "tiers"
            tier_files = plan.get("tiers", {}).get(key, []) or plan.get(key, [])
            for fp in tier_files:
                path = fp if isinstance(fp, str) else fp.get("file", fp.get("path", ""))
                if path:
                    files_to_move.append((path, tier))

        if dry_run:
            return {
                "dry_run": True,
                "would_move": len(files_to_move),
                "tiers": normalized,
                "files": [{"file": f, "tier": t} for f, t in files_to_move[:100]],
            }

        # Load ledger
        ledger = self._load_ledger()
        if not ledger.get("created"):
            try:
                from datetime import timezone as _tz
                ledger["created"] = _dt.now(_tz.utc).isoformat()
            except ImportError:
                ledger["created"] = _dt.utcnow().isoformat() + "Z"

        moved = []
        errors = []
        skipped = 0

        for file_path, tier in files_to_move:
            src = self.repo_root / file_path
            dst = self.quarantine_dir / tier / file_path

            if not src.exists():
                skipped += 1
                continue

            try:
                # Check permissions
                if not os.access(str(src), os.W_OK):
                    errors.append({"file": file_path, "error": "Permission denied"})
                    continue

                # Check for collision at destination
                if dst.exists():
                    errors.append({"file": file_path, "error": "Destination exists"})
                    continue

                # Create destination directory
                dst.parent.mkdir(parents=True, exist_ok=True)

                # Move
                _shutil.move(str(src), str(dst))

                # Record in ledger
                ledger["moves"].append({
                    "src": str(src),
                    "dst": str(dst),
                    "rel": file_path,
                    "tier": tier,
                    "timestamp": _dt.utcnow().isoformat() + "Z",
                })

                moved.append(file_path)

            except Exception as e:
                errors.append({"file": file_path, "error": str(e)})

        # Save ledger after all moves (atomic write)
        self._save_ledger(ledger)

        # Clean up empty directories left behind
        self._cleanup_empty_dirs()

        return {
            "moved": moved,
            "moved_count": len(moved),
            "skipped": skipped,
            "errors": errors,
            "error_count": len(errors),
            "tiers": normalized,
            "ledger_path": str(self._ledger_path()),
        }

    def restore(self, count=None):
        """
        Restore files from quarantine using the transaction ledger.
        
        Args:
            count: number of most recent moves to restore (None = restore all)
            
        Returns:
            dict with restored files and errors
        """
        import shutil as _shutil

        ledger = self._load_ledger()
        moves = ledger.get("moves", [])
        if not moves:
            return {"restored": [], "error": "Ledger is empty -- nothing to restore"}

        # Restore in reverse order (most recent first)
        to_restore = moves[-count:] if count else moves
        to_restore = list(reversed(to_restore))

        restored = []
        errors = []

        for entry in to_restore:
            src_path = Path(entry["src"])
            dst_path = Path(entry["dst"])

            if not dst_path.exists():
                errors.append({"file": entry["rel"], "error": "Not in quarantine"})
                continue

            try:
                src_path.parent.mkdir(parents=True, exist_ok=True)
                _shutil.move(str(dst_path), str(src_path))
                restored.append(entry["rel"])
                # Remove from ledger
                if entry in ledger["moves"]:
                    ledger["moves"].remove(entry)
            except Exception as e:
                errors.append({"file": entry["rel"], "error": str(e)})

        self._save_ledger(ledger)

        return {
            "restored": restored,
            "restored_count": len(restored),
            "errors": errors,
            "remaining_in_quarantine": len(ledger["moves"]),
        }

    def _cleanup_empty_dirs(self):
        """Remove empty directories left behind after moves."""
        import os as _os
        for dirpath, dirnames, filenames in _os.walk(str(self.repo_root), topdown=False):
            if not dirnames and not filenames:
                try:
                    dp = Path(dirpath)
                    if dp != self.repo_root and ".git" not in dp.parts:
                        dp.rmdir()
                except OSError:
                    pass
