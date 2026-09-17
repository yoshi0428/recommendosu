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


def hex_dump(data, start_offset=0, bytes_per_line=16):
    """
    Create a traditional hex dump:

    00000123  01 02 03 ... 0f  ................
    """

    lines = []

    for offset in range(0, len(data), bytes_per_line):
        chunk = data[offset:offset + bytes_per_line]

        hex_part = " ".join(f"{b:02x}" for b in chunk)

        # Pad hex column so ASCII lines line up
        hex_part = f"{hex_part:<47}"

        ascii_part = "".join(
            chr(b) if 32 <= b <= 126 else "."
            for b in chunk
        )

        lines.append(
            f"{start_offset + offset:08x}  "
            f"{hex_part}  "
            f"{ascii_part}"
        )

    return "\n".join(lines)


def parse_osdb(filename):

    with open(filename, "rb") as f:
        data = f.read()

    r = Reader(data)

    # -------------------------
    # Header
    # -------------------------

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

    # -------------------------
    # Collection
    # -------------------------

    for collection_index in range(collection_count):

        collection_name = r.string()
        online_id = r.int32()
        beatmap_count = r.int32()

        print(f"\nCollection: {collection_name}")
        print(f"Online ID: {online_id}")
        print(f"Beatmaps: {beatmap_count}")

        # This is where the first beatmap's data begins.
        start_offset = r.pos

        print(f"\nFirst beatmap data starts at:")
        print(f"Decimal: {start_offset}")
        print(f"Hex:     0x{start_offset:x}")

        # --------------------------------
        # Dump first 1000 bytes
        # --------------------------------

        dump_size = 1000

        chunk = data[start_offset:start_offset + dump_size]

        dump = hex_dump(
            chunk,
            start_offset=start_offset
        )

        # Print to console
        print("\n=== HEX DUMP ===")
        print(dump)

        # Save to file
        with open("./outputs/osdb_hex_dump.txt", "w") as f:
            f.write(
                f"File: {filename}\n"
                f"Version: {version}\n"
                f"Collection: {collection_name}\n"
                f"Beatmaps: {beatmap_count}\n"
                f"First beatmap offset: "
                f"{start_offset} (0x{start_offset:x})\n\n"
            )

            f.write(dump)

        print(
            "\nHex dump saved to: "
            "osdb_hex_dump.txt"
        )

        # Stop here.
        # We don't want to attempt parsing the beatmap yet.
        break


if __name__ == "__main__":
    parse_osdb("inputs/NM2.osdb")