# 🛡️ Repository Integrity Engine (v1.0)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-v1.0--Stable-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)]()

> A sophisticated, policy-driven code filter and architectural governance tool for Python repositories.

The **Repository Integrity Engine** transforms repository analysis from "guessing" into "governance." It discovers reachable code, minimizes your entrypoint surface, and enforces strict architectural boundaries—all while running repository code in a hardened, side-effect-free environment.

---

## 🚀 Core Value Proposition

- **Minimize Legacy Waste**: Identify files that are truly dead, not just "unreferenced" in text.
- **Architectural Governance**: Detect "Archive Leaks," Shadowed Modules, and Boundary Violations automatically.
- **Safe Tracing**: Run untrusted repository code with a **Deny-by-Default** safety harness.
- **Triangulated Coverage**: Discover the minimum set of scripts needed to reach 100% of your active code.

---

## 🧩 The 4-Layer Analysis Pipeline

### 1. Evidence Gathering (Phase 1)
Collects multi-modal proof of life:
- **Runtime Traces**: Files actually loaded during execution.
- **Static AST Analysis**: Import chains and symbol tracking.
- **Text Scans**: Weighted string references.

### 2. Structural Validation (Phase 2 & 3)
Builds a mathematical model of your repository:
- **Execution Graph**: Nodes representing files and edges representing dependencies.
- **Structural Cartography**: Maps "domains of execution" and folder health.

### 3. Entrypoint Triangulation (Phase 4 & 4.5)
Identifies the "engines" of your codebase:
- **Role Scoring**: Classifies scripts into `infrastructure_boot`, `core_logic_driver`, and `tooling_cli`.
- **Greedy Triangulation**: Picks the Top-K entrypoints that cover the maximum reachable surface.

### 4. Policy Enforcement (Phase 5 & 6)
Turns insights into action:
- **Drift Detection**: Catch active files living in the `archive/`.
- **Shadowing Resolution**: Identifies module name collisions.
- **Safe Prune**: Generates a Bash script to safely move active tools and delete dead code.

---

## 🛠️ Usage

### Quick Start
```bash
# Analyze a repository with safe runtime tracing enabled
python3 main.py /path/to/repo --prune
```

### Advanced Flags
- `--no-trace`: Skip dangerous execution and rely only on static/text evidence.
- `--no-safe`: Disable the Safety Harness (⚠️ Use only for trusted internal code).
- `--k 5`: Triangulate the top 5 entrypoints for maximum coverage.
- `--prune`: Generate a physical `prune_script.sh` in the `reports/` directory.

---

## 📊 Interactive Reporting
The engine generates a structured `usage_index.json` and a beautiful `report_viewer.html` for deep inspection of your repository's integrity.

---

## ⚖️ Safety & Disclaimer
This tool uses a hardened "Safe Trace Harness" to intercept side effects. However, it is a **safety guardrail**, not a cryptographic sandbox. Always exercise caution when running unknown code.
