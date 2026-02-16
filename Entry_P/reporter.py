"""
Reporter
Generates the final structured report:
  - reports/usage_index.json (machine-readable)
  - reports/report_viewer.html (interactive browser viewer)
"""
import json
import os
from pathlib import Path
from datetime import datetime


class Reporter:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.reports_dir = repo_root / "reports"
        self.reports_dir.mkdir(exist_ok=True)

    def generate(
        self,
        all_files: set,
        runtime_files: set,
        static_imports: set,
        text_refs: dict,
        file_data: list,
        phase_two_data: dict = None,
        cartography_data: dict = None,
        triangulation_data: dict = None,
        classified_entrypoints: list = None,
        policy_data: dict = None,
        metadata: dict = None,
        surface_data: dict = None,
    ) -> dict:
        phase_two_data = phase_two_data or {}
        cartography_data = cartography_data or {}
        triangulation_data = triangulation_data or {}
        classified_entrypoints = classified_entrypoints or []
        policy_data = policy_data or {}
        metadata = metadata or {}
        surface_data = surface_data or {}

        active_count = sum(1 for f in file_data if f["status"] == "ACTIVE")
        legacy_count = sum(1 for f in file_data if f["status"] == "LEGACY")
        runtime_count = sum(1 for f in file_data if "runtime_trace" in f.get("evidence", []))

        # Enrich classified entrypoints with domain/scope/surface from file_data
        file_map = {f["file"]: f for f in file_data}
        for ep in classified_entrypoints:
            fdata = file_map.get(ep["path"], {})
            ep["domain"] = fdata.get("domain", "unknown")
            ep["scope"] = ep["path"].split("/")[0] if "/" in ep["path"] else "root"
            ep["surface_id"] = fdata.get("surface_id", ep["scope"])

        primary_candidates = [ep for ep in classified_entrypoints if ep.get("eligible_for_primary")]
        coverage_summary = triangulation_data.get("coverage_summary", {})
        coverage_ratio = coverage_summary.get("coverage_ratio", 0)

        report = {
            "schema_version": "2.2.0",
            "metadata": {
                **metadata,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "repo": str(self.repo_root),
                "tool": "Repository Integrity Engine",
                "version": "2.2",
            },
            "summary": {
                "total_files": len(file_data),
                "active_files": active_count,
                "legacy_files": legacy_count,
                "runtime_traced": runtime_count,
                "static_imported": sum(1 for f in file_data if "static_import" in f.get("evidence", [])),
                "text_referenced": len(text_refs),
            },
            "layer_1_evidence": {
                "files": file_data,
            },
            "layer_2_structure": {
                "graph_summary": {
                    "total_nodes": phase_two_data.get("clusters", {}).get("total_nodes", 0),
                    "total_edges": phase_two_data.get("clusters", {}).get("total_edges", 0),
                    "roots": phase_two_data.get("clusters", {}).get("roots", [])[:20],
                    "leaves_count": len(phase_two_data.get("clusters", {}).get("leaves", [])),
                },
                # Full adjacency list -- consumed by clean.py for quarantine/prune
                "graph": {k: sorted(v) for k, v in phase_two_data.get("graph", {}).items() if v},
                "cartography": {
                    "folders": cartography_data.get("folders", {}),
                    "domains": cartography_data.get("domains", []),
                },
            },
            "layer_3_entrypoints": {
                "triangulation": {
                    "coverage_summary": coverage_summary,
                    "selected_engines": triangulation_data.get("selected", []),
                    "top_ranked": triangulation_data.get("all_ranked", [])[:20],
                },
            },
            "layer_4_policy": policy_data,
            # Compatibility aliases for report_viewer.html
            "phase4_entrypoints": {
                "classified": classified_entrypoints,
                "primary_candidates": primary_candidates,
            },
            "policy_violations": policy_data,
            "cartography_data": {
                "domains": cartography_data.get("domains", []),
            },
            "scan_stats": {
                "files_scanned": len(file_data),
                "entrypoints_detected": len(classified_entrypoints),
                "runtime_traced": runtime_count,
                "static_imports": sum(1 for f in file_data if "static_import" in f.get("evidence", [])),
            },
            "engine_coverage": coverage_ratio,
            "active_in_archive": policy_data.get("active_in_archive", []),
            "surfaces": surface_data,
        }

        json_path = self.reports_dir / "usage_index.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

        self._generate_html_viewer()

        print(f"\n\u2705 Reports written to: {self.reports_dir}")
        print(f"   - {json_path.name} ({os.path.getsize(json_path)} bytes)")
        print(f"   - report_viewer.html")

        return report

    def _generate_html_viewer(self):
        html_path = self.reports_dir / "report_viewer.html"
        html_path.write_text(VIEWER_HTML, encoding="utf-8")



VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Repository Integrity Engine - Report Viewer</title>
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
            --code: #6e7681;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 20px;
        }

        .container { max-width: 1400px; margin: 0 auto; }
        
        /* Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 30px;
        }
        header h1 { font-size: 24px; font-weight: 600; }
        header .meta { color: var(--text-muted); font-size: 14px; }
        header .meta span { margin-left: 20px; }

        /* Navigation */
        nav {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        nav button {
            background: var(--panel);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        nav button:hover { border-color: var(--accent); }
        nav button.active { background: var(--accent); border-color: var(--accent); color: #000; }

        /* Sections */
        .section { display: none; }
        .section.active { display: block; }

        /* Cards */
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
        }
        .card h3 { color: var(--text-muted); font-size: 12px; text-transform: uppercase; margin-bottom: 10px; }
        .card .value { font-size: 32px; font-weight: 600; }
        .card .value.success { color: var(--success); }
        .card .value.warning { color: var(--warning); }
        .card .value.error { color: var(--error); }

        /* Tables */
        table {
            width: 100%;
            border-collapse: collapse;
            background: var(--panel);
            border-radius: 8px;
            overflow: hidden;
        }
        th, td {
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        th {
            background: #232c36;
            color: var(--text-muted);
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
        }
        tr:hover { background: #232c36; }
        code {
            background: var(--code);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Consolas', monospace;
            font-size: 13px;
        }

        /* Tags */
        .tag {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .tag.runtime { background: #1f6feb33; color: #58a6ff; }
        .tag.tools { background: #d2992233; color: #d29922; }
        .tag.tests { background: #f8514933; color: #f85149; }
        .tag.archive { background: #6e768133; color: #8b949e; }
        .tag.boot { background: #3fb95033; color: #3fb950; }
        .tag.core { background: #58a6ff33; color: #58a6ff; }
        .tag.cli { background: #d2992233; color: #d29922; }

        /* Command Box */
        .command-box {
            background: #0d1117;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 16px;
            margin: 20px 0;
            font-family: 'Consolas', monospace;
            font-size: 14px;
        }
        .command-box .label { color: var(--text-muted); font-size: 12px; margin-bottom: 8px; }
        .command-box code { color: var(--accent); }

        /* Violations */
        .violation-row { cursor: pointer; }
        .violation-details {
            display: none;
            background: #0d1117;
            padding: 16px;
            border-top: 1px solid var(--border);
        }
        .violation-details.show { display: block; }
        .violation-details .fix { color: var(--success); margin-top: 10px; }

        /* Filters */
        .filters {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .filters select, .filters input {
            background: var(--panel);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 14px;
        }

        /* Loading */
        .loading {
            text-align: center;
            padding: 60px;
            color: var(--text-muted);
        }
        .loading .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Error */
        .error-box {
            background: #f8514922;
            border: 1px solid var(--error);
            border-radius: 8px;
            padding: 20px;
            color: var(--error);
            margin: 20px 0;
        }

        /* Tree */
        .tree { margin-left: 20px; }
        .tree-item { padding: 4px 0; }
        .tree-toggle { cursor: pointer; color: var(--accent); }
        .tree-children { display: none; margin-left: 20px; }
        .tree-children.show { display: block; }

        /* Utility */
        .flex { display: flex; gap: 10px; align-items: center; }
        .justify-between { justify-content: space-between; }
        .mt-20 { margin-top: 20px; }
        .mb-20 { margin-bottom: 20px; }
        .text-muted { color: var(--text-muted); }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1> Repository Integrity Engine</h1>
            <div class="meta" id="headerMeta">
                <span>Run ID: <code id="runId">-</code></span>
                <span>Timestamp: <code id="timestamp">-</code></span>
            </div>
        </header>

        <!-- Surface Selector -->
        <div id="surfaceBar" style="display: none; padding: 8px 24px; background: #161b22; border-bottom: 1px solid #2d3742; font-size: 13px;">
            <label style="color: #8b949e; margin-right: 8px;">Surface:</label>
            <select id="surfaceFilter" style="background: #0d1117; color: #e6edf3; border: 1px solid #2d3742; padding: 4px 8px; border-radius: 4px;">
                <option value="all">All Surfaces</option>
            </select>
            <span id="surfaceInfo" style="margin-left: 16px; color: #8b949e;"></span>
        </div>

        <nav>
            <button class="active" data-section="overview">Overview</button>
            <button data-section="entrypoints">Entrypoints & Scopes</button>
            <button data-section="violations">Boundary Violations</button>
            <button data-section="domains">Files & Domains</button>
            <button data-section="rawjson">Raw JSON</button>
        </nav>

        <div id="loading" class="loading">
            <div class="spinner"></div>
            <p>Loading report data...</p>
        </div>

        <div id="error" class="error-box" style="display: none;"></div>

        <!-- OVERVIEW -->
        <section id="overview" class="section active">
            <!-- Surface Breakdown Cards -->
            <div id="surfaceCards" style="display: none; margin-bottom: 16px;"></div>

            <div class="cards">
                <div class="card">
                    <h3>Engine Coverage</h3>
                    <div class="value success" id="engineCoverage">-</div>
                    <div class="text-muted" id="engineScope">-</div>
                </div>
                <div class="card">
                    <h3>Boundary Violations</h3>
                    <div class="value error" id="boundaryViolations">-</div>
                    <div class="text-muted">tests touching runtime</div>
                </div>
                <div class="card">
                    <h3>Active in Archive</h3>
                    <div class="value warning" id="activeInArchive">-</div>
                    <div class="text-muted">files that should be moved</div>
                </div>
                <div class="card">
                    <h3>Shadowed Modules</h3>
                    <div class="value warning" id="shadowedModules">-</div>
                    <div class="text-muted">duplicate module names</div>
                </div>
            </div>

            <div class="card">
                <h3>Start the Engine</h3>
                <div id="startEngine"></div>
            </div>

            <div class="card mt-20">
                <h3>Scan Statistics</h3>
                <div id="scanStats"></div>
            </div>
        </section>

        <!-- ENTRYPOINTS -->
        <section id="entrypoints" class="section">
            <div class="filters">
                <select id="scopeFilter">
                    <option value="all">All Scopes</option>
                </select>
                <select id="roleFilter">
                    <option value="all">All Roles</option>
                    <option value="infrastructure_boot">Boot</option>
                    <option value="core_logic_driver">Core</option>
                    <option value="tooling_cli">CLI Tool</option>
                    <option value="test_harness">Test</option>
                </select>
                <select id="intentFilter">
                    <option value="all">All Intents</option>
                    <option value="intent:runtime">Runtime</option>
                    <option value="intent:tools">Tools</option>
                    <option value="intent:tests">Tests</option>
                    <option value="intent:archive">Archive</option>
                </select>
                <input type="text" id="pathFilter" placeholder="Filter by path...">
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Path</th>
                        <th>Role</th>
                        <th>Intent</th>
                        <th>Domain</th>
                        <th>In Engine</th>
                        <th>Score</th>
                        <th>Coverage</th>
                        <th style="width: 60px;"></th>
                    </tr>
                </thead>
                <tbody id="entrypointsTable"></tbody>
            </table>
        </section>

        <!-- VIOLATIONS -->
        <section id="violations" class="section">
            <div class="filters">
                <select id="violationSeverity">
                    <option value="all">All Severities</option>
                    <option value="error">Error</option>
                    <option value="warn">Warning</option>
                </select>
                <input type="text" id="violationFilter" placeholder="Filter by test or module...">
            </div>
            <div class="cards">
                <div class="card">
                    <h3>By Test File</h3>
                    <div id="violationsByTest"></div>
                </div>
                <div class="card">
                    <h3>By Runtime Module</h3>
                    <div id="violationsByRuntime"></div>
                </div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Test File</th>
                        <th>Runtime Module</th>
                        <th>Symbol</th>
                        <th>Type</th>
                        <th>Severity</th>
                    </tr>
                </thead>
                <tbody id="violationsTable"></tbody>
            </table>
        </section>

        <!-- DOMAINS -->
        <section id="domains" class="section">
            <div id="domainsTree"></div>
        </section>

        <!-- RAW JSON -->
        <section id="rawjson" class="section">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div>
                    <select id="jsonSection" style="margin-right: 8px;">
                        <option value="__full__">Full Report</option>
                        <option value="metadata">Metadata</option>
                        <option value="summary">Summary</option>
                        <option value="layer_1_evidence">Layer 1: Evidence</option>
                        <option value="layer_2_structure">Layer 2: Structure</option>
                        <option value="layer_3_entrypoints">Layer 3: Entrypoints</option>
                        <option value="phase4_entrypoints">Classified Entrypoints</option>
                        <option value="policy_violations">Policy Violations</option>
                        <option value="surfaces">Surfaces</option>
                        <option value="scan_stats">Scan Stats</option>
                    </select>
                </div>
                <button onclick="copyJson()" style="background: var(--accent); color: #000; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                    Copy JSON
                </button>
            </div>
            <pre id="jsonBlock" style="background: #0d1117; border: 1px solid var(--border); border-radius: 8px; padding: 16px; overflow: auto; max-height: 70vh; font-size: 12px; line-height: 1.5; color: #e6edf3; white-space: pre-wrap; word-break: break-all;"></pre>
        </section>
    </div>

    <script>
        // State
        let reportData = null;
        let entrypoints = [];
        let violations = [];
        let domains = {};

        // Safe accessor -- never returns undefined
        function safe(val, fallback) { return (val === undefined || val === null) ? (fallback || '---') : val; }

        // Navigation
        document.querySelectorAll('nav button').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(btn.dataset.section).classList.add('active');
            });
        });

        // Load Data
        async function loadData() {
            try {
                const res = await fetch('usage_index.json');
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                reportData = await res.json();

                // Schema version check
                const expectedSchema = '2.2.0';
                if (reportData.schema_version && reportData.schema_version !== expectedSchema) {
                    console.warn(`Report schema ${reportData.schema_version} may not match viewer v${expectedSchema}`);
                }
                
                // Extract data
                entrypoints = reportData.phase4_entrypoints?.classified || [];
                violations = reportData.policy_violations?.tests_touching_runtime?.violations || [];
                domains = reportData.cartography_data?.domains || {};

                // Populate UI
                populateOverview();
                populateEntrypoints();
                populateViolations();
                populateDomains();
                populateJson();
                populateFilters();

                document.getElementById('loading').style.display = 'none';
            } catch (err) {
                document.getElementById('loading').style.display = 'none';
                const errorEl = document.getElementById('error');
                errorEl.style.display = 'block';
                errorEl.textContent = `Failed to load usage_index.json: ${err.message}. Make sure you've run the scanner first.`;
            }
        }

        // Overview
        function populateOverview() {
            const meta = reportData.metadata || {};
            document.getElementById('runId').textContent = meta.run_id || '-';
            document.getElementById('timestamp').textContent = meta.timestamp?.split('T')[0] || '-';

            const policy = reportData.policy_violations || {};
            const trace = meta.trace || {};
            const stats = reportData.scan_stats || {};

            // Engine coverage
            const coverage = reportData.engine_coverage || 0;
            document.getElementById('engineCoverage').textContent = `${Math.round(coverage * 100)}%`;
            document.getElementById('engineScope').textContent = (meta.engine_scope || []).join(', ') || 'global';

            // Violations
            const vCount = violations.length;
            document.getElementById('boundaryViolations').textContent = vCount;
            document.getElementById('boundaryViolations').className = `value ${vCount > 0 ? 'error' : 'success'}`;

            // Active in archive
            const activeArchive = reportData.active_in_archive?.length || 0;
            document.getElementById('activeInArchive').textContent = activeArchive;
            document.getElementById('activeInArchive').className = `value ${activeArchive > 0 ? 'warning' : 'success'}`;

            // Shadowed
            const shadowed = policy.shadowed_modules?.length || 0;
            document.getElementById('shadowedModules').textContent = shadowed;
            document.getElementById('shadowedModules').className = `value ${shadowed > 0 ? 'warning' : 'success'}`;

            // Start engine -- with copy-to-clipboard "Run" buttons
            const engine = reportData.phase4_entrypoints?.primary_candidates || [];
            const startEl = document.getElementById('startEngine');
            if (engine.length > 0) {
                const top = engine[0];
                const cmd = `python3 ${top.path}`;
                startEl.innerHTML = `
                    <div class="command-box" style="display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <div class="label">Primary Entry Point</div>
                            <code id="primaryCmd">${cmd}</code>
                            <div class="text-muted" style="margin-top: 8px;">
                                Role: ${formatRole(top.role)} | Score: ${Math.round((top.primary_candidate_score || 0) * 100)}%
                                | Coverage: ${Math.round((top.score_breakdown?.coverage || 0) * 100)}%
                            </div>
                        </div>
                        <button onclick="copyCmd('${cmd}')" style="background: var(--accent); color: #000; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 600; white-space: nowrap;">
                            Copy Command
                        </button>
                    </div>
                `;
                if (engine.length > 1) {
                    const alt = engine[1];
                    const altCmd = `python3 ${alt.path}`;
                    startEl.innerHTML += `
                        <div class="command-box" style="margin-top: 8px; display: flex; align-items: center; justify-content: space-between;">
                            <div>
                                <div class="label">Alternative (${formatRole(alt.role)})</div>
                                <code>${altCmd}</code>
                            </div>
                            <button onclick="copyCmd('${altCmd}')" style="background: #2d3742; color: #e6edf3; border: 1px solid #444; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px;">
                                Copy
                            </button>
                        </div>
                    `;
                }
            } else {
                startEl.innerHTML = '<div class="text-muted">No engine entrypoints identified.</div>';
            }

            // Trace completeness warning
            const trace_comp = trace.completeness;
            const tracePartial = trace.partial;
            if (tracePartial) {
                document.getElementById('scanStats').innerHTML = `
                    <div style="background: #2d2000; border: 1px solid #d29922; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; font-size: 13px; color: #d29922;">
                        Trace completeness: ${Math.round((trace_comp || 0) * 100)}% -- some entrypoints timed out. Static graph is primary signal.
                    </div>
                `;
            } else {
                document.getElementById('scanStats').innerHTML = '';
            }

            // Scan stats
            document.getElementById('scanStats').innerHTML += `
                <div class="flex" style="flex-wrap: wrap; gap: 20px;">
                    <div><strong>${stats.files_scanned || 0}</strong> files scanned</div>
                    <div><strong>${stats.entrypoints_detected || 0}</strong> entrypoints</div>
                    <div><strong>${stats.runtime_traced || 0}</strong> runtime traced</div>
                    <div><strong>${stats.static_imports || 0}</strong> static imports</div>
                </div>
            `;
        }

        function copyCmd(cmd) {
            navigator.clipboard.writeText(cmd).then(() => {
                const btn = event.target;
                const orig = btn.textContent;
                btn.textContent = 'Copied!';
                btn.style.background = '#3fb950';
                setTimeout(() => { btn.textContent = orig; btn.style.background = ''; }, 1500);
            });
        }

        // Raw JSON viewer
        function populateJson() {
            const select = document.getElementById('jsonSection');
            const block = document.getElementById('jsonBlock');

            function render() {
                const key = select.value;
                let data;
                if (key === '__full__') {
                    data = reportData;
                } else {
                    data = reportData[key] || {};
                }
                block.innerHTML = syntaxHighlight(JSON.stringify(data, null, 2));
            }

            select.addEventListener('change', render);
            render();
        }

        function syntaxHighlight(json) {
            json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return json.replace(
                /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
                function (match) {
                    let cls = 'color: #a5d6ff;';  // number
                    if (/^"/.test(match)) {
                        if (/:$/.test(match)) {
                            cls = 'color: #7ee787;';  // key
                        } else {
                            cls = 'color: #a5d6ff;';  // string
                        }
                    } else if (/true|false/.test(match)) {
                        cls = 'color: #ff7b72;';  // boolean
                    } else if (/null/.test(match)) {
                        cls = 'color: #8b949e;';  // null
                    }
                    return '<span style="' + cls + '">' + match + '</span>';
                }
            );
        }

        function copyJson() {
            const key = document.getElementById('jsonSection').value;
            const data = key === '__full__' ? reportData : (reportData[key] || {});
            const text = JSON.stringify(data, null, 2);
            navigator.clipboard.writeText(text).then(() => {
                const btn = event.target;
                const orig = btn.textContent;
                btn.textContent = 'Copied!';
                btn.style.background = '#3fb950';
                setTimeout(() => { btn.textContent = orig; btn.style.background = ''; }, 1500);
            });
        }

        // Entrypoints
        function populateEntrypoints() {
            const tbody = document.getElementById('entrypointsTable');
            const filtered = filterEntrypoints();
            
            tbody.innerHTML = filtered.map(ep => {
                const isRunnable = ep.intent_tags?.includes('intent:runtime') || ep.intent_tags?.includes('intent:tools');
                const cmd = `python3 ${ep.path}`;
                const runBtn = isRunnable
                    ? `<button onclick="copyCmd('${cmd}')" style="background: none; border: 1px solid #2d3742; color: #8b949e; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 11px;" onmouseover="this.style.borderColor='var(--accent)';this.style.color='var(--accent)'" onmouseout="this.style.borderColor='#2d3742';this.style.color='#8b949e'">Run</button>`
                    : '';
                return `<tr>
                    <td><code>${ep.path}</code></td>
                    <td><span class="tag ${getRoleClass(ep.role)}">${formatRole(ep.role)}</span></td>
                    <td><span class="tag ${getIntentClass(ep.intent_tags)}">${formatIntent(ep.intent_tags)}</span></td>
                    <td>${ep.domain || '-'}</td>
                    <td>${ep.in_engine_scope ? 'Y' : 'N'}</td>
                    <td>${Math.round((ep.primary_candidate_score || 0) * 100)}%</td>
                    <td>${Math.round((ep.coverage?.cover_ratio || 0) * 100)}%</td>
                    <td>${runBtn}</td>
                </tr>`;
            }).join('');
        }

        function filterEntrypoints() {
            const scope = document.getElementById('scopeFilter').value;
            const role = document.getElementById('roleFilter').value;
            const intent = document.getElementById('intentFilter').value;
            const path = document.getElementById('pathFilter').value.toLowerCase();

            return getFilteredEntrypoints().filter(ep => {
                if (scope !== 'all' && ep.scope !== scope) return false;
                if (role !== 'all' && ep.role !== role) return false;
                if (intent !== 'all' && !ep.intent_tags?.includes(intent)) return false;
                if (path && !ep.path.toLowerCase().includes(path)) return false;
                return true;
            });
        }

        // Violations
        function populateViolations() {
            const tbody = document.getElementById('violationsTable');
            const filtered = filterViolations();

            // Schema mismatch detection
            if (filtered.length > 0 && !filtered[0].hasOwnProperty('test_file')) {
                const keys = Object.keys(filtered[0]).join(', ');
                tbody.innerHTML = `<tr><td colspan="5" style="color: #f85149; text-align: center; padding: 20px;">
                    <strong>SCHEMA MISMATCH</strong><br>
                    Viewer expects key 'test_file', report has: [${keys}]<br>
                    Re-run the scan to regenerate the report.
                </td></tr>`;
                return;
            }

            tbody.innerHTML = filtered.map((v, idx) => {
                const sev = safe(v.severity, 'warn');
                const sevColor = sev === 'error' ? '#f85149' : '#d29922';
                const sevBg = sev === 'error' ? '#f8514933' : '#d2992233';
                return `
                <tr class="violation-row" onclick="toggleViolation(this)">
                    <td><code>${safe(v.test_file)}</code></td>
                    <td><code>${safe(v.runtime_module)}</code></td>
                    <td>${safe(v.symbol, '-')}</td>
                    <td>${safe(v.edge_type, 'import')}</td>
                    <td><span class="tag" style="background: ${sevBg}; color: ${sevColor}">${sev}</span></td>
                </tr>
                <tr>
                    <td colspan="5">
                        <div class="violation-details" id="v-${idx}">
                            <div><strong>Evidence:</strong> ${safe(v.evidence, 'static_ast')}</div>
                            <div><strong>Test:</strong> ${safe(v.test_file)}</div>
                            <div><strong>Runtime:</strong> ${safe(v.runtime_module)}</div>
                            <div class="fix"><strong>Suggested Fix:</strong> ${safe(v.suggested_fix, 'Review import and consider mocking')}</div>
                        </div>
                    </td>
                </tr>`;
            }).join('');

            // Summary cards
            const byTest = reportData.policy_violations?.tests_touching_runtime?.summary?.by_test_file || {};
            const byRuntime = reportData.policy_violations?.tests_touching_runtime?.summary?.by_runtime_module || {};

            document.getElementById('violationsByTest').innerHTML = Object.entries(byTest)
                .slice(0, 5)
                .map(([f, c]) => `<div><code>${f}</code>: ${c}</div>`)
                .join('') || '<div class="text-muted">None</div>';

            document.getElementById('violationsByRuntime').innerHTML = Object.entries(byRuntime)
                .slice(0, 5)
                .map(([f, c]) => `<div><code>${f}</code>: ${c}</div>`)
                .join('') || '<div class="text-muted">None</div>';
        }

        function filterViolations() {
            const severity = document.getElementById('violationSeverity').value;
            const filter = document.getElementById('violationFilter').value.toLowerCase();

            return getFilteredViolations().filter(v => {
                if (severity !== 'all' && safe(v.severity) !== severity) return false;
                if (filter && !safe(v.test_file).toLowerCase().includes(filter) && !safe(v.runtime_module).toLowerCase().includes(filter)) return false;
                return true;
            });
        }

        function toggleViolation(row) {
            const details = row.nextElementSibling?.querySelector('.violation-details');
            if (details) {
                details.classList.toggle('show');
            }
        }

        // Domains
        function populateDomains() {
            const container = document.getElementById('domainsTree');
            
            // Group entrypoints by domain
            const byDomain = {};
            entrypoints.forEach(ep => {
                const domain = ep.domain || 'unknown';
                if (!byDomain[domain]) byDomain[domain] = [];
                byDomain[domain].push(ep);
            });

            container.innerHTML = Object.entries(byDomain).map(([domain, eps]) => `
                <div class="card mb-20">
                    <h3 class="flex justify-between">
                        <span>${domain}</span>
                        <span class="text-muted">${eps.length} entrypoints</span>
                    </h3>
                    <div class="tree">
                        ${eps.slice(0, 10).map(ep => `
                            <div class="tree-item">
                                <code>${ep.path}</code>
                                <span class="tag ${getRoleClass(ep.role)}" style="margin-left: 10px;">${formatRole(ep.role)}</span>
                            </div>
                        `).join('')}
                        ${eps.length > 10 ? `<div class="text-muted">+ ${eps.length - 10} more...</div>` : ''}
                    </div>
                </div>
            `).join('');
        }

        // Filters
        let currentSurface = 'all';

        function populateFilters() {
            const scopeFilter = document.getElementById('scopeFilter');
            const scopes = new Set(entrypoints.map(ep => ep.scope).filter(Boolean));
            scopes.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                opt.textContent = s;
                scopeFilter.appendChild(opt);
            });

            // Add listeners
            document.getElementById('scopeFilter').addEventListener('change', populateEntrypoints);
            document.getElementById('roleFilter').addEventListener('change', populateEntrypoints);
            document.getElementById('intentFilter').addEventListener('change', populateEntrypoints);
            document.getElementById('pathFilter').addEventListener('input', populateEntrypoints);
            document.getElementById('violationSeverity').addEventListener('change', populateViolations);
            document.getElementById('violationFilter').addEventListener('input', populateViolations);

            // Surface filter
            populateSurfaces();
        }

        function populateSurfaces() {
            const surfaceData = reportData.surfaces || {};
            const metrics = surfaceData.metrics || {};
            const surfaceNames = Object.keys(metrics);

            // Only show surface bar if 2+ surfaces
            if (surfaceNames.length < 2) return;

            const bar = document.getElementById('surfaceBar');
            bar.style.display = 'block';

            const sel = document.getElementById('surfaceFilter');
            surfaceNames.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                opt.textContent = `${s} (${metrics[s].file_count} files)`;
                sel.appendChild(opt);
            });

            sel.addEventListener('change', () => {
                currentSurface = sel.value;
                const m = metrics[currentSurface];
                if (m) {
                    document.getElementById('surfaceInfo').textContent =
                        `${m.active} active / ${m.runtime} traced / coverage: ${(m.coverage * 100).toFixed(0)}%`;
                } else {
                    document.getElementById('surfaceInfo').textContent = '';
                }
                populateOverview();
                populateEntrypoints();
                populateViolations();
            });

            // Surface cards in overview
            const cardsDiv = document.getElementById('surfaceCards');
            cardsDiv.style.display = 'block';
            const crossInfo = surfaceData.cross_edges || {};
            const crossPairs = crossInfo.by_pair || {};

            cardsDiv.innerHTML = '<div class="cards">' + surfaceNames.map(s => {
                const m = metrics[s];
                const covPct = (m.coverage * 100).toFixed(0);
                const crossOut = m.cross_edges_out || 0;
                const crossIn = m.cross_edges_in || 0;
                const crossLabel = (crossOut + crossIn) > 0
                    ? `<div style="margin-top: 4px; font-size: 11px; color: #d29922;">cross: ${crossOut} out / ${crossIn} in</div>`
                    : '';
                return `<div class="card" style="cursor: pointer; border-left: 3px solid ${covPct > 50 ? '#3fb950' : '#d29922'};"
                    onclick="document.getElementById('surfaceFilter').value='${s}'; document.getElementById('surfaceFilter').dispatchEvent(new Event('change'));">
                    <h3 style="font-size: 14px;">${s}</h3>
                    <div class="value" style="color: ${covPct > 50 ? '#3fb950' : '#d29922'};">${covPct}%</div>
                    <div class="text-muted">${m.file_count} files / ${m.active} active / ${m.runtime} traced</div>
                    ${crossLabel}
                </div>`;
            }).join('') + '</div>';

            // Cross-surface summary
            if (crossInfo.count > 0) {
                let crossHtml = '<div style="margin-top: 8px; padding: 8px 12px; background: #161b22; border: 1px solid #2d3742; border-radius: 6px; font-size: 12px;">';
                crossHtml += `<strong style="color: #d29922;">${crossInfo.count} cross-surface edges</strong>`;
                for (const [pair, count] of Object.entries(crossPairs)) {
                    crossHtml += ` <span style="color: #8b949e; margin-left: 12px;">${pair}: ${count}</span>`;
                }
                crossHtml += '</div>';
                cardsDiv.innerHTML += crossHtml;
            }
        }

        function getFilteredEntrypoints() {
            let eps = entrypoints;
            if (currentSurface !== 'all') {
                eps = eps.filter(ep => safe(ep.surface_id) === currentSurface || safe(ep.scope) === currentSurface);
            }
            return eps;
        }

        function getFilteredViolations() {
            let vs = violations;
            if (currentSurface !== 'all') {
                vs = vs.filter(v =>
                    safe(v.test_file).startsWith(currentSurface + '/') ||
                    safe(v.runtime_module).startsWith(currentSurface + '/')
                );
            }
            return vs;
        }

        // Helpers
        function getRoleClass(role) {
            return {
                'infrastructure_boot': 'boot',
                'core_logic_driver': 'core',
                'tooling_cli': 'cli',
                'test_harness': 'tests'
            }[role] || 'runtime';
        }

        function formatRole(role) {
            return {
                'infrastructure_boot': 'Boot',
                'core_logic_driver': 'Core',
                'tooling_cli': 'CLI',
                'test_harness': 'Test'
            }[role] || role;
        }

        function getIntentClass(tags) {
            if (!tags) return 'runtime';
            if (tags.includes('intent:tools')) return 'tools';
            if (tags.includes('intent:tests')) return 'tests';
            if (tags.includes('intent:archive')) return 'archive';
            return 'runtime';
        }

        function formatIntent(tags) {
            if (!tags) return 'runtime';
            if (tags.includes('intent:tools')) return 'Tools';
            if (tags.includes('intent:tests')) return 'Tests';
            if (tags.includes('intent:archive')) return 'Archive';
            return 'Runtime';
        }

        // Init
        loadData();
    </script>
</body>
</html>"""
