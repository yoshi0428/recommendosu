BEGIN TRANSACTION;

CREATE TEMP TABLE deleted_beatmaps AS
SELECT DISTINCT beatmap_id
FROM beatmap_variants
WHERE variant_id IN (4045, 4713, 7533);

DELETE FROM beatmap_variants
WHERE variant_id IN (4045, 4713, 7533);

DELETE FROM beatmaps
WHERE beatmap_id IN (
    SELECT beatmap_id
    FROM deleted_beatmaps
)
AND NOT EXISTS (
    SELECT 1
    FROM beatmap_variants v
    WHERE v.beatmap_id = beatmaps.beatmap_id
);

DROP TABLE deleted_beatmaps;

COMMIT;