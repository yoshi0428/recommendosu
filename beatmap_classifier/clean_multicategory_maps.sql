-- Removes variants labeled with two or more tournament slots (the rows
-- view_multicategory_maps.sql shows), since their label is ambiguous.
-- osu_parser_modded.py runs this after populating the database.
BEGIN TRANSACTION;

CREATE TEMP TABLE deleted_variants AS
SELECT variant_id
FROM tournament_predictions
WHERE
    (CASE WHEN nm1 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN nm2 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN nm3 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN nm4 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN nm5 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN nm6 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN dt1 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN dt2_and_dt3 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN dt4 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN hr1 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN hr2 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN hr3 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN hd1 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN hd2 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN hd3 IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN tiebreaker IS NOT NULL THEN 1 ELSE 0 END) >= 2;

CREATE TEMP TABLE deleted_beatmaps AS
SELECT DISTINCT beatmap_id
FROM beatmap_variants
WHERE variant_id IN (SELECT variant_id FROM deleted_variants);

-- Foreign keys aren't enforced (no PRAGMA foreign_keys), so ON DELETE
-- CASCADE won't remove these for us.
DELETE FROM tournament_predictions
WHERE variant_id IN (SELECT variant_id FROM deleted_variants);

DELETE FROM beatmap_variants
WHERE variant_id IN (SELECT variant_id FROM deleted_variants);

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

DROP TABLE deleted_variants;
DROP TABLE deleted_beatmaps;

COMMIT;
