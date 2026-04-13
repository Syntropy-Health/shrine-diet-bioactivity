// Data quality: nodes with UNKNOWN type or empty descriptions
MATCH (n)
WHERE n.entity_type = 'UNKNOWN'
   OR n.description IS NULL
   OR n.description = ''
   OR n.description = 'UNKNOWN'
RETURN n.entity_id AS id,
       n.entity_type AS type,
       n.description AS description
LIMIT 20;
