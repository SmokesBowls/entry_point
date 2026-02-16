#!/usr/bin/env python3
"""
Repository Integrity Engine v2.2

Two modes:
  scan (default) -- read-only analysis, generates report JSON
  clean          -- consumes report JSON to quarantine/prune (separate step)

The scan phase NEVER imports pruning or quarantine modules.
This separation ensures users can safely run scans on production codebases
without any file-modification machinery being loaded into memory.
"""
import argparse
import os
from pathlib import Path
from entrypoint_detector import EntrypointDetector
from static_analyzer import StaticAnalyzer
from runtime_tracer import RuntimeTracer
from text_scanner import TextScanner
from reporter import Reporter
from graph_engine import GraphEngine
from risk_analyzer import RiskAnalyzer
from simulation_engine import SimulationEngine
from validator import Validator
from cartography import CartographyEngine
from triangulator import Triangulator
from entry_tagger import EntryTagger
from policy_enforcer import PolicyEnforcer
# NOTE: PruningEngine and QuarantineEngine are lazy-imported ONLY when
# --prune or --quarantine flags are passed. They are never loaded during
# read-only scans. This is intentional -- see "Diagnosis vs Surgery" separation.
from domain_resolver import DomainResolver
from scope_resolver import ScopeResolver
import yaml
import json
import uuid
import hashlib
from datetime import datetime

def build_arg_parser(include_surgery=True):
    """Build the CLI argument parser.
    
    Args:
        include_surgery: If False, omit --prune and --quarantine flags.
                        Used by scan.py to present a clean read-only interface.
    """
    desc = "Repository Integrity Engine -- scan any Python codebase to find entrypoints, map dependencies, and identify dead code."
    epilog = "Default mode is read-only scan."
    if include_surgery:
        epilog += " Add --prune or --quarantine to enable cleanup (separate phase)."
    
    parser = argparse.ArgumentParser(description=desc, epilog=epilog)
    parser.add_argument("repo", nargs="?", default=".", help="Path to the repository to analyze (default: current dir)")
    parser.add_argument("--no-trace", action="store_true", help="Skip runtime tracing")
    parser.add_argument("--k", type=int, default=10, help="Max entrypoints to return")
    parser.add_argument("--target", help="Target scope: 'engine' (default include roots), 'global' (everything), or a folder path")
    parser.add_argument("--surfaces", choices=["primary", "all"], default="primary", help="Show primary surface only (default) or all detected surfaces")
    parser.add_argument("--trace-mode", choices=["full", "import-only", "auto"], default="auto", help="Trace strategy")
    parser.add_argument("--trace-timeout", type=int, default=10, help="Default timeout per entrypoint trace in seconds")
    parser.add_argument("--boot-timeout", type=int, default=15, help="Timeout for infrastructure_boot entrypoints")
    parser.add_argument("--no-safe", action="store_false", dest="safe", help="Disable Simulation Mode")
    parser.set_defaults(safe=True)
    
    if include_surgery:
        parser.add_argument("--prune", action="store_true", help="Generate a safe pruning plan and script")
        parser.add_argument("--quarantine", action="store_true", help="Generate quarantine plan with tiered move/restore scripts")
    
    return parser


