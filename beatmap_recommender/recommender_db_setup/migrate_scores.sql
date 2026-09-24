ATTACH 'recommender.local.db' AS target_db;

-- Do not use BEGIN TRANSACTION here... an implicit one is already active
INSERT INTO target_db.scores SELECT * FROM main.scores;

-- Force the active implicit transaction to write to disk and clear the lock
COMMIT;

-- Now the database can safely be detached
DETACH DATABASE target_db;