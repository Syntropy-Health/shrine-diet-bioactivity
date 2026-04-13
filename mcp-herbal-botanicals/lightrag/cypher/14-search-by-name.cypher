// Search for entities by name (case-insensitive substring)
// Change 'curcumin' to search for anything
MATCH (n)
WHERE toLower(n.entity_id) CONTAINS 'curcumin'
   OR toLower(n.description) CONTAINS 'curcumin'
RETURN n.entity_id AS id,
       n.entity_type AS type,
       n.description AS description
LIMIT 10;
