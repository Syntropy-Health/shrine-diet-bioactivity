// Herbs and the symptoms they treat
MATCH (h:Herb)-[r]->(s:Symptom)
RETURN h.entity_id AS herb,
       r.description AS relationship,
       s.entity_id AS symptom
LIMIT 30;
