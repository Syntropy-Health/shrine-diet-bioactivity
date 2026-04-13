// Multi-hop: herb → compound → food
MATCH (h:Herb)-[r1]->(c:Compound)-[r2]->(f:Food)
RETURN h, r1, c, r2, f
LIMIT 50;
