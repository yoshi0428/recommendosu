import sqlite3

def find_variant_mod_collisions(conn):
    """
    Find cases where multiple DB rows represent the same canonical
    (beatmap_id, mods) pair.
    """

    rows = conn.execute(
        """
        SELECT
            variant_id,
            beatmap_id,
            mods
        FROM beatmap_variants
        ORDER BY beatmap_id, variant_id
        """
    ).fetchall()

    seen = {}
    collisions = []

    for variant_id, beatmap_id, mods in rows:

        beatmap_id = str(beatmap_id)
        canonical_mods = canonicalize_mods(mods)
        key = (beatmap_id, canonical_mods,)

        if key in seen:

            collisions.append({
                "beatmap_id": beatmap_id,
                "mods": canonical_mods,
                "variant_ids": [
                    seen[key],
                    variant_id,
                ],
            })

        else:
            seen[key] = variant_id

    return collisions

def canonicalize_variant_mods(conn):
    rows = conn.execute(
        """
        SELECT
            variant_id,
            mods
        FROM beatmap_variants
        """
    ).fetchall()

    updates = []

    for variant_id, mods in rows:

        canonical_mods = canonicalize_mods(mods)

        if canonical_mods != mods:
            print(f"variant {variant_id}: {mods} -> {canonical_mods}")
            updates.append((canonical_mods, variant_id,))

    if not updates:
        print("All variant mod strings are already canonical.")
        return

    conn.executemany(
        """
        UPDATE beatmap_variants
        SET mods = ?
        WHERE variant_id = ?
        """,
        updates,
    )

    conn.commit()
    print(f"Updated {len(updates)} variant mod strings.")

########################################################
########################################################
########################################################

conn = sqlite3.connect("../../test_everything.db")

conn.execute("PRAGMA foreign_keys=ON")

collisions = find_variant_mod_collisions(conn)

if collisions:
    print("Cannot safely canonicalize variants.")
    for collision in collisions[:20]:
        print(collision)
else:
    canonicalize_variant_mods(conn)

conn.close()