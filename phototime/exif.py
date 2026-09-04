"""Minimal EXIF reader for JPEG files.

This only extracts the handful of tags phototime cares about (the
DateTime family). It is not a general-purpose EXIF library: no writing,
no thumbnails, no GPS, no maker notes. JPEG only for now - see README
for the plan on other formats.
"""

import struct

_JPEG_SOI = b"\xff\xd8"
_APP1_MARKER = 0xFFE1
_START_OF_SCAN = 0xFFDA
_EXIF_HEADER = b"Exif\x00\x00"

TAG_DATETIME = 0x0132
TAG_EXIF_IFD_POINTER = 0x8769
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004

_TYPE_ASCII = 2
_TYPE_SHORT = 3
_TYPE_LONG = 4

# EXIF is almost always in the first segment or two of a JPEG, well
# before any scan data, so we never need to read the whole file.
_READ_LIMIT = 2 * 1024 * 1024


class ExifError(Exception):
    pass


def _find_app1_segment(data):
    if data[:2] != _JPEG_SOI:
        raise ExifError("not a JPEG file (missing SOI marker)")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ExifError("malformed JPEG: expected marker at offset %d" % pos)
        marker = (data[pos] << 8) | data[pos + 1]
        # Markers with no payload: SOI/EOI and the RST0-RST7 restart markers.
        if marker in (0xFFD8, 0xFFD9) or 0xFFD0 <= marker <= 0xFFD7:
            pos += 2
            continue
        if marker == _START_OF_SCAN:
            break  # entropy-coded image data follows; no more segments
        length = struct.unpack_from(">H", data, pos + 2)[0]
        if marker == _APP1_MARKER:
            segment = data[pos + 4: pos + 2 + length]
            if segment.startswith(_EXIF_HEADER):
                return segment[len(_EXIF_HEADER):]
        pos += 2 + length
    return None


def _read_ifd(tiff, byte_order, offset):
    count = struct.unpack_from(byte_order + "H", tiff, offset)[0]
    entries = {}
    entry_offset = offset + 2
    for _ in range(count):
        tag, typ, num = struct.unpack_from(byte_order + "HHI", tiff, entry_offset)
        value_bytes = tiff[entry_offset + 8: entry_offset + 12]
        if typ == _TYPE_ASCII:
            if num <= 4:
                raw = value_bytes[:num]
            else:
                value_offset = struct.unpack_from(byte_order + "I", value_bytes)[0]
                raw = tiff[value_offset: value_offset + num]
            entries[tag] = raw.rstrip(b"\x00").decode("ascii", errors="replace")
        elif typ == _TYPE_SHORT:
            entries[tag] = struct.unpack_from(byte_order + "H", value_bytes)[0]
        elif typ == _TYPE_LONG:
            entries[tag] = struct.unpack_from(byte_order + "I", value_bytes)[0]
        entry_offset += 12
    next_ifd = struct.unpack_from(byte_order + "I", tiff, entry_offset)[0]
    return entries, next_ifd


def read_tags(path):
    """Return a dict of {tag: str_value} for the tags we know about.

    Returns an empty dict if the file has no EXIF data. Raises ExifError
    if the file isn't a JPEG or its EXIF block looks corrupt.
    """
    with open(path, "rb") as f:
        data = f.read(_READ_LIMIT)
    tiff = _find_app1_segment(data)
    if tiff is None:
        return {}
    if tiff[:2] == b"II":
        byte_order = "<"
    elif tiff[:2] == b"MM":
        byte_order = ">"
    else:
        raise ExifError("bad TIFF byte-order marker in EXIF block")

    ifd0_offset = struct.unpack_from(byte_order + "I", tiff, 4)[0]
    ifd0, _ = _read_ifd(tiff, byte_order, ifd0_offset)

    tags = {}
    if TAG_DATETIME in ifd0:
        tags[TAG_DATETIME] = ifd0[TAG_DATETIME]
    if TAG_EXIF_IFD_POINTER in ifd0:
        exif_ifd, _ = _read_ifd(tiff, byte_order, ifd0[TAG_EXIF_IFD_POINTER])
        for tag in (TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED):
            if tag in exif_ifd:
                tags[tag] = exif_ifd[tag]
    return tags
