"""Store file bytes, compressed bytes, UTF-8, JSON, and YAML in native Strings."""

import gzip
import hashlib
import json
from pathlib import Path

from common import console, key, text, timed
from valkey_client import ValkeyClientManager


ASSETS = Path(__file__).with_name("assets")


def sample_values():
    logo = (ASSETS / "valkey-horizontal.svg").read_bytes()
    return {
        "logo-svg": logo,
        "logo-svg-gzip": gzip.compress(logo, mtime=0),
        "opaque": b"\x00\x01\xff\x80A",
        "utf8": "café 🚀".encode("utf-8"),
        "json": json.dumps({"sku": "speaker", "stock": 7}).encode("utf-8"),
        "yaml": b"sku: speaker\nstock: 7\n",
    }


def demonstrate(client):
    values = sample_values()
    for label, payload in values.items():
        name = key("string", label)
        reply, set_ms = timed(client.set, name, payload)
        restored, get_ms = timed(client.get, name)
        length, length_ms = timed(client.strlen, name)
        kind, type_ms = timed(client.type, name)
        encoding, encoding_ms = timed(client.object_encoding, name)
        assert text(reply) == "OK" and restored == payload and length == len(payload)
        assert text(kind) == "string"
        console.print(f"SET {name}: OK; {set_ms:.3f} ms")
        console.print(
            f"GET: {len(restored)} bytes; {get_ms:.3f} ms; "
            f"SHA-256: {hashlib.sha256(restored).hexdigest()}"
        )
        console.print(
            f"STRLEN: {length}; {length_ms:.3f} ms; "
            f"TYPE: {text(kind)}; {type_ms:.3f} ms; "
            f"OBJECT ENCODING: {text(encoding)}; {encoding_ms:.3f} ms"
        )
        console.print(f"First 12 bytes in hex: {restored[:12].hex(' ')}")

    compressed, get_ms = timed(client.get, key("string", "logo-svg-gzip"))
    assert gzip.decompress(compressed) == values["logo-svg"]
    console.print(f"Compressed logo GET: {get_ms:.3f} ms; Python decompression restores the SVG bytes.")
    for start, end in [(0, 4), (3, 3), (6, 9)]:
        part, range_ms = timed(client.getrange, key("string", "utf8"), start, end)
        assert part == values["utf8"][start:end + 1]
        console.print(f"GETRANGE utf8 {start} {end}: hex={part.hex(' ')}; {range_ms:.3f} ms")
    console.print(
        "café 🚀 has 6 Unicode characters and 10 UTF-8 bytes. Ranges use inclusive byte offsets. "
        "The c3 byte alone is an incomplete UTF-8 character."
    )
    console.print(
        "Valkey stores these bytes as Strings. Python chooses how to decode, parse, or decompress them. "
        "These keys remain available for inspection in Valkey Admin."
    )


def main():
    with ValkeyClientManager() as client:
        demonstrate(client)


if __name__ == "__main__":
    main()
