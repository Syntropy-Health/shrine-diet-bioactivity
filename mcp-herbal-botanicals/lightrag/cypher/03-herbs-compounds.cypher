// Herbs and the compounds they contain
MATCH (h:Herb)-[r]->(c:Compound)
RETURN h, r, c
LIMIT 100;
