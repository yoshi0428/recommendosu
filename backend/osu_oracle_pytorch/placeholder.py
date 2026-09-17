import sqlite3

conn = sqlite3.connect('./scripts/beatmaps.db')
conn.execute('ALTER TABLE beatmaps ADD COLUMN star_rating REAL')
conn.commit()
conn.close()