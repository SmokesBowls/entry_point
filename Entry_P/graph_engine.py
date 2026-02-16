"""
Phase 2: Graph Engine
Builds the execution/dependency graph from Phase 1 evidence.
Nodes = files, Edges = import/load relationships.
Provides reachability analysis and root classification.
"""
from pathlib import Path
from collections import defaultdict, deque


class GraphEngine:
    def __init__(self, repo_root: Path, file_data: list, static_relations: list, dynamic_relations: list = None):
        """
        Args:
            repo_root: Path to the repository root
            file_data: list of dicts from Phase 1 with keys: file, evidence, confidence, status
            static_relations: list of (source, target) tuples from static analysis
            dynamic_relations: list of (source, target) tuples from runtime tracing
        """
        self.repo_root = repo_root
        self.file_data = file_data
        self.static_relations = static_relations
        self.dynamic_relations = dynamic_relations or []
        self.graph = {}  # node -> set of (neighbor_rel, is_dynamic)
        self.reverse_graph = defaultdict(set)
        self._edges_meta = {} # (src, tgt) -> {"dynamic": bool}

    def build_graph(self) -> dict:
        """
        Build the directed dependency graph.
        Returns the adjacency list: {file_rel: set of imported file_rels}
        """
        self.graph = defaultdict(set)
        self.reverse_graph = defaultdict(set)
        self._edges_meta = {}

        # Add all files as nodes
        for entry in self.file_data:
            rel = entry["file"]
            if rel not in self.graph:
                self.graph[rel] = set()

        # Add static edges first (primary backbone)
        for src, tgt in self.static_relations:
            src_rel = self._to_rel(src)
            tgt_rel = self._to_rel(tgt)
            if src_rel and tgt_rel and src_rel != tgt_rel:
                self.graph[src_rel].add(tgt_rel)
                self.reverse_graph[tgt_rel].add(src_rel)
                self._edges_meta[(src_rel, tgt_rel)] = {"dynamic": False}

        # Add dynamic edges (optional enrichment)
        for src, tgt in self.dynamic_relations:
            src_rel = self._to_rel(src)
            tgt_rel = self._to_rel(tgt)
            if src_rel and tgt_rel and src_rel != tgt_rel:
                self.graph[src_rel].add(tgt_rel)
                self.reverse_graph[tgt_rel].add(src_rel)
                # Only mark as dynamic if it wasn't already a static edge
                if (src_rel, tgt_rel) not in self._edges_meta:
                    self._edges_meta[(src_rel, tgt_rel)] = {"dynamic": True}

        return dict(self.graph)

    def get_edge_metadata(self) -> dict:
        """Return metadata for all edges."""
        return self._edges_meta

    def _to_rel(self, path) -> str | None:
        """Convert a path to a relative string."""
        if isinstance(path, Path):
            try:
                return str(path.relative_to(self.repo_root))
            except ValueError:
                return str(path)
        if isinstance(path, str):
            # If it's an absolute path, try to make relative
            try:
                return str(Path(path).relative_to(self.repo_root))
            except (ValueError, TypeError):
                return path
        return None

    def get_reachable(self, start: str) -> set:
        """BFS to find all files reachable from a starting node."""
        visited = set()
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for neighbor in self.graph.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        return visited

    def classify_roots(self) -> dict:
        """
        Classify files by their role in the graph:
        - roots: files with no incoming edges (nothing imports them)
        - leaves: files with no outgoing edges (they import nothing in repo)
        - connectors: files with both incoming and outgoing edges
        """
        all_nodes = set(self.graph.keys())
        has_incoming = set()
        for targets in self.graph.values():
            has_incoming.update(targets)

        roots = all_nodes - has_incoming
        leaves = {n for n in all_nodes if not self.graph.get(n)}
        connectors = all_nodes - roots - leaves

        return {
            "roots": sorted(roots),
            "leaves": sorted(leaves),
            "connectors": sorted(connectors),
            "total_nodes": len(all_nodes),
            "total_edges": sum(len(v) for v in self.graph.values()),
        }

    def get_active_subgraph(self) -> dict:
        """Return the subgraph containing only ACTIVE files."""
        active_files = {e["file"] for e in self.file_data if e.get("status") == "ACTIVE"}
        subgraph = {}
        for node, neighbors in self.graph.items():
            if node in active_files:
                subgraph[node] = neighbors.intersection(active_files)
        return subgraph
