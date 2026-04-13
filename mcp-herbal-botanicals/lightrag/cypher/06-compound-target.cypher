// Compounds and the protein targets they interact with
MATCH (c:Compound)-[r]->(t:Target)
RETURN c, r, t
LIMIT 50;
