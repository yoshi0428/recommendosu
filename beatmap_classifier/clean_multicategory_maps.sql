-- Removes beatmaps labeled with two or more tournament slots (the rows
-- view_multicategory_maps.sql shows), since their label is ambiguous.
-- Labels are counted over all of a beatmap's variants, so a map pooled as
-- NM1 (on its NM variant) and HD2 (on its HD variant) is removed too.
-- populate.py runs this after populating the database.
BEGIN TRANSACTION;

CREATE TEMP TABLE deleted_beatmaps AS
SELECT beatmap_id
FROM (
SELECT
    bv.beatmap_id,
    SUM(
         CASE WHEN tp.nm1 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.nm2 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.nm3 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.nm4 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.nm5 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.nm6 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.nm7 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.nm8 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.dt1 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.dt2 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.dt3 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.dt4 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.dt5 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hr1 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hr2 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hr3 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hr4 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hd1 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hd2 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hd3 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.hd4 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.fm1 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.fm2 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.fm3 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.fm4 IS NOT NULL THEN 1 ELSE 0 END +
         CASE WHEN tp.tb IS NOT NULL THEN 1 ELSE 0 END
    ) AS label_count
FROM tournament_predictions tp
JOIN beatmap_variants bv ON bv.variant_id = tp.variant_id
GROUP BY bv.beatmap_id
)
WHERE label_count >= 2;

-- Foreign keys aren't enforced (no PRAGMA foreign_keys), so ON DELETE
-- CASCADE won't remove these for us.
DELETE FROM tournament_predictions
WHERE variant_id IN (
    SELECT variant_id FROM beatmap_variants
    WHERE beatmap_id IN (SELECT beatmap_id FROM deleted_beatmaps)
);

DELETE FROM beatmap_variants
WHERE beatmap_id IN (SELECT beatmap_id FROM deleted_beatmaps);

DELETE FROM beatmaps
WHERE beatmap_id IN (SELECT beatmap_id FROM deleted_beatmaps);

DROP TABLE deleted_beatmaps;

COMMIT;
