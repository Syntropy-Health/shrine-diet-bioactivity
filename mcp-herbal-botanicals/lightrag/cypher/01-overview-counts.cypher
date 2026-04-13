// Entity types and counts
MATCH (n)
RETURN n.entity_type AS type, COUNT(n) AS count
ORDER BY count DESC;
