"""
Phase 1: Runtime Tracer
Hooks into Python's import system to log every file actually loaded during execution.

Modes:
  auto: AST-extract imports from each file, exec only those (fast, safe, no package structure needed)
  import-only: same as auto
  full: actually execute the script (catches dynamic imports but can hang)

The auto/import-only approach:
  1. Read the target file
  2. Parse with AST, extract only import/from-import statements  
  3. Build a mini-script that does ONLY those imports (with import hook active)
  4. The hook captures what files get loaded -> dependency chain discovered
  
This works regardless of __init__.py, folder names with spaces, or missing package structure.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


class RuntimeTracer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def run_trace(
        self,
        entrypoints: list,
        safe: bool = True,
        default_timeout: int = 10,
        boot_timeout: int = 15,
        trace_mode: str = "auto",
        entrypoint_hints: dict = None,
    ) -> tuple:
        """
        Trace each entrypoint and collect runtime-loaded files.
        Returns: (runtime_files: set[Path], relations: list[tuple], trace_meta: dict)
        """
        runtime_files = set()
        relations = []
        timeouts = []
        traced_entries = []
        entrypoint_hints = entrypoint_hints or {}
        total = len(entrypoints)

        print(f"[TRACE] Tracing {total} entrypoints (mode: {trace_mode})...")

        for idx, ep in enumerate(entrypoints, 1):
            rel = str(ep.relative_to(self.repo_root))
            hint = entrypoint_hints.get(rel, "")

            timeout = boot_timeout if hint == "infrastructure_boot" else default_timeout

            if trace_mode == "full":
                mode = "full"
            else:
                mode = "import-only"

            print(f"  [{idx}/{total}] {rel}", end="", flush=True)

            trace_result = self._trace_single(ep, safe=safe, timeout=timeout, mode=mode)

            # Mark based on simulation results
            status = trace_result["status"]
            blocked = trace_result.get("blocked", [])
            if blocked:
                status = "blocked"
            
            n_files = len(trace_result["files"])
            if n_files > 0:
                print(f" -> {n_files} files", end="")
            
            if status == "timeout":
                print(f" [TIMEOUT]", end="")
                timeouts.append(rel)
            elif status == "blocked":
                print(f" [BLOCKED]", end="")
            elif status == "ok":
                if n_files == 0:
                    print(f" -> 0 in-repo", end="")
            else:
                print(f" [{status}]", end="")
            print()

            traced_entries.append({
                "path": rel,
                "status": status,
                "files_found": n_files,
                "mode": mode,
                "timeout": timeout,
                "blocked_events": blocked,
            })

            for f in trace_result["files"]:
                fp = Path(f)
                if fp.exists():
                    runtime_files.add(fp)

            for src, tgt in trace_result.get("edges", []):
                relations.append((src, tgt))

        print(f"[TRACE] Done. {len(runtime_files)} unique files, {len(timeouts)} timeouts.")

        trace_meta = {
            "trace_mode": trace_mode,
            "timeouts": timeouts,
            "default_timeout": default_timeout,
            "boot_timeout": boot_timeout,
            "entrypoints": traced_entries,
        }

        return runtime_files, relations, trace_meta

    def _extract_imports(self, filepath: Path) -> str:
        """
        Parse a Python file and extract only its import statements as executable code.
        Returns a string of just the import lines, safe to exec.
        """
        try:
            source = filepath.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, ValueError, UnicodeDecodeError):
            return ""

        import_lines = []
        for node in ast.iter_child_nodes(tree):
            # Only grab top-level imports (not inside functions/classes)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_lines.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = ", ".join(alias.name for alias in node.names)
                level = "." * (node.level or 0)
                if module:
                    import_lines.append(f"from {level}{module} import {names}")
                elif level:
                    import_lines.append(f"from {level} import {names}")

        return "\n".join(import_lines)

    def _trace_single(self, entrypoint: Path, safe: bool = True, timeout: int = 10, mode: str = "import-only") -> dict:
        """Trace a single entrypoint by running it in a subprocess with import hooking."""
        trace_out = tempfile.mktemp(suffix=".json", prefix="rie_trace_")

        # The import hook that captures loaded files
        hook_setup = textwrap.dedent(f"""\
        import atexit, json, os, sys

        _loaded = set()
        _edges = []
        _blocked = []
        _repo = {repr(str(self.repo_root))}
        _ep = {repr(str(entrypoint))}
        _trace_out = {repr(trace_out)}

        _real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def _hooked_import(name, globals=None, locals=None, fromlist=(), level=0):
            caller = None
            try:
                frame = sys._getframe(1)
                if frame and hasattr(frame, 'f_code'):
                    caller = frame.f_code.co_filename
            except ValueError:
                pass

            mod = _real_import(name, globals, locals, fromlist, level)
            try:
                m = sys.modules.get(name)
                f = getattr(m, '__file__', None)
                if f:
                    abs_f = os.path.abspath(f)
                    if abs_f.startswith(_repo):
                        _loaded.add(abs_f)
                        if caller and caller.startswith(_repo):
                            _edges.append((caller, abs_f))
            except Exception:
                pass
            return mod

        try:
            import builtins
            builtins.__import__ = _hooked_import
        except Exception:
            pass

        try:
            def _audit_hook(event, args):
                if event in ("subprocess.Popen", "os.system", "os.exec", "os.spawn", "socket.connect"):
                    _blocked.append({{"event": event, "details": str(args)}})
                    raise PermissionError("Blocked")
            sys.addaudithook(_audit_hook)
        except Exception:
            pass

        def _dump():
            try:
                os.makedirs(os.path.dirname(_trace_out), exist_ok=True)
                with open(_trace_out, 'w') as f:
                    json.dump({{"files": sorted(list(_loaded)), "edges": _edges, "blocked": _blocked}}, f)
            except Exception:
                pass

        atexit.register(_dump)
        os.environ['__RIE_TRACING__'] = '1'

        # Safety net: self-terminate before parent's timeout
        try:
            import signal
            def _alarm(signum, frame):
                _dump()
                os._exit(0)
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm({max(timeout - 2, 3)})
        except (AttributeError, ValueError):
            pass

        # Add the entrypoint's directory AND all intermediate parents to sys.path
        _ep_dir = os.path.dirname(_ep)
        _path_parts = os.path.relpath(_ep_dir, _repo).split(os.sep)
        _current = _repo
        for _part in _path_parts:
            _current = os.path.join(_current, _part)
            if _current not in sys.path:
                sys.path.insert(0, _current)
        if _ep_dir and _ep_dir not in sys.path:
            sys.path.insert(0, _ep_dir)
        """)

        if mode == "import-only":
            # Extract just the import statements from the file via AST
            import_code = self._extract_imports(entrypoint)
            if import_code:
                # Wrap each import in try/except so one failure doesn't stop the rest
                safe_imports = []
                for line in import_code.split("\n"):
                    if line.strip():
                        safe_imports.append(f"try:\n    {line}\nexcept Exception:\n    pass")
                hook_code = hook_setup + "\n" + "\n".join(safe_imports) + "\n"
            else:
                hook_code = hook_setup
        else:
            # Full execution mode
            hook_code = hook_setup + textwrap.dedent(f"""
            try:
                exec(open({repr(str(entrypoint))}).read())
            except SystemExit:
                pass
            except Exception:
                pass
            """)

        tracer_file = tempfile.mktemp(suffix=".py", prefix="rie_tracer_")
        try:
            with open(tracer_file, "w") as f:
                f.write(hook_code)

            env = os.environ.copy()
            env["__RIE_TRACING__"] = "1"
            env["PYTHONPATH"] = str(self.repo_root) + os.pathsep + env.get("PYTHONPATH", "")

            if safe:
                env["DISPLAY"] = ""
                env["WAYLAND_DISPLAY"] = ""
                env["SDL_VIDEODRIVER"] = "dummy"
                env["QT_QPA_PLATFORM"] = "offscreen"
                env["MPLBACKEND"] = "Agg"

            try:
                result = subprocess.run(
                    [sys.executable, tracer_file],
                    cwd=str(self.repo_root),
                    timeout=timeout,
                    capture_output=True,
                    env=env,
                )
                status = "ok" if result.returncode == 0 else "error"
            except subprocess.TimeoutExpired:
                status = "timeout"
                try:
                    subprocess.run(["pkill", "-f", tracer_file], capture_output=True, timeout=2)
                except Exception:
                    pass
            except Exception as e:
                status = f"error:{type(e).__name__}"

            # Read trace output
            files = []
            edges = []
            blocked = []
            if os.path.exists(trace_out):
                try:
                    with open(trace_out) as f:
                        data = json.load(f)
                    files = data.get("files", [])
                    edges = data.get("edges", [])
                    blocked = data.get("blocked", [])
                    if status == "timeout" and files:
                        status = "partial"
                except Exception:
                    pass

            return {"status": status, "files": files, "edges": edges, "blocked": blocked}

        finally:
            for tmp in (tracer_file, trace_out):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
