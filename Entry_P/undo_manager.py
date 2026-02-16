import os
import json
import shutil
from pathlib import Path
from datetime import datetime
import uuid

class UndoManager:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.undo_dir = repo_root / ".uacf_undo"
        self.ledger_path = self.undo_dir / "ledger.json"
        self.trash_dir = self.undo_dir / "trash"
        
        self.undo_dir.mkdir(exist_ok=True)
        self.trash_dir.mkdir(exist_ok=True)
        
        if not self.ledger_path.exists():
            self._save_ledger([])

    def _load_ledger(self) -> list:
        try:
            with open(self.ledger_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save_ledger(self, ledger: list):
        with open(self.ledger_path, "w") as f:
            json.dump(ledger, f, indent=2)

    def log_operation(self, op_type: str, src: str, dst: str = None, session_id: str = None, status: str = "pending"):
        """
        Record a file operation in the ledger.
        op_type: 'move', 'delete'
        """
        ledger = self._load_ledger()
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id or "default",
            "op_type": op_type,
            "src": src,
            "dst": dst,
            "status": status
        }
        ledger.append(entry)
        self._save_ledger(ledger)
        return entry["id"]

    def update_status(self, op_id: str, status: str):
        ledger = self._load_ledger()
        for entry in ledger:
            if entry["id"] == op_id:
                entry["status"] = status
                break
        self._save_ledger(ledger)

    def move_to_trash(self, rel_path: str, session_id: str = None) -> bool:
        """Move a file or directory to the trash folder instead of deleting."""
        src_path = self.repo_root / rel_path
        if not src_path.exists():
            return False
            
        trash_id = str(uuid.uuid4())
        dst_path = self.trash_dir / trash_id
        
        op_id = self.log_operation("delete", rel_path, dst=f".uacf_undo/trash/{trash_id}", session_id=session_id)
        
        try:
            shutil.move(str(src_path), str(dst_path))
            self.update_status(op_id, "done")
            return True
        except Exception as e:
            self.update_status(op_id, f"failed: {e}")
            return False

    def move_file(self, src_rel: str, dst_rel: str, session_id: str = None) -> bool:
        """Perform a standard move and log it."""
        src_path = self.repo_root / src_rel
        dst_path = self.repo_root / dst_rel
        
        op_id = self.log_operation("move", src_rel, dst_rel, session_id=session_id)
        
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_path), str(dst_path))
            self.update_status(op_id, "done")
            return True
        except Exception as e:
            self.update_status(op_id, f"failed: {e}")
            return False

    def undo_session(self, session_id: str = None) -> dict:
        """Undo the most recent session or a specific session."""
        ledger = self._load_ledger()
        if not ledger:
            return {"status": "error", "message": "No operations in ledger."}
            
        if not session_id:
            # Find the most recent session_id that isn't already 'undone'
            sessions = [e["session_id"] for e in reversed(ledger) if e["status"] == "done"]
            if not sessions:
                return {"status": "error", "message": "No undoable operations found."}
            session_id = sessions[0]
            
        ops_to_undo = [e for e in ledger if e["session_id"] == session_id and e["status"] == "done"]
        # Undo in reverse order
        ops_to_undo.reverse()
        
        results = []
        for op in ops_to_undo:
            success = False
            error = None
            try:
                if op["op_type"] == "move":
                    src = self.repo_root / op["src"]
                    dst = self.repo_root / op["dst"]
                    if dst.exists():
                        src.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(dst), str(src))
                        success = True
                elif op["op_type"] == "delete":
                    src = self.repo_root / op["src"]
                    trash_path = self.repo_root / op["dst"]
                    if trash_path.exists():
                        src.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(trash_path), str(src))
                        success = True
                
                if success:
                    op["status"] = "undone"
                    results.append({"op_id": op["id"], "status": "undone"})
                else:
                    results.append({"op_id": op["id"], "status": "failed", "message": "Source file missing"})
            except Exception as e:
                results.append({"op_id": op["id"], "status": "failed", "message": str(e)})

        self._save_ledger(ledger)
        return {"status": "ok", "session_id": session_id, "results": results}

    def get_history(self, limit: int = 50):
        ledger = self._load_ledger()
        return ledger[-limit:]
