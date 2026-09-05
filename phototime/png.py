"""Minimal PNG metadata reader.

PNGs can carry the same EXIF DateTime tags as JPEGs, tucked into an
"eXIf" chunk holding a raw TIFF blob (no APP1 wrapper, unlike JPEG).
They can also carry a "Creation Time" tEXt/zTXt chunk, one of the
handful of keywords the PNG spec actually standardizes. We read both
and leave everything else (palettes, gamma, ICC profiles, ...) alone.
"""

import struct
import zlib

from . import exif

SIGNATURE = b"\x89PNG\r\n\x1a\n"

TAG_CREATION_TIME = "png:CreationTime"

# Chunks live before the pixel data, which can be arbitrarily large, so we
# still cap how much of the file we're willing to read - same idea as the
# JPEG reader's _READ_LIMIT.
_READ_LIMIT = 4 * 1024 * 1024


class PngError(Exception):
    pass


def _iter_chunks(data):
    pos = len(SIGNATURE)
    while pos + 8 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        chunk_type = data[pos + 4: pos + 8]
        chunk_data = data[pos + 8: pos + 8 + length]
        if len(chunk_data) < length:
            return  # truncated by _READ_LIMIT before the chunk fully landed
        yield chunk_type, chunk_data
        if chunk_type == b"IEND":
            return
        pos += 12 + length  # length field + type + data + trailing CRC


def _decode_text_chunk(chunk_data):
    keyword, _, text = chunk_data.partition(b"\x00")
    return keyword.decode("latin-1"), text


def _decode_ztxt_chunk(chunk_data):
    keyword, _, rest = chunk_data.partition(b"\x00")
    if len(rest) < 1 or rest[0] != 0:
        return keyword.decode("latin-1"), b""  # unknown compression method
    try:
        text = zlib.decompress(rest[1:])
    except zlib.error:
        text = b""
    return keyword.decode("latin-1"), text


def read_tags(path):
    """Return a dict combining EXIF-style tags and the PNG creation-time tag.

    EXIF tags (from an eXIf chunk) use the same numeric keys as exif.py's
    TAG_* constants, so callers can treat a PNG's eXIf data exactly like a
    JPEG's. Creation Time (from a tEXt/zTXt chunk) uses the string key
    TAG_CREATION_TIME instead, since it isn't part of EXIF at all.
    """
    with open(path, "rb") as f:
        data = f.read(_READ_LIMIT)
    if data[:8] != SIGNATURE:
        raise PngError("not a PNG file (missing signature)")

    tags = {}
    for chunk_type, chunk_data in _iter_chunks(data):
        if chunk_type == b"eXIf":
            try:
                tags.update(exif.parse_tiff(chunk_data))
            except (exif.ExifError, struct.error):
                pass
        elif chunk_type in (b"tEXt", b"zTXt") and TAG_CREATION_TIME not in tags:
            if chunk_type == b"tEXt":
                keyword, text = _decode_text_chunk(chunk_data)
            else:
                keyword, text = _decode_ztxt_chunk(chunk_data)
            if keyword == "Creation Time" and text:
                tags[TAG_CREATION_TIME] = text.decode("ascii", errors="replace")
    return tags
