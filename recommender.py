from typing import Dict, Any


def build_recommendation(entrypoint: Dict[str, Any]) -> Dict[str, str]:
    path = str(entrypoint.get("path", "")).lower()
    score = float(entrypoint.get("primary_candidate_score", 0.0) or 0.0)
    timed_out = bool(entrypoint.get("trace_timed_out", False))
    import_only = bool(entrypoint.get("trace_mode") == "import-only" or entrypoint.get("trace_import_only", False))

    validator_or_gui = (
        "validator" in path
        or "/gui/" in path
        or "_gui" in path
    )

    if timed_out or import_only:
        return {
            "label": "low-confidence",
            "guidance": "timeout/import-only trace observed; re-run with deeper tracing before treating this as confirmed",
        }

    if validator_or_gui:
        return {
            "label": "low-confidence",
            "guidance": "validator/GUI-like path signature detected; keep as auxiliary entrypoint",
        }

    if score >= 0.75:
        return {"label": "confirmed", "guidance": ""}

    return {
        "label": "low-confidence",
        "guidance": "multi-surface or sparse evidence; follow decision-tree guidance and collect more traces",
    }
