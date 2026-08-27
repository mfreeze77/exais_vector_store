"""Example only: load nodes.jsonl / edges.jsonl into NetworkX after scraping."""
import json
from pathlib import Path

import networkx as nx

root = Path("output/topeka")
graph = nx.MultiDiGraph()

for line in (root / "nodes.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    graph.add_node(row["id"], **row)

for line in (root / "edges.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    graph.add_edge(row["source"], row["target"], key=row["id"], **row)

print(graph.number_of_nodes(), "nodes")
print(graph.number_of_edges(), "edges")
