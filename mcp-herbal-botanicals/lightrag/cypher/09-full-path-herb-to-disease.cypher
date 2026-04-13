// Full multi-hop path: herb → compound → target → disease
MATCH path = (h:Herb)-[r1]->(c:Compound)-[r2]->(t:Target)-[r3]->(d:Disease)
RETURN path
LIMIT 25;
