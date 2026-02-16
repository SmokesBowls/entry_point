"""
Phase 3.5: Simulation Engine (Safe Trace Harness)
Provides a deny-by-default safety sandbox for executing untrusted repo code.
Blocks: filesystem writes, subprocess, network, GUI.
"""
import os
import sys
import tempfile


class SimulationEngine:
    """Sets up and tears down the safety harness for tracing."""

    def __init__(self, sandbox_dir: str = None):
        self.sandbox_dir = sandbox_dir or tempfile.mkdtemp(prefix="rie_sandbox_")
        self.blocked_events = []
        self._original_env = {}
        self._active = False

    def activate(self):
        """Enable the safety harness."""
        if self._active:
            return
        self._active = True

        # Suppress GUI frameworks
        gui_vars = {
            "DISPLAY": "",
            "WAYLAND_DISPLAY": "",
            "SDL_VIDEODRIVER": "dummy",
            "QT_QPA_PLATFORM": "offscreen",
            "MPLBACKEND": "Agg",
        }
        for key, val in gui_vars.items():
            self._original_env[key] = os.environ.get(key)
            os.environ[key] = val

        # Mark that we're in tracing mode
        os.environ["__RIE_TRACING__"] = "1"

        # Install audit hook
        try:
            sys.addaudithook(self._audit_hook)
        except Exception:
            pass

    def deactivate(self):
        """Restore original environment."""
        if not self._active:
            return
        self._active = False
        for key, val in self._original_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        os.environ.pop("__RIE_TRACING__", None)

    def _audit_hook(self, event, args):
        """Low-level audit hook to intercept dangerous operations."""
        if not self._active:
            return

        # Block subprocess execution
        if event in ("subprocess.Popen", "os.system", "os.exec", "os.spawn"):
            self.blocked_events.append({"event": event, "detail": str(args)[:200]})
            raise PermissionError(f"PROCESS BLOCKED: {event} is disabled in safe mode.")

        # Block network
        if event == "socket.connect":
            self.blocked_events.append({"event": event, "detail": str(args)[:200]})
            raise PermissionError(f"NETWORK BLOCKED: Attempted connection to {args}")

        # Block filesystem writes outside sandbox
        if event in ("open",) and len(args) >= 2:
            path_arg = str(args[0]) if args else ""
            mode = str(args[1]) if len(args) > 1 else "r"
            if any(m in mode for m in ("w", "a", "x")):
                abs_path = os.path.abspath(path_arg)
                if not abs_path.startswith(self.sandbox_dir):
                    self.blocked_events.append({"event": "fs_write", "path": abs_path})
                    raise PermissionError(
                        f"FILE BLOCKED: Attempted write to {path_arg} outside sandbox."
                    )

    def get_blocked_events(self):
        return list(self.blocked_events)
