"""
Repository Integrity Engine -- Web GUI
Launch with: python3 gui_server.py
Opens browser to http://localhost:9100
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

PORT = 9100
TOOL_DIR = Path(__file__).parent.resolve()
MAIN_PY = TOOL_DIR / "main.py"

# Track scan state
scan_state = {
    "running": False,
    "progress": [],
    "result": None,
    "repo": None,
    "report_dir": None,
}


class GUIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress request logs

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/status":
            self._json_response(scan_state)
        elif path == "/api/browse":
            params = urllib.parse.parse_qs(parsed.query)
            dir_path = params.get("path", [os.path.expanduser("~")])[0]
            self._browse_directory(dir_path)
        elif path == "/api/quarantine/plan":
            self._get_quarantine_plan()
        elif path.startswith("/report/"):
            self._serve_report_file(path[8:])
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/scan":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            self._start_scan(body)
        elif parsed.path == "/api/quarantine/move":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            self._quarantine_move(body)
        elif parsed.path == "/api/quarantine/restore":
            self._quarantine_restore()
        elif parsed.path == "/api/run":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            self._run_entrypoint(body)
        else:
            self.send_error(404)

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _browse_directory(self, dir_path):
        try:
            dir_path = os.path.expanduser(dir_path)
            if not os.path.isdir(dir_path):
                self._json_response({"error": "Not a directory"}, 400)
                return

            entries = []
            # Parent directory
            parent = str(Path(dir_path).parent)
            if parent != dir_path:
                entries.append({"name": "..", "path": parent, "type": "dir"})

            for name in sorted(os.listdir(dir_path)):
                if name.startswith(".") and name not in [".git"]:
                    continue
                full = os.path.join(dir_path, name)
                if os.path.isdir(full):
                    entries.append({"name": name, "path": full, "type": "dir"})

            # Check if this looks like a repo
            has_py = any(f.endswith(".py") for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f)))
            is_repo = has_py or any(
                os.path.exists(os.path.join(dir_path, marker))
                for marker in [".git", "setup.py", "pyproject.toml", "package.json",
                               "Cargo.toml", "requirements.txt", "engine_target.yml",
                               "Makefile", "CMakeLists.txt", "go.mod"]
            )

            self._json_response({
                "current": dir_path,
                "entries": entries,
                "is_repo": is_repo,
            })
        except PermissionError:
            self._json_response({"error": "Permission denied"}, 403)

    def _start_scan(self, body):
        if scan_state["running"]:
            self._json_response({"error": "Scan already running"}, 409)
            return

        repo = body.get("repo", "")
        if not repo or not os.path.isdir(repo):
            self._json_response({"error": f"Invalid repo path: {repo}"}, 400)
            return

        k = body.get("k", 5)
        target = body.get("target", "auto")
        surfaces = body.get("surfaces", "primary")
        quarantine = body.get("quarantine", False)

        scan_state["running"] = True
        scan_state["progress"] = []
        scan_state["result"] = None
        scan_state["repo"] = repo
        scan_state["report_dir"] = os.path.join(repo, "reports")

        def run():
            try:
                cmd = [sys.executable, str(MAIN_PY), repo, "--k", str(k)]
                if target != "auto":
                    cmd += ["--target", target]
                if surfaces != "primary":
                    cmd += ["--surfaces", surfaces]
                if quarantine:
                    cmd += ["--quarantine"]

                scan_state["progress"].append(f"$ {' '.join(cmd)}")

                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=str(TOOL_DIR),
                )

                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        scan_state["progress"].append(line)

                proc.wait()
                scan_state["result"] = "success" if proc.returncode == 0 else "error"
            except Exception as e:
                scan_state["progress"].append(f"ERROR: {e}")
                scan_state["result"] = "error"
            finally:
                scan_state["running"] = False

        threading.Thread(target=run, daemon=True).start()
        self._json_response({"status": "started"})

    def _serve_report_file(self, filename):
        if not scan_state["report_dir"]:
            self.send_error(404, "No report directory")
            return

        filepath = os.path.join(scan_state["report_dir"], filename)
        if not os.path.isfile(filepath):
            self.send_error(404, f"File not found: {filename}")
            return

        content_types = {
            ".html": "text/html",
            ".json": "application/json",
            ".js": "application/javascript",
            ".css": "text/css",
        }
        ext = os.path.splitext(filename)[1]
        ctype = content_types.get(ext, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def _get_quarantine_plan(self):
        """Return quarantine plan JSON if it exists."""
        if not scan_state["report_dir"]:
            self._json_response({"error": "No scan run yet"}, 404)
            return
        plan_path = os.path.join(scan_state["report_dir"], "quarantine_plan.json")
        if not os.path.isfile(plan_path):
            self._json_response({"error": "No quarantine plan. Run scan with quarantine enabled."}, 404)
            return
        with open(plan_path) as f:
            plan = json.load(f)

        # Quarantine dir is OUTSIDE the repo as a sibling
        repo = scan_state.get("repo", "")
        repo_name = os.path.basename(repo)
        quarantine_dir = os.path.join(os.path.dirname(repo), f"_quarantine_{repo_name}")
        manifest_path = os.path.join(quarantine_dir, "move_manifest.json")
        moved_count = 0
        if os.path.isfile(manifest_path):
            with open(manifest_path) as f:
                moved_count = len(json.load(f))

        plan["move_state"] = {
            "manifest_exists": os.path.isfile(manifest_path),
            "moved_count": moved_count,
            "quarantine_dir": quarantine_dir,
        }
        self._json_response(plan)

    def _quarantine_move(self, body):
        """Execute quarantine move using Python-native shutil (no bash scripts)."""
        tier = body.get("tier", "")
        if tier not in ("tier1", "tier2", "tier3", "all"):
            self._json_response({"error": f"Invalid tier: {tier}"}, 400)
            return

        if not scan_state.get("repo"):
            self._json_response({"error": "No repo selected"}, 400)
            return

        plan_path = os.path.join(scan_state.get("report_dir", ""), "quarantine_plan.json")
        if not os.path.isfile(plan_path):
            self._json_response({"error": "No quarantine_plan.json. Run scan with quarantine first."}, 404)
            return

        try:
            with open(plan_path) as f:
                plan = json.load(f)

            # Reconstruct a minimal QuarantineEngine for apply()
            sys.path.insert(0, os.path.dirname(__file__))
            from quarantine_engine import QuarantineEngine
            from pathlib import Path as _Path

            repo_root = _Path(scan_state["repo"])

            # We only need the engine for apply() -- pass minimal data
            qe = QuarantineEngine(
                repo_root, [], {}, [], ["."],
            )

            # Map tier names
            if tier == "all":
                tiers = ["t1", "t2", "t3"]
            else:
                tiers = [tier.replace("tier", "t")]

            result = qe.apply(plan, tiers=tiers)

            self._json_response({
                "status": "error" if result.get("error") else "success",
                "tier": tier,
                "moved_count": result.get("moved_count", 0),
                "moved_files": result.get("moved", [])[:50],
                "errors": result.get("errors", [])[:20],
                "skipped": result.get("skipped", 0),
                "ledger": result.get("ledger_path", ""),
            })

        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _quarantine_restore(self):
        """Execute quarantine restore using Python-native ledger (no bash scripts)."""
        if not scan_state.get("repo"):
            self._json_response({"error": "No repo selected"}, 400)
            return

        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from quarantine_engine import QuarantineEngine
            from pathlib import Path as _Path

            repo_root = _Path(scan_state["repo"])
            qe = QuarantineEngine(repo_root, [], {}, [], ["."])

            ledger = qe._load_ledger()
            if not ledger.get("moves"):
                self._json_response({"error": "Nothing to restore -- ledger is empty."}, 404)
                return

            result = qe.restore()

            self._json_response({
                "status": "success" if not result.get("errors") else "partial",
                "restored_count": result.get("restored_count", 0),
                "restored_files": result.get("restored", [])[:50],
                "errors": result.get("errors", [])[:20],
                "remaining": result.get("remaining_in_quarantine", 0),
            })

        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _run_entrypoint(self, body):
        """Execute an entrypoint script from the scanned repo."""
        if not scan_state.get("repo"):
            self._json_response({"error": "No repo scanned yet"}, 400)
            return

        entrypoint = body.get("entrypoint", "")
        if not entrypoint:
            self._json_response({"error": "No entrypoint specified"}, 400)
            return

        # Safety: path must be inside repo, must be .py, must exist
        repo = scan_state["repo"]
        full_path = os.path.normpath(os.path.join(repo, entrypoint))
        if not full_path.startswith(os.path.normpath(repo)):
            self._json_response({"error": "Path escape detected"}, 403)
            return
        if not full_path.endswith(".py"):
            self._json_response({"error": "Only .py files can be run"}, 400)
            return
        if not os.path.isfile(full_path):
            self._json_response({"error": f"File not found: {entrypoint}"}, 404)
            return

        try:
            result = subprocess.run(
                [sys.executable, full_path],
                capture_output=True, text=True, timeout=30,
                cwd=repo,
                env={**os.environ, "__RIE_TRACING__": ""},
            )
            self._json_response({
                "status": "success" if result.returncode == 0 else "error",
                "returncode": result.returncode,
                "stdout": result.stdout[-5000:] if result.stdout else "",
                "stderr": result.stderr[-2000:] if result.stderr else "",
                "command": f"python3 {entrypoint}",
            })
        except subprocess.TimeoutExpired:
            self._json_response({
                "status": "timeout",
                "error": "Script timed out after 30 seconds",
                "command": f"python3 {entrypoint}",
            })
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(MAIN_HTML.encode())


MAIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Repository Integrity Engine</title>
    <style>
        :root {
            --bg: #0f1419;
            --panel: #1a222c;
            --border: #2d3742;
            --text: #e6edf3;
            --text-muted: #8b949e;
            --accent: #58a6ff;
            --success: #3fb950;
            --warning: #d29922;
            --error: #f85149;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }

        /* Layout */
        .app { display: flex; flex-direction: column; min-height: 100vh; }

        header {
            background: var(--panel);
            border-bottom: 1px solid var(--border);
            padding: 16px 24px;
            display: flex;
            align-items: center;
            gap: 16px;
        }
        header h1 { font-size: 18px; font-weight: 600; }
        header .version { color: var(--text-muted); font-size: 13px; }

        .main { flex: 1; display: flex; }

        /* Sidebar - File Browser */
        .sidebar {
            width: 340px;
            background: var(--panel);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        .sidebar-header {
            padding: 16px;
            border-bottom: 1px solid var(--border);
        }
        .sidebar-header h2 { font-size: 14px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 8px; }

        .path-bar {
            display: flex;
            gap: 4px;
            align-items: center;
        }
        .path-bar input {
            flex: 1;
            background: var(--bg);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-family: 'Consolas', 'Monaco', monospace;
        }
        .path-bar input:focus { outline: none; border-color: var(--accent); }
        .path-bar button {
            background: var(--accent);
            color: #000;
            border: none;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
        }

        .file-list {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }
        .file-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-family: 'Consolas', 'Monaco', monospace;
            transition: background 0.15s;
        }
        .file-item:hover { background: #232c36; }
        .file-item .icon { width: 18px; text-align: center; color: var(--accent); }
        .file-item.is-repo { border-left: 3px solid var(--success); }

        .repo-indicator {
            display: none;
            padding: 12px 16px;
            background: #3fb95015;
            border-top: 1px solid var(--border);
            color: var(--success);
            font-size: 13px;
            font-weight: 600;
        }
        .repo-indicator.show { display: block; }

        .sidebar-footer {
            padding: 12px;
            border-top: 1px solid var(--border);
            background: var(--panel);
        }

        .file-item .select-btn {
            display: none;
            background: var(--success);
            color: #000;
            border: none;
            padding: 2px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            margin-left: auto;
            flex-shrink: 0;
        }
        .file-item:hover .select-btn { display: inline-block; }
        .file-item .select-btn:hover { background: #56d364; }

        /* Content - Scan Config + Output */
        .content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

        .config-panel {
            padding: 24px;
            border-bottom: 1px solid var(--border);
        }
        .config-panel h2 { font-size: 16px; margin-bottom: 16px; }

        .config-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        .config-field label {
            display: block;
            font-size: 12px;
            color: var(--text-muted);
            text-transform: uppercase;
            margin-bottom: 6px;
        }
        .config-field select, .config-field input[type="number"] {
            width: 100%;
            background: var(--bg);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 14px;
        }
        .config-field select:focus, .config-field input:focus { outline: none; border-color: var(--accent); }

        .checkbox-field {
            display: flex;
            align-items: center;
            gap: 8px;
            padding-top: 24px;
        }
        .checkbox-field input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: var(--accent);
        }

        .scan-actions { display: flex; gap: 12px; align-items: center; }

        .btn {
            padding: 10px 24px;
            border-radius: 6px;
            border: none;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary { background: var(--accent); color: #000; }
        .btn-primary:hover { background: #79b8ff; }
        .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-secondary { background: var(--panel); color: var(--text); border: 1px solid var(--border); }
        .btn-secondary:hover { border-color: var(--accent); }
        .btn-success { background: var(--success); color: #000; }
        .btn-success:hover { background: #56d364; }

        .selected-repo {
            padding: 8px 14px;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
            color: var(--accent);
        }

        /* Terminal Output */
        .terminal-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .terminal-header {
            padding: 12px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .terminal-header h3 { font-size: 13px; color: var(--text-muted); text-transform: uppercase; }

        .terminal {
            flex: 1;
            background: #0d1117;
            padding: 16px 24px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.7;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .terminal .line { color: var(--text-muted); }
        .terminal .line.cmd { color: var(--accent); }
        .terminal .line.ok { color: var(--success); }
        .terminal .line.err { color: var(--error); }
        .terminal .line.phase { color: var(--warning); font-weight: 600; }
        .terminal .line.result { color: var(--text); }

        /* Status bar */
        .status-bar {
            padding: 8px 24px;
            background: var(--panel);
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: var(--text-muted);
        }
        .status-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
        }
        .status-dot.idle { background: var(--text-muted); }
        .status-dot.running { background: var(--warning); animation: pulse 1s infinite; }
        .status-dot.done { background: var(--success); }
        .status-dot.error { background: var(--error); }

        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

        /* Quarantine Panel */
        .quarantine-panel {
            border-bottom: 1px solid var(--border);
            max-height: 55vh;
            overflow-y: auto;
            background: var(--bg);
        }
        .quarantine-header {
            padding: 12px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--panel);
            position: sticky;
            top: 0;
            z-index: 1;
        }
        .quarantine-header h3 { font-size: 14px; }

        .q-summary {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            padding: 16px 24px;
        }
        .q-card {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }
        .q-card .q-count { font-size: 28px; font-weight: 700; }
        .q-card .q-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-top: 4px; }
        .q-card.t0 .q-count { color: var(--success); }
        .q-card.t1 .q-count { color: var(--accent); }
        .q-card.t2 .q-count { color: var(--warning); }
        .q-card.t3 .q-count { color: var(--error); }

        .q-tiers { padding: 0 24px 16px; }
        .q-tier {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-bottom: 12px;
            overflow: hidden;
        }
        .q-tier-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            cursor: pointer;
        }
        .q-tier-header:hover { background: #232c36; }
        .q-tier-header h4 { font-size: 14px; display: flex; align-items: center; gap: 8px; }
        .q-tier-header .q-tier-count {
            background: var(--border);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 12px;
            color: var(--text-muted);
        }
        .q-tier-header .q-tier-actions { display: flex; gap: 8px; align-items: center; }

        .q-file-list {
            display: none;
            max-height: 300px;
            overflow-y: auto;
            border-top: 1px solid var(--border);
        }
        .q-file-list.show { display: block; }
        .q-file {
            padding: 6px 16px;
            font-size: 12px;
            font-family: 'Consolas', 'Monaco', monospace;
            display: flex;
            justify-content: space-between;
            border-bottom: 1px solid #1a222c;
        }
        .q-file:hover { background: #0d1117; }
        .q-file .q-reason { color: var(--text-muted); font-size: 11px; }

        .q-restore-bar {
            padding: 12px 24px;
            background: var(--panel);
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            bottom: 0;
        }

        .q-moved-badge {
            display: inline-block;
            background: var(--success);
            color: #000;
            padding: 1px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 700;
            margin-left: 6px;
        }

        /* Welcome state */
        .welcome {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: var(--text-muted);
        }
        .welcome h2 { font-size: 20px; color: var(--text); margin-bottom: 8px; }
        .welcome p { max-width: 400px; }
    </style>
</head>
<body>
    <div class="app">
        <header>
            <h1>Repository Integrity Engine</h1>
            <span class="version">v2.2</span>
        </header>

        <div class="main">
            <!-- Sidebar: File Browser -->
            <div class="sidebar">
                <div class="sidebar-header">
                    <h2>Select Repository</h2>
                    <div class="path-bar">
                        <input type="text" id="pathInput" placeholder="/home/user/project" />
                        <button onclick="navigateTo(document.getElementById('pathInput').value)">Go</button>
                    </div>
                </div>
                <div class="file-list" id="fileList"></div>
                <div class="sidebar-footer" id="sidebarFooter">
                    <button class="btn btn-primary" style="width: 100%; padding: 12px;" onclick="selectRepo(currentPath)" id="selectCurrentBtn">
                        Select Current Directory
                    </button>
                </div>
            </div>

            <!-- Content -->
            <div class="content">
                <!-- Config Panel -->
                <div class="config-panel">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
                        <div>
                            <h2>Scan Configuration</h2>
                            <div class="selected-repo" id="selectedRepo">No repository selected</div>
                        </div>
                    </div>

                    <div class="config-grid">
                        <div class="config-field">
                            <label>Target</label>
                            <select id="cfgTarget">
                                <option value="auto">Auto (infer scope)</option>
                                <option value="engine">Engine (from engine_target.yml)</option>
                                <option value="global">Global (all files)</option>
                            </select>
                        </div>
                        <div class="config-field">
                            <label>Surfaces</label>
                            <select id="cfgSurfaces">
                                <option value="primary">Primary only</option>
                                <option value="all">All surfaces</option>
                            </select>
                        </div>
                        <div class="config-field">
                            <label>Top K Candidates</label>
                            <input type="number" id="cfgK" value="5" min="1" max="20" />
                        </div>
                        <div class="checkbox-field">
                            <input type="checkbox" id="cfgQuarantine" />
                            <label for="cfgQuarantine" style="text-transform: none; color: var(--text); font-size: 14px;">Generate quarantine plan</label>
                        </div>
                    </div>

                    <div class="scan-actions">
                        <button class="btn btn-primary" id="scanBtn" onclick="startScan()" disabled>
                            Run Scan
                        </button>
                        <button class="btn btn-success" id="viewReportBtn" onclick="viewReport()" style="display: none;">
                            View Report
                        </button>
                        <button class="btn btn-secondary" id="quarantineBtn" onclick="showQuarantinePanel()" style="display: none;">
                            Quarantine Plan
                        </button>
                        <span id="scanStatus" style="color: var(--text-muted); font-size: 13px;"></span>
                    </div>
                </div>

                <!-- Quarantine Panel (hidden by default) -->
                <div class="quarantine-panel" id="quarantinePanel" style="display: none;">
                    <div class="quarantine-header">
                        <h3>Quarantine Plan (Dry Run)</h3>
                        <div style="display: flex; gap: 8px;">
                            <button class="btn btn-secondary" onclick="hideQuarantinePanel()" style="padding: 4px 12px; font-size: 12px;">Close</button>
                        </div>
                    </div>

                    <!-- Summary Cards -->
                    <div class="q-summary" id="qSummary"></div>

                    <!-- Tier Sections -->
                    <div class="q-tiers" id="qTiers"></div>

                    <!-- Restore bar -->
                    <div class="q-restore-bar" id="qRestoreBar" style="display: none;">
                        <span id="qRestoreStatus"></span>
                        <button class="btn btn-secondary" onclick="quarantineRestore()">Restore All</button>
                    </div>
                </div>

                <!-- Terminal / Welcome -->
                <div class="terminal-panel" id="terminalPanel">
                    <div class="terminal-header">
                        <h3>Output</h3>
                        <button class="btn btn-secondary" onclick="clearTerminal()" style="padding: 4px 12px; font-size: 12px;">Clear</button>
                    </div>
                    <div class="terminal" id="terminal">
                        <div class="welcome" id="welcome">
                            <div>
                                <h2>Select a repository to scan</h2>
                                <p>Browse to a project directory using the sidebar, then click Run Scan to analyze it.</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="status-bar">
            <div>
                <span class="status-dot idle" id="statusDot"></span>
                <span id="statusText">Ready</span>
            </div>
            <div id="statusRight"></div>
        </div>
    </div>

    <script>
        let currentPath = '';
        let selectedRepo = null;
        let pollTimer = null;
        let lastLineCount = 0;

        // Init
        navigateTo('~');

        // File browser
        async function navigateTo(path) {
            try {
                const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
                const data = await res.json();
                if (data.error) {
                    console.error(data.error);
                    return;
                }

                currentPath = data.current;
                document.getElementById('pathInput').value = currentPath;

                const list = document.getElementById('fileList');
                list.innerHTML = data.entries.map(e => {
                    const escapedPath = e.path.replace(/'/g, "\\'");
                    if (e.name === '..') {
                        return `<div class="file-item" ondblclick="navigateTo('${escapedPath}')" onclick="navigateTo('${escapedPath}')">
                            <span class="icon">&#8593;</span>
                            <span>..</span>
                        </div>`;
                    }
                    return `<div class="file-item" ondblclick="navigateTo('${escapedPath}')">
                        <span class="icon">&#128193;</span>
                        <span>${e.name}</span>
                        <button class="select-btn" onclick="event.stopPropagation(); selectRepo('${escapedPath}')">Select</button>
                    </div>`;
                }).join('');

                // Update footer button
                const btn = document.getElementById('selectCurrentBtn');
                const shortPath = currentPath.split('/').slice(-2).join('/');
                btn.textContent = 'Select: ' + shortPath;
            } catch (err) {
                console.error('Browse error:', err);
            }
        }

        function selectRepo(path) {
            selectedRepo = path;
            const shortPath = path.split('/').pop() || path;
            document.getElementById('selectedRepo').textContent = path;
            document.getElementById('selectedRepo').style.color = 'var(--success)';
            document.getElementById('selectedRepo').style.borderColor = 'var(--success)';
            document.getElementById('scanBtn').disabled = false;
            document.getElementById('viewReportBtn').style.display = 'none';
            setStatus('idle', 'Ready - ' + shortPath + ' selected');
        }

        // Scan
        async function startScan() {
            if (!selectedRepo) return;

            const body = {
                repo: selectedRepo,
                k: parseInt(document.getElementById('cfgK').value) || 5,
                target: document.getElementById('cfgTarget').value,
                surfaces: document.getElementById('cfgSurfaces').value,
                quarantine: document.getElementById('cfgQuarantine').checked,
            };

            clearTerminal();
            document.getElementById('scanBtn').disabled = true;
            document.getElementById('viewReportBtn').style.display = 'none';
            document.getElementById('quarantineBtn').style.display = 'none';
            document.getElementById('quarantinePanel').style.display = 'none';
            setStatus('running', 'Scanning...');

            try {
                const res = await fetch('/api/scan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await res.json();
                if (data.error) {
                    appendLine(data.error, 'err');
                    setStatus('error', 'Failed to start');
                    document.getElementById('scanBtn').disabled = false;
                    return;
                }

                lastLineCount = 0;
                pollTimer = setInterval(pollStatus, 300);
            } catch (err) {
                appendLine('Failed to connect to server', 'err');
                setStatus('error', 'Connection error');
                document.getElementById('scanBtn').disabled = false;
            }
        }

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                // Append new lines
                for (let i = lastLineCount; i < data.progress.length; i++) {
                    const line = data.progress[i];
                    let cls = 'line';
                    if (line.startsWith('$')) cls += ' cmd';
                    else if (line.includes('[OK]') || line.includes('Reports written')) cls += ' ok';
                    else if (line.includes('ERROR') || line.includes('error')) cls += ' err';
                    else if (line.match(/^\[[\d\/]+\]/)) cls += ' phase';
                    else if (line.startsWith('>>') || line.startsWith('   1.') || line.startsWith('   2.')) cls += ' result';
                    appendLine(line, cls.replace('line ', ''));
                }
                lastLineCount = data.progress.length;

                if (!data.running && data.result) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    document.getElementById('scanBtn').disabled = false;

                    if (data.result === 'success') {
                        setStatus('done', 'Scan complete');
                        document.getElementById('viewReportBtn').style.display = 'inline-block';
                        // Show quarantine button if quarantine was enabled
                        if (document.getElementById('cfgQuarantine').checked) {
                            document.getElementById('quarantineBtn').style.display = 'inline-block';
                        }
                    } else {
                        setStatus('error', 'Scan failed');
                    }
                }
            } catch (err) {
                // ignore transient errors
            }
        }

        function viewReport() {
            window.open('/report/report_viewer.html', '_blank');
        }

        // Terminal
        function appendLine(text, type) {
            const terminal = document.getElementById('terminal');
            const welcome = document.getElementById('welcome');
            if (welcome) welcome.style.display = 'none';

            const div = document.createElement('div');
            div.className = `line ${type || ''}`;
            div.textContent = text;
            terminal.appendChild(div);
            terminal.scrollTop = terminal.scrollHeight;
        }

        function clearTerminal() {
            const terminal = document.getElementById('terminal');
            terminal.innerHTML = '';
            lastLineCount = 0;
        }

        function setStatus(state, text) {
            const dot = document.getElementById('statusDot');
            dot.className = `status-dot ${state}`;
            document.getElementById('statusText').textContent = text;
        }

        // Quarantine Panel
        async function showQuarantinePanel() {
            const panel = document.getElementById('quarantinePanel');
            const termPanel = document.getElementById('terminalPanel');
            panel.style.display = 'block';

            try {
                const res = await fetch('/api/quarantine/plan');
                const plan = await res.json();
                if (plan.error) {
                    document.getElementById('qSummary').innerHTML = `<div style="padding: 20px; color: var(--error);">${plan.error}</div>`;
                    return;
                }
                renderQuarantinePlan(plan);
            } catch (err) {
                document.getElementById('qSummary').innerHTML = `<div style="padding: 20px; color: var(--error);">Failed to load plan: ${err.message}</div>`;
            }
        }

        function hideQuarantinePanel() {
            document.getElementById('quarantinePanel').style.display = 'none';
        }

        function renderQuarantinePlan(plan) {
            const s = plan.summary;
            const ms = plan.move_state || {};

            // Summary cards
            const qdir = plan.summary.quarantine_dir || plan.move_state.quarantine_dir || '(unknown)';
            document.getElementById('qSummary').innerHTML = `
                <div class="q-card t0">
                    <div class="q-count">${s.t0_keep}</div>
                    <div class="q-label">T0 Core (keep)</div>
                </div>
                <div class="q-card t1">
                    <div class="q-count">${s.t1_move_low_risk}</div>
                    <div class="q-label">T1 Periphery</div>
                </div>
                <div class="q-card t2">
                    <div class="q-count">${s.t2_move_med_risk}</div>
                    <div class="q-label">T2 Shadows</div>
                </div>
                <div class="q-card t3">
                    <div class="q-count">${s.t3_move_zero_evidence}</div>
                    <div class="q-label">T3 Ghosts</div>
                </div>
                <div style="grid-column: 1 / -1; padding: 8px 12px; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; font-size: 12px; font-family: monospace; color: var(--text-muted);">
                    Quarantine location: <span style="color: var(--accent);">${qdir}</span>
                    <span style="margin-left: 12px; color: var(--success);">(outside repo - invisible to scanner)</span>
                </div>
            `;

            // Restore bar
            if (ms.moved_count > 0) {
                const bar = document.getElementById('qRestoreBar');
                bar.style.display = 'flex';
                document.getElementById('qRestoreStatus').innerHTML = `<span style="color: var(--warning);">${ms.moved_count} files currently quarantined</span>`;
            }

            // Tier sections
            const tiers = [
                { key: 't0_core', name: 'T0: Core', desc: 'DO NOT TOUCH -- reachable from engine entrypoints', color: 'var(--success)', data: plan.t0_core, movable: false },
                { key: 't1_periphery', name: 'T1: Periphery', desc: 'Out-of-scope surfaces, tools, docs -- low risk', color: 'var(--accent)', data: plan.t1_periphery, movable: true, tier: 'tier1' },
                { key: 't2_shadow', name: 'T2: Shadows', desc: 'Archive, backup, _old.py, _v1.py -- medium risk', color: 'var(--warning)', data: plan.t2_shadow, movable: true, tier: 'tier2' },
                { key: 't3_ghost', name: 'T3: Ghosts', desc: 'Zero evidence: no imports, no runtime, no text refs', color: 'var(--error)', data: plan.t3_ghost, movable: true, tier: 'tier3' },
            ];

            document.getElementById('qTiers').innerHTML = tiers.map((t, idx) => `
                <div class="q-tier" id="qtier-${idx}">
                    <div class="q-tier-header" onclick="toggleTierFiles(${idx})">
                        <h4>
                            <span style="color: ${t.color};">${t.name}</span>
                            <span class="q-tier-count">${t.data.length} files</span>
                        </h4>
                        <div class="q-tier-actions">
                            <span style="font-size: 12px; color: var(--text-muted);">${t.desc}</span>
                            ${t.movable ? `<button class="btn btn-secondary" onclick="event.stopPropagation(); quarantineMove('${t.tier}', this)" style="padding: 4px 14px; font-size: 12px;">Move</button>` : ''}
                        </div>
                    </div>
                    <div class="q-file-list" id="qfiles-${idx}">
                        ${t.data.slice(0, 200).map(f => `
                            <div class="q-file">
                                <span>${f.file}</span>
                                <span class="q-reason">${f.reason}</span>
                            </div>
                        `).join('')}
                        ${t.data.length > 200 ? `<div class="q-file" style="color: var(--text-muted); text-align: center;">+ ${t.data.length - 200} more files...</div>` : ''}
                    </div>
                </div>
            `).join('');
        }

        function toggleTierFiles(idx) {
            const list = document.getElementById('qfiles-' + idx);
            list.classList.toggle('show');
        }

        async function quarantineMove(tier, btn) {
            const origText = btn.textContent;
            btn.textContent = 'Moving...';
            btn.disabled = true;

            try {
                const res = await fetch('/api/quarantine/move', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tier }),
                });
                const data = await res.json();

                if (data.status === 'success') {
                    btn.textContent = 'Moved ' + data.moved_count;
                    btn.style.background = 'var(--success)';
                    btn.style.color = '#000';
                    btn.style.borderColor = 'var(--success)';
                    // Show restore bar
                    const bar = document.getElementById('qRestoreBar');
                    bar.style.display = 'flex';
                    document.getElementById('qRestoreStatus').innerHTML = `<span style="color: var(--success);">${tier} moved (${data.moved_count} files)</span>`;
                    // Log to terminal
                    appendLine(`>> Quarantine ${tier}: ${data.moved_count} files moved`, 'ok');
                } else {
                    btn.textContent = 'Error';
                    btn.style.background = 'var(--error)';
                    appendLine(`>> Quarantine ${tier} error: ${data.error || 'unknown'}`, 'err');
                }
            } catch (err) {
                btn.textContent = 'Error';
                appendLine(`>> Quarantine error: ${err.message}`, 'err');
            }
        }

        async function quarantineRestore() {
            const bar = document.getElementById('qRestoreBar');
            document.getElementById('qRestoreStatus').innerHTML = '<span style="color: var(--warning);">Restoring...</span>';

            try {
                const res = await fetch('/api/quarantine/restore', { method: 'POST' });
                const data = await res.json();

                if (data.status === 'success') {
                    document.getElementById('qRestoreStatus').innerHTML = `<span style="color: var(--success);">Restored ${data.restored_count} files</span>`;
                    appendLine(`>> Quarantine restore: ${data.restored_count} files restored`, 'ok');
                    // Reset move buttons
                    document.querySelectorAll('.q-tier-actions button').forEach(b => {
                        if (b.textContent.startsWith('Moved')) {
                            b.textContent = 'Move';
                            b.disabled = false;
                            b.style.background = '';
                            b.style.color = '';
                            b.style.borderColor = '';
                        }
                    });
                } else {
                    document.getElementById('qRestoreStatus').innerHTML = `<span style="color: var(--error);">Restore failed: ${data.error}</span>`;
                    appendLine(`>> Restore error: ${data.error}`, 'err');
                }
            } catch (err) {
                document.getElementById('qRestoreStatus').innerHTML = `<span style="color: var(--error);">${err.message}</span>`;
            }
        }

        // Keyboard shortcuts
        document.getElementById('pathInput').addEventListener('keydown', e => {
            if (e.key === 'Enter') navigateTo(e.target.value);
        });
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), GUIHandler)
    url = f"http://localhost:{PORT}"
    print(f"Repository Integrity Engine GUI")
    print(f"  Server: {url}")
    print(f"  Tool:   {TOOL_DIR}")
    print()
    print(f"Opening browser...")
    webbrowser.open(url)
    print(f"Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
