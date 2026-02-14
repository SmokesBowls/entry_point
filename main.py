#!/usr/bin/env python3
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
from pruning_engine import PruningEngine
from domain_resolver import DomainResolver
from scope_resolver import ScopeResolver
import yaml
import json
import uuid
import hashlib
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Universal Active Code Filter (uacf)")
    parser.add_argument("repo", nargs="?", default=".", help="Path to the repository to analyze (default: current dir)")
    parser.add_argument("--no-trace", action="store_true", help="Skip runtime tracing")
    parser.add_argument("--k", type=int, default=10, help="Max entrypoints to return")
    parser.add_argument("--target", help="Optional target scope (engine, tools, global)")
    parser.add_argument("--prune", action="store_true", help="Generate a safe pruning plan and script")
    
    # Safety Flags
    parser.add_argument("--no-safe", action="store_false", dest="safe", help="Disable Simulation Mode")
    parser.set_defaults(safe=True)
    
    args = parser.parse_args()

    if os.environ.get("__RIE_TRACING__"):
        return

    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Error: Path {repo_root} does not exist.")
        return

    # Metadata & Config
    run_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    print(f"--- Repository Integrity Engine (Core) v2.1: {repo_root} ---")
    if args.safe:
        print("🛡️  Layer 0: Simulation Mode ACTIVE")
    
    # 0. Discovery
    all_files_list = {p for p in repo_root.rglob("*") if p.is_file() and ".git" not in p.parts and "reports" not in p.parts}
    
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

    # 1. Entrypoints
    detector = EntrypointDetector(repo_root)
    entrypoints = detector.detect_all()

    # 2. Trace
    runtime_files = set()
    relations = []
    if not args.no_trace and entrypoints:
        tracer = RuntimeTracer(repo_root)
        runtime_files, relations = tracer.run_trace(list(entrypoints), safe=args.safe)

    # 3. Static/Text
    analyzer = StaticAnalyzer(repo_root)
    static_imports = analyzer.analyze_repo()
    scanner = TextScanner(repo_root)
    text_refs = scanner.scan_all(all_files_list)

    # LAYER 2: Synthesis
    p1_temp_data = [] 
    for f in all_files_list:
        rel = str(f.relative_to(repo_root))
        ev = []
        if f in runtime_files: ev.append("runtime_trace")
        if f in static_imports: ev.append("static_import")
        res = resolver.resolve(rel)
        conf = "LOW"
        if f in runtime_files: conf = "HIGH"
        elif f in static_imports: conf = "MED"
        p1_temp_data.append({
            "file": rel, "evidence": ev, "confidence": conf,
            "status": "ACTIVE" if conf in ["HIGH", "MED"] else "LEGACY",
            "domain": res["domain"], "intent": res["intent"], "domain_source": res["source"]
        })

    graph_engine = GraphEngine(repo_root, p1_temp_data, relations)
    graph = graph_engine.build_graph()
    clusters = graph_engine.classify_roots()

    cartography = CartographyEngine(repo_root, p1_temp_data, graph)
    folders = cartography.aggregate_folders()
    domains = cartography.detect_domains()

    # v2.1 Scope Inference
    scope_resolver = ScopeResolver(repo_root, p1_temp_data, graph)
    inferred = scope_resolver.infer_scopes()
    
    # Handle --target
    engine_scopes = inferred["engine_scopes"]
    if args.target == "global":
        engine_scopes = ["."]
    elif args.target and args.target != "engine":
        # Specific target overrides
        engine_scopes = [args.target]

    # PHASE 4: Triangulation
    triangulator = Triangulator(repo_root, graph, p1_temp_data)
    target = triangulator.get_target_set(mode="active_or_runtime")
    candidates = triangulator.find_candidates()
    ranked = triangulator.rank_entrypoints(candidates, target, engine_scopes=engine_scopes)
    
    engine_config = {"max_k": args.k, "coverage_threshold": 0.95}
    triangulation_output = triangulator.select_engines(ranked, target, config=engine_config)
    
    tagger = EntryTagger(repo_root, triangulation_output)
    classified_entrypoints = tagger.tag_all()

    # PHASE 5: Enforcement
    enforcer = PolicyEnforcer(repo_root, p1_temp_data, graph, classified_entrypoints)
    violations = enforcer.detect_violations()
    v_report = violations.get("tests_touching_runtime", {})
    total_v = v_report.get("summary", {}).get("total_violations", 0)

    # PHASE 6: Pruning
    if args.prune:
        pruner = PruningEngine(repo_root, p1_temp_data, graph)
        engine_roots = [e["path"] for e in classified_entrypoints]
        prune_data = pruner.generate_plan(engine_roots)
        pruner.generate_script(prune_data)

    # FINAL REPORT
    reporter = Reporter(repo_root)
    final_report = reporter.generate(
        all_files_list, runtime_files, static_imports, text_refs, p1_temp_data,
        phase_two_data={"graph": graph, "clusters": clusters},
        cartography_data={"folders": folders, "domains": domains},
        triangulation_data=triangulation_output,
        policy_data=violations,
        metadata=metadata
    )

    # v2.1 Default Output Footer
    print("-" * 79)
    print("✅ Scan complete. Recommended next steps:")
    print("-" * 79)
    print("\n🔹 Start the engine")
    print("These are the confirmed main entrypoints for this repository:\n")
    
    main_count = 0
    engine_paths = set()
    for ep in classified_entrypoints:
        is_main_role = ep["role"] in ["infrastructure_boot", "core_logic_driver", "tooling_cli"]
        if is_main_role and ep.get("eligible_for_primary", True):
            main_count += 1
            engine_paths.add(ep["path"])
            conf = int(ep["primary_candidate_score"] * 100)
            print(f"{main_count}. {ep['path']:<50} confidence: {conf}%")
            if main_count >= 5: break

    if main_count == 0:
        print(" (No primary engine entrypoints identified)")

    print(f"\nRun a full deep trace:")
    if classified_entrypoints:
        print(f"  uacf trace {classified_entrypoints[0]['path']}")
    
    print("-" * 79)
    print("\n🔹 Available tools\n")
    
    # List tools (non-engine entrypoints)
    tools = []
    for ep in classified_entrypoints:
        if ep["path"] in engine_paths: continue
        if ep["role"] == "test_harness" or "test" in ep["path"].lower(): continue
        # Only show things with some behavioral signature or non-engine scope
        if ep["role"] != "unknown" or ep.get("in_engine_scope") == False:
            tools.append(ep)

    if tools:
        # Group by folder/domain
        by_domain = {}
        for t in tools:
            p1_entry = next((i for i in p1_temp_data if i["file"] == t["path"]), {})
            dom = p1_entry.get("domain", "tools")
            by_domain.setdefault(dom, []).append(t["path"])
        
        for dom, files in sorted(by_domain.items()):
            if files and dom != "unknown":
                print(f" {dom:<20}: {files[0]}")
    else:
        print(" (No auxiliary tools identified)")

    print("-" * 79)
    print("\n🔹 Issues found\n")
    print(f" {total_v:<3} test boundary violations")
    active_in_archive = sum(1 for f in p1_temp_data if f["status"] == "ACTIVE" and "archive" in f["file"].lower())
    print(f" {active_in_archive:<3} active files in archive/")
    shadowed = len(violations.get("shadowed_modules", []))
    print(f" {shadowed:<3} shadowed modules")

    print(f"\nView full interactive report: uacf report")
    print("-" * 79)

if __name__ == "__main__":
    main()
