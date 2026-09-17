with open("inputs/NM2.osdb", "rb") as f:
    data = f.read()

print("File size:", len(data))
print("File end:", hex(len(data)))

start = max(0, len(data) - 256)

for offset in range(start, len(data), 16):
    chunk = data[offset:offset + 16]

    hex_part = " ".join(f"{b:02x}" for b in chunk)
    ascii_part = "".join(
        chr(b) if 32 <= b < 127 else "."
        for b in chunk
    )

    print(
        f"{offset:08x}  "
        f"{hex_part:<47}  "
        f"{ascii_part}"
    )