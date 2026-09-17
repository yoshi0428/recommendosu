import struct


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        if self.pos + n > len(self.data):
            raise EOFError(
                f"Unexpected EOF at offset {self.pos}"
            )

        start = self.pos
        result = self.data[self.pos:self.pos + n]
        self.pos += n

        print(
            f"READ {n:3} bytes "
            f"@ 0x{start:08x}: "
            f"{result.hex(' ')}"
        )

        return result

    def byte(self):
        return self.read(1)[0]

    def int32(self):
        return struct.unpack("<i", self.read(4))[0]

    def double(self):
        return struct.unpack("<d", self.read(8))[0]

    def string(self):
        start = self.pos

        length = self.byte()

        print(
            f"STRING @ 0x{start:08x}: "
            f"length={length}"
        )

        if length == 0:
            return ""

        raw = self.read(length)

        print(
            f"  data: {raw.hex(' ')}"
        )

        try:
            value = raw.decode("utf-8")
            print(f"  text: {value!r}")
            return value
        except UnicodeDecodeError as e:
            print(
                f"  !!! UTF-8 DECODE FAILED !!!"
            )
            print(
                f"  raw: {raw.hex(' ')}"
            )
            raise


def parse_osdb(filename):

    with open(filename, "rb") as f:
        data = f.read()

    print(f"File size: {len(data)} bytes")

    r = Reader(data)

    # =========================
    # HEADER
    # =========================

    print("\n========== HEADER ==========")

    version = r.string()

    print(f"Version: {version}")

    if version != "o!dm6":
        raise ValueError(
            f"Expected o!dm6, got {version!r}"
        )

    creation_date = r.double()
    editor = r.string()
    collection_count = r.int32()

    print(f"Creation date: {creation_date}")
    print(f"Editor: {editor}")
    print(f"Collections: {collection_count}")

    # =========================
    # COLLECTION
    # =========================

    for collection_index in range(collection_count):

        print(
            f"\n========== COLLECTION "
            f"{collection_index} =========="
        )

        collection_name = r.string()
        online_id = r.int32()
        beatmap_count = r.int32()

        print(f"Collection: {collection_name}")
        print(f"Online ID: {online_id}")
        print(f"Beatmaps: {beatmap_count}")


        # =========================
        # FIRST BEATMAP
        # =========================
        print("\n========== FIRST BEATMAP ==========")

        beatmap_id = r.int32()
        print(f"Beatmap ID: {beatmap_id}")

        artist = r.string()
        print(f"Artist: {artist!r}")

        title = r.string()
        print(f"Title: {title!r}")

        difficulty = r.string()
        print(f"Difficulty: {difficulty!r}")

        md5 = r.string()
        print(f"MD5: {md5!r}")

        print("\n--- Next bytes after MD5 ---")

        print(
            f"Current offset: {r.pos:#x}"
        )

        print(
            "Next 20 bytes:",
            r.data[r.pos:r.pos + 20].hex(" ")
        )

        # Read 3 bytes temporarily
        unknown = r.read(3)

        print(
            f"Unknown 3 bytes: {unknown.hex(' ')}"
        )

        stars = r.double()

        print(f"Stars: {stars}")

        next_id = r.int32()

        print(f"Next beatmap ID: {next_id}")

        break


if __name__ == "__main__":
    parse_osdb("inputs/NM2.osdb")