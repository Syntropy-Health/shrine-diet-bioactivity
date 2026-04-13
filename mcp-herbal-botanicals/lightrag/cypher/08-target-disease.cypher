// Targets associated with diseases
MATCH (t:Target)-[r]->(d:Disease)
RETURN t, r, d
LIMIT 50;
