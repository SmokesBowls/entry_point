import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Set, List, Dict, Any, Tuple

class RuntimeTracer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.trace_log_path = self.repo_root / "reports" / "runtime_trace.log"

    def run_trace(
        self,
        entrypoints: List[Path],
        safe: bool = True,
        default_timeout: int = 60,
        boot_timeout: int = 180,
        trace_mode: str = "full",
        entrypoint_hints: Dict[str, str] = None,
    ) -> Tuple[Set[Path], List[Tuple[str, int, str, str, int]], Dict[str, Any]]:
        """
        Runs the given entrypoints with a hardened sitecustomize.py tracer.
        Returns a set of all files loaded during execution.
        """
        if not self.trace_log_path.parent.exists():
            self.trace_log_path.parent.mkdir(parents=True)
        
        if self.trace_log_path.exists():
            self.trace_log_path.unlink()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            sandbox_path = tmpdir_path / "sandbox"
            sandbox_path.mkdir()
            site_py = tmpdir_path / "sitecustomize.py"
            
            # Load allowlist if it exists
            allowlist = {"permitted_paths": [], "permitted_domains": []}
            allowlist_path = self.repo_root / "allowlist.yml"
            if allowlist_path.exists():
                try:
                    import yaml
                    with open(allowlist_path, "r") as f:
                        allowlist = yaml.safe_load(f)
                except:
                    pass

            # sitecustomize.py payload with relational tracing and simulation mode
            payload = f"""
import builtins
import sys
import os
import shutil
import subprocess
import socket
import io
import inspect
from pathlib import Path

# --- Configuration ---
trace_log = Path(r"{self.trace_log_path}")
repo_root = Path(r"{self.repo_root}")
sandbox_root = Path(r"{sandbox_path}")
safe_mode = {safe}
allowlist = {allowlist}

# Shared state for deduplication and hit counts
_hit_buffer = {{}} # (caller_path, line, sym, callee) -> count
repo_root_str = str(repo_root)

def _log_hit(callee):
    try:
        # Relational discovery: identify the caller using fast frame traversal
        caller_path = "unknown"
        caller_line = 0
        caller_symbol = "unknown"
        frame = sys._getframe(1)
        while frame:
            f_path = frame.f_code.co_filename
            if f_path and not f_path.endswith('sitecustomize.py'):
                try:
                    p = Path(f_path).resolve()
                    p_str = str(p)
                    if p_str.startswith(repo_root_str):
                        caller_path = p_str[len(repo_root_str):].lstrip(os.sep)
                        caller_line = frame.f_lineno
                        caller_symbol = frame.f_code.co_name
                        break
                except:
                    pass
            frame = frame.f_back
        
        callee_rel = f"ext:{{callee}}"
        try:
            p_callee = Path(callee).resolve()
            p_callee_str = str(p_callee)
            if p_callee_str.startswith(repo_root_str):
                callee_rel = p_callee_str[len(repo_root_str):].lstrip(os.sep)
            else:
                if str(callee).startswith("INTENDED_"):
                    callee_rel = str(callee)
        except:
            pass

        key = (caller_path, caller_line, caller_symbol, callee_rel)
        _hit_buffer[key] = _hit_buffer.get(key, 0) + 1
    except:
        pass

# --- Safety Simulation Mode ---
if safe_mode:
    def is_allowed_write(path):
        try:
            p = Path(path).resolve()
            # Check allowlist
            for allowed in allowlist.get("permitted_paths", []):
                if p.is_relative_to(Path(allowed).resolve() if Path(allowed).is_absolute() else (repo_root / allowed).resolve()):
                    return True
            return p.is_relative_to(sandbox_root) or p.is_relative_to(repo_root / "reports")
        except:
            return False

    # 1. Mock Filesystem
    original_open = builtins.open
    def safe_open(file, mode="r", *args, **kwargs):
        if any(m in mode for m in "wax+"):
            if not is_allowed_write(file):
                _log_hit(f"INTENDED_WRITE: {{file}}")
                return io.StringIO()
        
        res = original_open(file, mode, *args, **kwargs)
        if hasattr(res, 'name'):
            _log_hit(res.name)
        return res
    builtins.open = safe_open

    # 2. Mock Process execution
    def mock_run(*args, **kwargs):
        _log_hit(f"INTENDED_PROC: {{args}}")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
    
    subprocess.run = mock_run
    subprocess.Popen = lambda *args, **kwargs: mock_run(*args, **kwargs)
    os.system = lambda cmd: _log_hit(f"INTENDED_SYSTEM: {{cmd}}") or 0

    # 3. Mock Network
    original_connect = socket.socket.connect
    def mock_connect(self, address):
        # Check allowlist for domains
        host = address[0] if isinstance(address, tuple) else address
        if host in allowlist.get("permitted_domains", []):
            return original_connect(self, address)
        
        _log_hit(f"INTENDED_NET: {{address}}")
        return None
    socket.socket.connect = mock_connect

# --- Relational Import Tracker ---
original_import = builtins.__import__
def tracked_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = original_import(name, globals, locals, fromlist, level)
    if hasattr(module, "__file__") and module.__file__:
        _log_hit(module.__file__)
    return module
builtins.__import__ = tracked_import

# --- Final Flush at Exit ---
import atexit
def flush_trace():
    try:
        if _hit_buffer:
            with original_open(trace_log, "a") as f:
                for (c_path, c_line, c_sym, callee), count in _hit_buffer.items():
                    f.write(f"{{c_path}}:{{c_line}}:{{c_sym}} -> {{callee}} [{{count}}]\\n")
    except:
        pass
atexit.register(flush_trace)
"""
            site_py.write_text(payload)

            # --- Headless & Environment Suppression ---
            env = os.environ.copy()
            env.update({
                "PYTHONPATH": str(tmpdir_path) + os.pathsep + env.get("PYTHONPATH", ""),
                "DISPLAY": "",
                "WAYLAND_DISPLAY": "",
                "SDL_VIDEODRIVER": "dummy",
                "QT_QPA_PLATFORM": "offscreen",
                "MPLBACKEND": "Agg",
                "PYGAME_HIDE_SUPPORT_PROMPT": "1",
                "CI": "1",
                "HOME": str(sandbox_path),
                "XDG_CONFIG_HOME": str(sandbox_path / ".config"),
                "XDG_CACHE_HOME": str(sandbox_path / ".cache"),
                "XDG_DATA_HOME": str(sandbox_path / ".local" / "share"),
                "__RIE_TRACING__": "1"
            })

            loaded_files = set()
            trace_meta = {
                "trace_mode": trace_mode,
                "default_timeout": default_timeout,
                "boot_timeout": boot_timeout,
                "timeouts": [],
                "entrypoints": []
            }
            entrypoint_hints = entrypoint_hints or {}
            for ep in entrypoints:
                loaded_files.add(ep.resolve())

            for entry in entrypoints:
                entry = entry.resolve()
                if entry.suffix == ".py":
                    print(f"Tracing entrypoint: {entry.relative_to(self.repo_root)}")
                    rel = str(entry.relative_to(self.repo_root))
                    hint = entrypoint_hints.get(rel, "unknown")
                    effective_mode = "import-only" if (trace_mode == "auto" and hint == "infrastructure_boot") else trace_mode
                    effective_timeout = boot_timeout if hint == "infrastructure_boot" else default_timeout
                    cmd = [sys.executable, str(entry)]
                    if effective_mode == "import-only":
                        cmd = [
                            sys.executable,
                            "-c",
                            (
                                "import importlib.util; "
                                f"spec=importlib.util.spec_from_file_location('rie_trace_target', r'{entry}'); "
                                "mod=importlib.util.module_from_spec(spec); "
                                "spec.loader.exec_module(mod)"
                            )
                        ]

                    try:
                        completed = subprocess.run(
                            cmd,
                            env=env,
                            cwd=str(self.repo_root),
                            timeout=effective_timeout,
                            capture_output=True,
                            text=True
                        )
                        trace_meta["entrypoints"].append({
                            "path": rel,
                            "hint": hint,
                            "mode": effective_mode,
                            "timeout_s": effective_timeout,
                            "returncode": completed.returncode
                        })
                    except subprocess.TimeoutExpired:
                        trace_meta["timeouts"].append(rel)
                        trace_meta["entrypoints"].append({
                            "path": rel,
                            "hint": hint,
                            "mode": effective_mode,
                            "timeout_s": effective_timeout,
                            "timed_out": True
                        })
                        print(f"  Trace interrupted: timeout after {effective_timeout}s")
                    except Exception as e:
                        print(f"  Trace interrupted: {e}")

            relations = []
            if self.trace_log_path.exists():
                with open(self.trace_log_path, "r") as f:
                    for line in f:
                        if " -> " in line:
                            # Parse "path:line:symbol -> callee [count]"
                            try:
                                caller_part, rest = line.split(" -> ")
                                callee_part, count_part = rest.split(" [")
                                
                                # Split caller by colons (path:line:symbol)
                                # Since path might contain colons (less likely on Linux but technically possible), 
                                # we split from the right for line and symbol.
                                c_parts = caller_part.rsplit(":", 2)
                                if len(c_parts) == 3:
                                    c_path, c_line, c_sym = c_parts
                                else:
                                    # Fallback for older format or malformed lines
                                    c_path, c_line, c_sym = caller_part, "0", "unknown"
                                
                                callee = callee_part.strip()
                                count = int(count_part.replace("]", "").strip())
                                
                                relations.append((c_path.strip(), int(c_line), c_sym.strip(), callee, count))
                                
                                if callee and not callee.startswith("INTENDED_") and not callee.startswith("ext:"):
                                    # This is likely a repo-relative path
                                    full_path = self.repo_root / callee
                                    if full_path.exists():
                                        loaded_files.add(full_path.resolve())
                            except:
                                pass
            return loaded_files, relations, trace_meta

if __name__ == "__main__":
    import sys
    root_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    eps = [Path(p) for p in sys.argv[2:]] if len(sys.argv) > 2 else []
    tracer = RuntimeTracer(Path(root_arg))
    results, _, _ = tracer.run_trace(eps)
    print(f"Captured {len(results)} files via relational tracing.")
    for r in results:
        print(f"  {r.relative_to(tracer.repo_root)}")
