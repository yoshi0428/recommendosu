SELECT s.variant_id, v.beatmap_id, s.error
FROM classifier_prediction_status s
JOIN beatmap_variants v ON v.variant_id = s.variant_id
WHERE s.status = 'failed'