def run_scan(repo_root, args):
    """Execute the read-only scan pipeline. Returns scan state dict."""

    # Metadata & Config
    run_id = str(uuid.uuid4())
    try:
        from datetime import timezone
        timestamp = datetime.now(timezone.utc).isoformat()
    except ImportError:
        timestamp = datetime.utcnow().isoformat() + "Z"
    
    print(f"--- Repository Integrity Engine v2.2: {repo_root} ---")
    mode_label = "scan"
    if getattr(args, "prune", False):
        mode_label = "scan + prune"
    if getattr(args, "quarantine", False):
        mode_label = "scan + quarantine"
    print(f"[MODE] {mode_label}" + (" [SAFE]" if args.safe else " [UNSAFE]"))
    
    # 0. Discovery
    all_files_list = {p for p in repo_root.rglob("*") if p.is_file() and ".git" not in p.parts and "reports" not in p.parts and "__pycache__" not in p.parts}
    
    domain_rules = {}
    domains_path = repo_root / "entrypoint_domains.yml"
    if domains_path.exists():
        try:
            with open(domains_path, "r") as f:
                domain_rules = yaml.safe_load(f) or {}
        except: pass
    
    allowlist = {}
    allowlist_path = repo_root / "allowlist.yml"
    if allowlist_path.exists():
        try:
            with open(allowlist_path, "r") as f:
                allowlist = yaml.safe_load(f) or {}
        except: pass

    # Config Hash
    config_prep = {"domains": domain_rules, "allowlist": allowlist, "repo": str(repo_root)}
    config_hash = "sha256:" + hashlib.sha256(json.dumps(config_prep, sort_keys=True).encode()).hexdigest()
    metadata = {"run_id": run_id, "timestamp": timestamp, "config_hash": config_hash}
    
    resolver = DomainResolver(repo_root, domain_rules)

    # 1. Entrypoints (detect all -- we need the full list for reporting)
    print("[1/6] Detecting entrypoints...")
    detector = EntrypointDetector(repo_root)
    all_entrypoints = detector.detect_all()
    print(f"  Found {len(all_entrypoints)} entrypoints.")

    # Early scope resolution: figure out what to trace BEFORE tracing
    # Static analysis first (fast, no execution) to inform scope
    print("[2/6] Static analysis...")
    analyzer = StaticAnalyzer(repo_root)
    static_imports = analyzer.analyze_repo()
    static_edges = analyzer.get_edges()
    print(f"  Found {len(static_imports)} statically imported files, {len(static_edges)} import edges.")
    scanner = TextScanner(repo_root)
    text_refs = scanner.scan_all(all_files_list)
    print(f"  Found {len(text_refs)} text-referenced files.")

    # Build preliminary file data for scope inference
    text_ref_files = set(text_refs.keys()) if isinstance(text_refs, dict) else set()
    prelim_data = []
    for f in all_files_list:
        rel = str(f.relative_to(repo_root))
        ev = []
        if f in static_imports: ev.append("static_import")
        if rel in text_ref_files: ev.append("text_reference")
        res = resolver.resolve(rel)
        conf = "MED" if f in static_imports else ("LOW-MED" if rel in text_ref_files else "LOW")
        prelim_data.append({
            "file": rel, "evidence": ev, "confidence": conf,
            "status": "ACTIVE" if conf in ["HIGH", "MED"] else "LEGACY",
            "domain": res["domain"], "intent": res["intent"], "domain_source": res["source"]
        })

    # Build preliminary graph for scope inference
    prelim_relations = [(src, tgt) for src, tgt in static_edges]
    prelim_graph_engine = GraphEngine(repo_root, prelim_data, prelim_relations)
    prelim_graph = prelim_graph_engine.build_graph()

    # Load engine target config early (needed for surface detection)
    engine_target_config = None
    engine_target_path = repo_root / "engine_target.yml"
    if engine_target_path.exists():
        try:
            with open(engine_target_path, "r") as f:
                engine_target_config = yaml.safe_load(f) or {}
        except Exception:
            pass

    # Scope and Surface inference
    scope_resolver = ScopeResolver(repo_root, prelim_data, prelim_graph,
                                   engine_target_config=engine_target_config)
    inferred = scope_resolver.infer_scopes()
    engine_scopes = inferred["engine_scopes"]

    # Tag every file with surface_id
    scope_resolver.tag_files(prelim_data)
    surface_info = scope_resolver.detect_surfaces()
    surface_names = list(surface_info["surfaces"].keys())
    if surface_names:
        print(f"  Surfaces: {', '.join(surface_names)}")
    
    # --- TARGET RESOLUTION ---
    target_mode = args.target or "auto"
    
    if target_mode == "global":
        engine_scopes = ["."]
        print(f"  Target: global (all surfaces)")
    elif target_mode == "engine":
        if engine_target_config:
            # User-defined engine roots
            engine_scopes = engine_target_config.get("include_roots", engine_scopes)
            exclude_patterns = engine_target_config.get("exclude", [])
            print(f"  Target: engine (from engine_target.yml)")
            print(f"  Include: {', '.join(engine_scopes)}")
            if exclude_patterns:
                print(f"  Exclude: {', '.join(exclude_patterns)}")
        else:
            # No config file -- use primary inferred scope only
            if len(engine_scopes) > 1:
                engine_scopes = engine_scopes[:1]  # primary only
            print(f"  Target: engine (inferred primary: {', '.join(engine_scopes)})")
            print(f"  Tip: create engine_target.yml to define exact roots")
    elif target_mode != "auto":
        # Specific path
        engine_scopes = [target_mode]
        print(f"  Target: {target_mode}")

    # Filter entrypoints to engine scope for tracing
    # Always excluded from tracing
    trace_deny_prefixes = {"tests/", "test/", "docs/", "doc/", "__pycache__/"}
    
    # Add excludes from engine_target.yml if --target engine
    if target_mode == "engine" and engine_target_config:
        for excl in engine_target_config.get("exclude", []):
            # Strip glob chars for prefix matching
            clean = excl.replace("**/", "").replace("/**", "/").strip("/") + "/"
            trace_deny_prefixes.add(clean)
    
    def in_trace_scope(ep_path):
        rel = str(ep_path.relative_to(repo_root))
        rel_lower = rel.lower()
        
        # Always deny these
        if any(rel_lower.startswith(d) or ("/" + d) in rel_lower for d in trace_deny_prefixes):
            return False
        if rel_lower.split("/")[-1].startswith("test_"):
            return False
        if "archive/" in rel_lower:
            return False
            
        # If global scope, trace everything that passes deny
        if engine_scopes == ["."]:
            return True
        
        # Must be under at least one engine scope
        return any(rel == s or rel.startswith(s + "/") for s in engine_scopes)

    scoped_entrypoints = [ep for ep in all_entrypoints if in_trace_scope(ep)]
    excluded_count = len(all_entrypoints) - len(scoped_entrypoints)
    
    if excluded_count > 0:
        print(f"  Scoped to: {', '.join(engine_scopes)}")
        print(f"  Tracing {len(scoped_entrypoints)} in-scope entrypoints ({excluded_count} excluded).")

    # 3. Runtime Trace (scoped)
    runtime_files = set()
    relations = list(prelim_relations)  # start with static edges
    trace_meta = {"trace_mode": "disabled", "timeouts": [], "default_timeout": args.trace_timeout, "boot_timeout": args.boot_timeout, "entrypoints": []}
    if not args.no_trace and scoped_entrypoints:
        print(f"[3/6] Runtime tracing ({len(scoped_entrypoints)} entrypoints)...")
        hint_tagger = EntryTagger(repo_root)
        entrypoint_hints = {}
        for ep in scoped_entrypoints:
            rel = str(ep.relative_to(repo_root))
            intent = hint_tagger._get_intent(rel)
            role, _, _ = hint_tagger._infer_role(rel)
            entrypoint_hints[rel] = role if intent == "runtime" else f"intent:{intent}"

        tracer = RuntimeTracer(repo_root)
        runtime_files, trace_relations, trace_meta = tracer.run_trace(
            list(scoped_entrypoints),
            safe=args.safe,
            default_timeout=args.trace_timeout,
            boot_timeout=args.boot_timeout,
            trace_mode=args.trace_mode,
            entrypoint_hints=entrypoint_hints,
        )
        # Merge trace edges into relations
        relations.extend(trace_relations)
    elif args.no_trace:
        print("[3/6] Skipping runtime tracing.")

    # Compute trace completeness -- surfaces where tracing is the signal source
    trace_attempted = len(trace_meta.get("entrypoints", []))
    trace_timeouts = len(trace_meta.get("timeouts", []))
    trace_completeness = 1.0
    if trace_attempted > 0:
        trace_completeness = (trace_attempted - trace_timeouts) / trace_attempted
    trace_meta["completeness"] = round(trace_completeness, 4)
    trace_meta["partial"] = trace_completeness < 0.9
    if trace_meta["partial"]:
        print(f"  WARNING: Trace completeness {trace_completeness:.0%} -- "
              f"{trace_timeouts}/{trace_attempted} entrypoints timed out.")
        print(f"  Static graph is primary signal source. Runtime data is supplemental.")

    # LAYER 2: Synthesis -- merge runtime trace evidence into file data
    print("[4/6] Building execution graph...")
    
    # Update prelim_data with runtime trace evidence
    p1_temp_data = []
    for entry in prelim_data:
        f_path = repo_root / entry["file"]
        ev = list(entry["evidence"])
        if f_path in runtime_files and "runtime_trace" not in ev:
            ev.append("runtime_trace")
        
        conf = entry["confidence"]
        if f_path in runtime_files:
            conf = "HIGH"
        
        status = "ACTIVE" if conf in ["HIGH", "MED"] else "LEGACY"
        
        p1_temp_data.append({
            **entry,
            "evidence": ev,
            "confidence": conf,
            "status": status,
        })

    graph_engine = GraphEngine(repo_root, p1_temp_data, relations)
    graph = graph_engine.build_graph()
    clusters = graph_engine.classify_roots()

    cartography = CartographyEngine(repo_root, p1_temp_data, graph)
    folders = cartography.aggregate_folders()
    domains = cartography.detect_domains()

    # PHASE 4: Triangulation (engine_scopes already resolved above)
    print("[5/6] Triangulating entrypoints...")
    triangulator = Triangulator(repo_root, graph, p1_temp_data)
    target = triangulator.get_target_set(mode="active_or_runtime")
    
    # Constrain candidates to actual detected entrypoints
    detected_ep_rels = {str(ep.relative_to(repo_root)) for ep in all_entrypoints}
    candidates = triangulator.find_candidates(detected_entrypoints=detected_ep_rels)
    ranked = triangulator.rank_entrypoints(candidates, target, engine_scopes=engine_scopes)
    
    engine_config = {"max_k": args.k, "coverage_threshold": 0.95}
    triangulation_output = triangulator.select_engines(ranked, target, config=engine_config)
    
    tagger = EntryTagger(repo_root, triangulation_output, graph=graph, trace_meta=trace_meta)
    classified_entrypoints = tagger.tag_all()

    # PHASE 5: Enforcement
    print("[6/6] Checking policy violations...")
    enforcer = PolicyEnforcer(repo_root, p1_temp_data, graph, classified_entrypoints,
                              surface_resolver=scope_resolver)
    violations = enforcer.detect_violations()
    v_report = violations.get("tests_touching_runtime", {})
    total_v = v_report.get("summary", {}).get("total_violations", 0)

    # Compute per-surface metrics
    # Update scope_resolver with runtime-enriched file data so traced counts are correct
    scope_resolver.file_data = p1_temp_data
    scope_resolver._surface_cache = {}  # Clear cache to re-resolve with fresh data
    scope_resolver.tag_files(p1_temp_data)
    surface_metrics = scope_resolver.get_surface_metrics(graph)
    edge_classification = scope_resolver.classify_edges(graph)

    # FINAL REPORT
    reporter = Reporter(repo_root)
    final_report = reporter.generate(
        all_files_list, runtime_files, static_imports, text_refs, p1_temp_data,
        phase_two_data={"graph": graph, "clusters": clusters},
        cartography_data={"folders": folders, "domains": domains},
        triangulation_data=triangulation_output,
        classified_entrypoints=classified_entrypoints,
        policy_data=violations,
        metadata={**metadata, "trace": trace_meta, "engine_scope": engine_scopes},
        surface_data={
            "surfaces": surface_info["surfaces"],
            "metrics": surface_metrics,
            "cross_edges": {
                "count": edge_classification["cross_count"],
                "by_pair": {f"{k[0]}->{k[1]}": len(v)
                            for k, v in edge_classification.get("cross_by_pair", {}).items()},
            },
        },
    )

    # v2.1 Default Output Footer
    print("-" * 79)
    print("[OK] Scan complete.")
    print("-" * 79)

    # ---- BUILD CANDIDATE LIST WITH HARD GATING ----
    # Candidates MUST satisfy ALL of:
    #   1. in_engine_scope == True
    #   2. eligible_for_primary == True
    #   3. intent:runtime (not tests/docs/archive)
    #   4. NOT matching deny patterns (tests/, archive/, docs/, __pycache__)
    #   5. role in (infrastructure_boot, core_logic_driver, tooling_cli)
    deny_prefixes = ("tests/", "test/", "archive/", "docs/", "doc/", "__pycache__/")
    
    engine_candidates = []
    for ep in classified_entrypoints:
        path = ep.get("path", "")
        
        # Hard gate 1: must be in engine scope
        if not ep.get("in_engine_scope", False):
            continue
        
        # Hard gate 2: must be under one of the resolved engine roots
        if engine_scopes and engine_scopes != ["."]:
            in_root = any(
                path == scope or path.startswith(scope + "/")
                for scope in engine_scopes
            )
            if not in_root:
                continue
        
        # Hard gate 3: deny patterns
        path_lower = path.lower()
        if any(path_lower.startswith(d) or ("/" + d) in path_lower for d in deny_prefixes):
            continue
        if "/test_" in path_lower or path_lower.split("/")[-1].startswith("test_"):
            continue
        
        # Hard gate 4: must be eligible and runtime
        if not ep.get("eligible_for_primary", False):
            continue
        intents = set(ep.get("intent_tags", []))
        if "intent:runtime" not in intents:
            continue
        
        # Hard gate 5: role check
        role = ep.get("role", "")
        if role not in ("infrastructure_boot", "core_logic_driver", "tooling_cli"):
            continue
        
        engine_candidates.append(ep)

    engine_candidates.sort(key=lambda x: x.get("primary_candidate_score", 0), reverse=True)

    # ---- DETERMINE SIGNAL QUALITY ----
    trace_useful = len(runtime_files) > 5
    static_useful = len(static_edges) > 10
    signal_source = []
    if trace_useful:
        signal_source.append("runtime trace")
    if static_useful:
        signal_source.append("static import graph")
    if not signal_source:
        signal_source.append("naming heuristics + role scoring")

    # ---- GROUP CANDIDATES BY SCOPE ----
    scope_groups = {}
    for ep in engine_candidates:
        p = ep["path"]
        matched_scope = "."
        for scope in engine_scopes:
            if scope != "." and (p == scope or p.startswith(scope + "/")):
                matched_scope = scope
                break
        scope_groups.setdefault(matched_scope, []).append(ep)

    # Rank scopes by total score
    ranked_scopes = sorted(
        scope_groups.keys(),
        key=lambda s: sum(ep.get("primary_candidate_score", 0) for ep in scope_groups[s]),
        reverse=True
    )

    # Single-surface default: only show primary unless --surfaces all
    show_all_surfaces = args.surfaces == "all"
    primary_scope = ranked_scopes[0] if ranked_scopes else None
    secondary_scopes = ranked_scopes[1:] if len(ranked_scopes) > 1 else []

    # ---- PRINT: START THE ENGINE ----
    print(f"\n>> To start this project\n")
    
    if not trace_useful and static_useful:
        print(f"   Signal: {', '.join(signal_source)}")
        print(f"   (Runtime trace was not useful; ranked by static graph + heuristics)\n")
    elif signal_source:
        print(f"   Signal: {', '.join(signal_source)}\n")

    engine_paths = set()

    if not engine_candidates:
        print("   No engine entrypoints identified in scope.\n")
        if engine_scopes and engine_scopes != ["."]:
            print(f"   Try: python3 main.py {repo_root} --target global --k 10\n")
    elif primary_scope:
        # Print primary surface
        if engine_scopes and engine_scopes != ["."]:
            print(f"   Engine scope: {primary_scope}/\n")
        
        primary_eps = scope_groups.get(primary_scope, [])
        for idx, ep in enumerate(primary_eps[:args.k], start=1):
            engine_paths.add(ep["path"])
            score = int(ep.get("primary_candidate_score", 0.0) * 100)
            role = ep.get("role", "unknown")
            bd = ep.get("score_breakdown", {})
            label = {"infrastructure_boot": "boot", "core_logic_driver": "core", "tooling_cli": "cli"}.get(role, role)
            print(f"   {idx}. {ep['path']}")
            print(f"      score: {score}  role: {label}  coverage: {bd.get('coverage', 0):.0%}  centrality: {bd.get('centrality', 0):.0%}")

        top = primary_eps[0]
        print(f"\n   Run it:")
        print(f"     python3 {top['path']}")
        if len(primary_eps) > 1 and primary_eps[1].get("role") != primary_eps[0].get("role"):
            alt = primary_eps[1]
            print(f"     python3 {alt['path']}  (alternative: {alt.get('role', '')})")

        # Secondary surfaces
        if secondary_scopes and show_all_surfaces:
            for scope in secondary_scopes:
                scope_eps = scope_groups[scope]
                print(f"\n   Other surface: {scope}/")
                for idx, ep in enumerate(scope_eps[:args.k], start=1):
                    engine_paths.add(ep["path"])
                    score = int(ep.get("primary_candidate_score", 0.0) * 100)
                    bd = ep.get("score_breakdown", {})
                    label = {"infrastructure_boot": "boot", "core_logic_driver": "core", "tooling_cli": "cli"}.get(ep.get("role", ""), ep.get("role", ""))
                    print(f"      {idx}. {ep['path']}")
                    print(f"         score: {score}  role: {label}  coverage: {bd.get('coverage', 0):.0%}  centrality: {bd.get('centrality', 0):.0%}")
                print(f"      Run: python3 {scope_eps[0]['path']}")
        elif secondary_scopes:
            # Mention they exist without showing details
            others = ", ".join(f"{s}/" for s in secondary_scopes)
            print(f"\n   Other surfaces detected: {others}")
            print(f"   Rerun with --surfaces all to see them.")

    # ---- PRINT: AVAILABLE TOOLS ----
    print(f"\n>> Tools and utilities\n")

    tools = []
    for ep in classified_entrypoints:
        p = ep.get("path", "")
        if not p or p in engine_paths:
            continue
        if ep.get("role") == "test_harness" or "test_" in p.lower().split("/")[-1]:
            continue
        intents = set(ep.get("intent_tags", []))
        is_tool = "intent:tools" in intents or "intent:gui" in intents
        out_of_scope = not ep.get("in_engine_scope", True)
        if is_tool or out_of_scope:
            tools.append(ep)

    if tools:
        by_domain = {}
        for t in tools:
            p1_entry = next((i for i in p1_temp_data if i["file"] == t["path"]), {})
            dom = p1_entry.get("domain", "tools")
            by_domain.setdefault(dom, []).append(t["path"])

        for dom, files in sorted(by_domain.items()):
            if files and dom != "unknown":
                print(f"   {dom:<20}: {files[0]}")
    else:
        print("   (none identified)")

    # ---- PRINT: ISSUES ----
    print(f"\n>> Issues\n")
    print(f"   {total_v:<3} test boundary violations")
    active_in_archive = sum(1 for f in p1_temp_data if f["status"] == "ACTIVE" and "archive" in f["file"].lower())
    print(f"   {active_in_archive:<3} active files in archive/")
    shadowed = len(violations.get("shadowed_modules", []))
    print(f"   {shadowed:<3} shadowed modules")

    # Cross-surface violations
    cross_v = violations.get("cross_surface", {})
    cross_total = cross_v.get("summary", {}).get("total_cross_edges", 0)
    cross_unauth = cross_v.get("summary", {}).get("unauthorized", 0)
    if cross_total > 0:
        print(f"   {cross_total:<3} cross-surface edges ({cross_unauth} unauthorized)")
        for pair, count in cross_v.get("summary", {}).get("by_pair", {}).items():
            print(f"       {pair}: {count}")

    if engine_scopes and engine_scopes != ["."]:
        scope_target = {
            rec["file"]
            for rec in p1_temp_data
            if any(rec["file"] == s or rec["file"].startswith(s + "/") for s in engine_scopes)
        }
        scope_covered = len(
            scope_target.intersection({
                r["file"] for r in p1_temp_data if "runtime_trace" in r.get("evidence", []) or r["status"] == "ACTIVE"
            })
        )
        scope_ratio = (scope_covered / len(scope_target)) if scope_target else 0.0
        print(f"   Engine coverage: {scope_ratio:.0%} of {', '.join(engine_scopes)}")

    # ---- PRINT: PER-SURFACE SUMMARY ----
    if surface_metrics and len(surface_metrics) > 1:
        print(f"\n>> Surface Breakdown\n")
        for sid, m in sorted(surface_metrics.items(), key=lambda x: -x[1]["active"]):
            cov_pct = f"{m['coverage']:.0%}"
            print(f"   {sid:<24} {m['file_count']:>5} files  {m['active']:>4} active  "
                  f"{m['runtime']:>3} traced  coverage: {cov_pct}")
            if m["cross_edges_out"] > 0 or m["cross_edges_in"] > 0:
                print(f"   {'':24} cross: {m['cross_edges_out']} out / {m['cross_edges_in']} in")

    # ---- PRINT: SCAN STATS ----
    print(f"\n>> Scan stats\n")
    print(f"   {len(all_files_list)} files scanned")
    print(f"   {len(all_entrypoints)} entrypoints detected ({len(scoped_entrypoints)} in scope)")
    print(f"   {len(runtime_files)} runtime-traced files")
    print(f"   {len(static_imports)} statically imported, {len(static_edges)} import edges")
    print(f"   {len(text_refs)} text-referenced files")
    if engine_scopes and engine_scopes != ["."]:
        print(f"   Inferred engine scope: {', '.join(engine_scopes)}")

    print(f"\n   Full report: reports/usage_index.json")
    print(f"   HTML viewer: reports/report_viewer.html")
    print("-" * 79)

    # Return scan state for clean.py / main() to consume
    return {
        "repo_root": repo_root,
        "file_data": p1_temp_data,
        "graph": graph,
        "classified_entrypoints": classified_entrypoints,
        "engine_scopes": engine_scopes,
        "engine_target_config": engine_target_config,
        "violations": violations,
    }


