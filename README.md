# Repository Integrity Engine v2.2

Point this at any Python repo and know exactly where to start.

The Repository Integrity Engine scans a codebase, finds the files that actually matter, ranks them by importance, and tells you which ones to run first. Everything else gets classified into keep, quarantine, or ignore -- with safe, reversible cleanup.

Built for developers who inherited a repo with 2,000 files, no documentation, and a deadline.


## Install

```
pip install pyyaml
```

That's it. Everything else is Python 3.8+ stdlib. No compiled dependencies, no Docker, no cloud.


## 30-Second Quickstart

```bash
# Scan any Python repo (read-only, zero side effects)
python3 scan.py /path/to/repo

# Open the interactive report
open /path/to/repo/reports/report_viewer.html

# Or launch the web GUI
python3 gui_server.py
```

The scan produces two files in `reports/`:
- `usage_index.json` -- the complete analysis artifact
- `report_viewer.html` -- interactive browser-based dashboard


## What It Does

**Scan** -- Finds every Python entrypoint, traces imports (static + optional runtime), builds a dependency graph, and scores every file by reachability, centrality, and naming signals.

**Rank** -- Identifies the top-K entrypoints that cover the most code. Tells you "run this file first" with a copy-to-clipboard command.

**Surface Detection** -- Auto-detects independent codebases within a monorepo. Each surface gets its own coverage metrics, entrypoint rankings, and cross-edge analysis.

**Quarantine** -- Classifies every file into tiers:
- **T0 Core** -- reachable from engine entrypoints. Do not touch.
- **T1 Periphery** -- out-of-scope surfaces, tools, docs. Low risk.
- **T2 Shadow** -- `_old.py`, `_backup.py`, legacy patterns. Medium risk.
- **T3 Ghost** -- zero evidence anywhere. No imports, no runtime, no references.

**Enforce** -- Detects boundary violations, module shadowing, active files hiding in archive folders, and unauthorized cross-surface imports.


## Three Scripts, Three Jobs

```
scan.py    -- Read-only analysis. Never loads deletion code. Safe on production.
clean.py   -- Consumes the JSON artifact. Quarantines or prunes. No re-scanning.
main.py    -- Both in one call (backward compatible).
```

The scan and clean phases are fully decoupled. Run the heavy scan once, then clean multiple times with different thresholds. The JSON artifact is the contract between them.


## Usage

### Basic Scan
```bash
python3 scan.py /path/to/repo
```

### Scan with Options
```bash
# Limit to top 5 entrypoints, show all surfaces
python3 scan.py /path/to/repo --k 5 --surfaces all

# Skip runtime tracing (static-only, faster, deterministic)
python3 scan.py /path/to/repo --no-trace

# Target a specific folder
python3 scan.py /path/to/repo --target myapp/core
```

### Quarantine
```bash
# Generate quarantine plan (scan + classify)
python3 main.py /path/to/repo --quarantine

# Or use the two-step workflow:
python3 scan.py /path/to/repo          # step 1: analyze
python3 clean.py /path/to/repo --quarantine  # step 2: act on results
```

### Web GUI
```bash
python3 gui_server.py
# Opens browser to http://localhost:9100
# Browse repos, scan, view reports, quarantine files -- all from the browser.
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `--k N` | Top N entrypoint candidates (default: 10) |
| `--target engine` | Scope to engine roots only |
| `--target global` | Scan everything |
| `--surfaces all` | Show all detected surfaces |
| `--no-trace` | Skip runtime tracing (static analysis only) |
| `--trace-mode auto` | Auto-select trace strategy per entrypoint |
| `--trace-timeout N` | Timeout per trace in seconds (default: 10) |
| `--quarantine` | Generate quarantine plan + scripts |
| `--prune` | Generate pruning plan + scripts |


## Report Viewer

The HTML report has five tabs:

- **Overview** -- Engine coverage, boundary violations, "Start the Engine" card with copy-to-clipboard, surface breakdown cards
- **Entrypoints** -- Filterable table with role, intent, domain, score, coverage. "Run" buttons on executable entries.
- **Violations** -- Boundary violations, module shadowing, active-in-archive warnings
- **Files & Domains** -- Domain tree showing every file classified by domain and intent
- **Raw JSON** -- Section-by-section JSON explorer with syntax highlighting and copy button


## Configuration

### engine_target.yml

Place in the repo root to control scope, surfaces, and cross-surface rules:

```yaml
# Which folders are "the engine" (scanned + traced)
include_roots:
  - myapp/core
  - myapp/api

