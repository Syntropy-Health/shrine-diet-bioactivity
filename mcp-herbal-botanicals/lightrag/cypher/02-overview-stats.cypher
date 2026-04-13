// Total nodes, edges, and connected vs orphan breakdown
MATCH (n) WITH COUNT(n) AS total_nodes
MATCH ()-[r]->() WITH total_nodes, COUNT(r) AS total_edges
OPTIONAL MATCH (o) WHERE NOT (o)--() WITH total_nodes, total_edges, COUNT(o) AS orphans
RETURN total_nodes, total_edges, orphans, total_nodes - orphans AS connected;
