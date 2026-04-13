// Expand neighborhood: find all nodes within 2 hops of a given entity
// Change the entity_id to explore different starting points
MATCH path = (start {entity_id: 'QUERCETIN'})-[*1..2]-(neighbor)
RETURN path
LIMIT 100;