def run_clean(repo_root, file_data, graph, classified_entrypoints,
              engine_scopes, engine_target_config=None,
              prune=False, quarantine=False):
    """Execute surgery (prune/quarantine) using pre-computed scan data.
    
    Can be called from main.py (after scan) or clean.py (from saved JSON).
    """
    if prune:
        from pruning_engine import PruningEngine
        print("[CLEAN] Generating pruning plan...")
        pruner = PruningEngine(repo_root, file_data, graph)
        engine_roots = [e["path"] for e in classified_entrypoints if e.get("eligible_for_primary")]
        prune_data = pruner.generate_plan(engine_roots)
        pruner.generate_script(prune_data)

    if quarantine:
        from quarantine_engine import QuarantineEngine
        print("[CLEAN] Generating quarantine plan...")
        quarantine_eng = QuarantineEngine(
            repo_root, file_data, graph,
            classified_entrypoints, engine_scopes,
            engine_target_config=engine_target_config
        )
        q_plan = quarantine_eng.build_plan()
        quarantine_eng.write_scripts(q_plan)


def main():
    """Backward-compatible entry point: scan + optional surgery."""
    parser = build_arg_parser(include_surgery=True)
    args = parser.parse_args()

    if os.environ.get("__RIE_TRACING__"):
        return

    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Error: Path {repo_root} does not exist.")
        return

    # Scan phase (always runs)
    scan_data = run_scan(repo_root, args)
    if not scan_data:
        return

    # Surgery phase (only if flags set)
    if getattr(args, "prune", False) or getattr(args, "quarantine", False):
        run_clean(
            scan_data["repo_root"],
            scan_data["file_data"],
            scan_data["graph"],
            scan_data["classified_entrypoints"],
            scan_data["engine_scopes"],
            engine_target_config=scan_data.get("engine_target_config"),
            prune=getattr(args, "prune", False),
            quarantine=getattr(args, "quarantine", False),
        )


if __name__ == "__main__":
    main()
