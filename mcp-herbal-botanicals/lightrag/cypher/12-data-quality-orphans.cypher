// Data quality: orphan nodes with no relationships
MATCH (n) WHERE NOT (n)--()
RETURN n.entity_type AS type, COUNT(n) AS orphan_count
ORDER BY orphan_count DESC;
