// All connected nodes and edges (the interesting part of the graph)
MATCH (a)-[r]->(b)
RETURN a, r, b
LIMIT 200;