# What to exclude from tracing
exclude:
  - archive
  - docs
  - vendor

# Declare surfaces explicitly (overrides auto-detection)
surfaces:
  backend:
    root: myapp/
    type: web_application
  ml_pipeline:
    root: ml/
    type: data_pipeline

# Allow specific cross-surface imports
cross_surface:
  allow:
    - from: backend
      to: ml_pipeline
      reason: API calls ML inference
```

### entrypoint_domains.yml

Define project-specific domain classifications:

```yaml
domains:
  - name: game_engine
    include:
      - "**/engine/**"
      - "**/runtime/**"
    exclude:
      - "**/tests/**"
    priority: 10

  - name: animation
    include:
      - "**/anim/**"
      - "**/mechanimation/**"
    priority: 5
```

Built-in domains (always available, no config needed): `core_engine`, `testing`, `documentation`, `migration_tools`, `configuration`, `cli`, `api`, `data_layer`, `utilities`.


## How Scoring Works

Each entrypoint gets a composite score from five signals:

| Signal | Weight | Source |
|--------|--------|--------|
| Graph reach (coverage) | 35% | Dependency graph (static + runtime) |
| Centrality | 25% | Import graph out-degree |
| Filename heuristics | 15% | `launch_`, `main`, `app`, `server` patterns |
| Role scoring | 15% | Behavioral classification (boot, CLI, tool) |
| `__main__` block | 10% | Has `if __name__ == "__main__"` |

When runtime tracing is incomplete, the report flags `trace_partial: true` and shows which portion of the score comes from deterministic static signals vs trace-dependent graph signals.


## Surface Detection

Surfaces are auto-detected from top-level directories with 3+ Python files. Large folders (20+ .py files) with multiple distinct sub-directories are automatically split into sub-surfaces.

Example output:
```
godotengain    437 files   31 active    8 traced  coverage: 7%
               cross: 6 out / 1 in
trae           109 files   24 active    0 traced  coverage: 22%
godotsim        22 files   17 active   12 traced  coverage: 77%
               cross: 0 out / 10 in
blender       1700 files    2 active    0 traced  coverage: 0%
```

Cross-surface edges are tracked and reported. Unauthorized imports between surfaces show as policy violations unless allowed in `engine_target.yml`.


## Quarantine Tiers

| Tier | Risk | What | Action |
|------|------|------|--------|
| T0 | -- | Reachable from entrypoints | Keep. Do not touch. |
| T1 | Low | Out-of-scope surfaces, tools, docs | Safe to move |
| T2 | Medium | `_old.py`, `_backup.py`, legacy naming | Review then move |
| T3 | Zero | No imports, no runtime, no text refs | Move immediately |

Quarantine moves files to a sibling directory (`_quarantine_<reponame>/`) outside the repo. The scanner never sees quarantined files on rescan. All moves are tracked in a transaction ledger (`.rie_ledger.json`) with full restore capability.


## Architecture

```
scan.py / main.py
    |
    +-- entrypoint_detector.py    # Find __main__ blocks, CLI patterns
    +-- static_analyzer.py        # AST-based import graph
    +-- runtime_tracer.py         # Optional: execute + trace imports
    +-- text_scanner.py           # String reference search
    +-- graph_engine.py           # Build dependency graph
    +-- scope_resolver.py         # Surface detection, cross-edge tracking
    +-- domain_resolver.py        # 3-tier domain classification
    +-- cartography.py            # Folder health, domain mapping
    +-- triangulator.py           # Greedy set-cover entrypoint selection
    +-- entry_tagger.py           # Role scoring, composite ranking
    +-- policy_enforcer.py        # Boundary violations, shadowing
    +-- reporter.py               # JSON report + HTML viewer generation
    |
clean.py
    |
    +-- quarantine_engine.py      # Tier classification + Python-native moves
    +-- pruning_engine.py         # Dead code removal scripts
```

Static analysis is the backbone. Runtime tracing is optional enrichment. The graph is deterministic without tracing -- tracing only adds bonus edges.


## Requirements

- Python 3.8+
- PyYAML (`pip install pyyaml`)
- No other dependencies


## License

MIT
