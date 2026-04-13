// All relationships with human-readable descriptions
MATCH (a)-[r]->(b)
RETURN a.entity_id AS from,
       a.entity_type AS from_type,
       r.description AS relationship,
       b.entity_id AS to,
       b.entity_type AS to_type
ORDER BY a.entity_type, a.entity_id
LIMIT 50;
