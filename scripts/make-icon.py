"""Write electron/assets/icon.ico (one embedded 256px PNG) so the app builds without extra tooling."""
from pathlib import Path
import struct
import zlib

SIZE = 256


def pixel(x, y):
    t = (x + y) / (2 * SIZE)
    r, g, b = (2 + int(t * 77), 132 - int(t * 30), 199 + int(t * 20))  # sky blue to indigo
    inside = abs(x - SIZE / 2) < SIZE * 0.22 and abs(y - SIZE / 2) < SIZE * 0.3
    return (255, 255, 255, 255) if inside else (r, g, b, 255)


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(SIZE)) for y in range(SIZE))
png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))
ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22) + png
target = Path(__file__).resolve().parent.parent / "electron" / "assets" / "icon.ico"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(ico)
print(f"wrote {target} ({len(ico)} bytes)")
