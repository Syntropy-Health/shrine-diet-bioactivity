// Deep-dive: all connections from a single herb
// Change the entity_id to explore different herbs
MATCH (h:Herb {entity_id: 'Abelmoschus esculentus'})-[r]->(n)
RETURN h, r, n;
