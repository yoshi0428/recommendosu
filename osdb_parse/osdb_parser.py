import struct

"""
To get the .osdb files, I used this: https://github.com/roogue/osu-collector-dl

Trial and error required to get the right beatmap counts
Usually around -1 to -5 from the collection count shown in https://osucollector.com worked for me
"""
COUNT_DICT = {
    "NM2": 887,
    "NM3": 928,
    "NM4": 771,
    "HR1": 774,
    "HR2": 683,
    "DT2 and DT3": 1087,
}
NAME = "HR2"
FILENAME = f"./inputs/{NAME}.osdb"
ACTUAL_BEATMAP_COUNT = COUNT_DICT[NAME]

class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        if self.pos + n > len(self.data):
            raise EOFError(
                f"Unexpected EOF at offset {self.pos:#x}, "
                f"wanted {n} bytes"
            )

        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def byte(self):
        return self.read(1)[0]

    def int32(self):
        return struct.unpack("<i", self.read(4))[0]

    def double(self):
        return struct.unpack("<d", self.read(8))[0]

    def string(self):
        length = self.byte()

        if length == 0:
            return ""

        return self.read(length).decode("utf-8")


def parse_beatmap(r):
    """
    FOR TESTING PURPOSES

    Parse one beatmap.

    Some records in this file appear to omit beatmapset_id,
    while others contain it. Detect which layout is present.
    """

    start = r.pos

    beatmap_id = r.int32()

    # ---------------------------------------------------------
    # Try the format WITH beatmapset_id first.
    # ---------------------------------------------------------
    try:
        test_pos = r.pos

        beatmapset_id = r.int32()

        artist = r.string()
        title = r.string()
        difficulty = r.string()
        md5 = r.string()
        comment = r.string()
        mode = r.byte()
        stars = r.double()

        # If all of that worked, use this format.
        return {
            "beatmap_id": beatmap_id,
            "beatmapset_id": beatmapset_id,
            "artist": artist,
            "title": title,
            "difficulty": difficulty,
            "md5": md5,
            "comment": comment,
            "mode": mode,
            "stars": stars,
        }

    except (UnicodeDecodeError, EOFError, struct.error):
        # The record probably doesn't contain a beatmapset ID.
        r.pos = start + 4

    # ---------------------------------------------------------
    # Format WITHOUT beatmapset_id.
    # ---------------------------------------------------------

    artist = r.string()
    title = r.string()
    difficulty = r.string()
    md5 = r.string()
    comment = r.string()
    mode = r.byte()
    stars = r.double()

    return {
        "beatmap_id": beatmap_id,
        "beatmapset_id": None,
        "artist": artist,
        "title": title,
        "difficulty": difficulty,
        "md5": md5,
        "comment": comment,
        "mode": mode,
        "stars": stars,
    }


def parse_osdb(filename, name):

    with open(filename, "rb") as f:
        data = f.read()

    r = Reader(data)

    # ---------------------------------------------------------
    # Header
    # ---------------------------------------------------------

    version = r.string()

    if version != "o!dm6":
        raise ValueError(
            f"Expected o!dm6, got {version!r}"
        )

    creation_date = r.double()
    editor = r.string()
    collection_count = r.int32()

    print(f"Version: {version}")
    print(f"Creation date: {creation_date}")
    print(f"Editor: {editor}")
    print(f"Collections: {collection_count}")

    collections = {}

    # ---------------------------------------------------------
    # Collections
    # ---------------------------------------------------------

    for collection_index in range(collection_count):

        collection_name = r.string()
        online_id = r.int32()
        beatmap_count = r.int32()

        print(f"\nCollection {collection_index}")
        print(f"  Name: {collection_name}")
        print(f"  Online ID: {online_id}")
        print(f"  Beatmaps: {beatmap_count}")

        beatmap_ids = []
        beatmapset_ids = []

        for beatmap_index in range(ACTUAL_BEATMAP_COUNT):

            record_offset = r.pos

            try:
                beatmap_id = r.int32()

                # TODO: Record 0 is different in all our .osdb collections???
                if beatmap_index == 0:
                    beatmapset_id = None
                else:
                    beatmapset_id = r.int32()

                artist = r.string()
                title = r.string()
                difficulty = r.string()
                md5 = r.string()
                comment = r.string()
                mode = r.byte()
                stars = r.double()

            except Exception as e:
                print("\n========== PARSE ERROR ==========")
                print(f"Beatmap index: {beatmap_index}")
                print(f"Offset: {record_offset:#x}")
                print(f"Error: {e}")
                print(
                    "Next bytes:",
                    r.data[record_offset:record_offset + 64].hex(" ")
                )
                raise

            beatmap_ids.append(beatmap_id)

            if beatmapset_id is not None:
                beatmapset_ids.append(beatmapset_id)

        # -----------------------------------------------------
        # Save IDs to TXT files
        # -----------------------------------------------------

        beatmap_id_filename = f"./outputs/{collection_name}_beatmap_ids.txt"
        beatmapset_id_filename = f"./outputs/{collection_name}_beatmapset_ids.txt"

        with open(beatmap_id_filename, "w", encoding="utf-8") as f:
            for beatmap_id in beatmap_ids:
                f.write(f"{beatmap_id}\n")

        with open(beatmapset_id_filename, "w", encoding="utf-8") as f:
            for beatmapset_id in beatmapset_ids:
                f.write(f"{beatmapset_id}\n")

        print(f"\nSaved beatmap IDs to: {beatmap_id_filename}")
        print(f"Saved beatmapset IDs to: {beatmapset_id_filename}")

        print("\n========== AFTER BEATMAPS ==========")
        print(f"Offset: {r.pos:#x}")

        md5_count = r.int32()
        print(f"MD5 count: {md5_count}")

        md5_hashes = []
        for _ in range(md5_count):
            md5_hashes.append(r.string())

        footer = r.string()
        print(f"Footer: {footer!r}")

        print(f"Final offset: {r.pos:#x}")
        print(f"File size: {len(data):#x}")

        collections[collection_name] = {
            "beatmap_ids": beatmap_ids,
            "beatmapset_ids": beatmapset_ids,
        }


    return collections



if __name__ == "__main__":

    collections = parse_osdb(FILENAME, NAME)

    for collection_name, collection_data in collections.items():

        beatmap_ids = collection_data["beatmap_ids"]
        beatmapset_ids = collection_data["beatmapset_ids"]

        print(
            f"\n{collection_name}: "
            f"{len(beatmap_ids):,} beatmap IDs"
        )

        print(
            f"{collection_name}: "
            f"{len(beatmapset_ids):,} beatmapset IDs"
        )