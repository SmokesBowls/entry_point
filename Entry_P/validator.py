"""
Validator
Validates internal consistency of the analysis pipeline:
  - All referenced files exist
  - Graph edges point to known nodes
  - No contradictions between evidence and classification
"""
from pathlib import Path


class Validator:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def validate_file_data(self, file_data: list) -> dict:
        """Validate Phase 1 file data for consistency."""
        errors = []
        warnings = []

        known_files = {entry["file"] for entry in file_data}

        for entry in file_data:
            rel = entry["file"]
            full_path = self.repo_root / rel

            # Check file exists
            if not full_path.exists():
                warnings.append(f"File not found: {rel}")

            # Check evidence/status consistency
            evidence = entry.get("evidence", [])
            status = entry.get("status", "LEGACY")
            confidence = entry.get("confidence", "LOW")

            if "runtime_trace" in evidence and status == "LEGACY":
                errors.append(f"Runtime-traced file marked LEGACY: {rel}")

            if confidence == "HIGH" and status == "LEGACY":
                errors.append(f"HIGH confidence file marked LEGACY: {rel}")

            if confidence == "LOW" and status == "ACTIVE":
                warnings.append(f"LOW confidence file marked ACTIVE: {rel}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "files_checked": len(file_data),
        }

    def validate_graph(self, graph: dict, file_data: list) -> dict:
        """Validate that graph edges reference known files."""
        known_files = {entry["file"] for entry in file_data}
        errors = []

        for src, targets in graph.items():
            if src not in known_files:
                errors.append(f"Graph node not in file_data: {src}")
            for tgt in targets:
                if tgt not in known_files:
                    errors.append(f"Graph edge target not in file_data: {src} -> {tgt}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "nodes_checked": len(graph),
        }
