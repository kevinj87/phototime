"""Build synthetic JPEG/PNG/HEIC bytes for tests, in memory.

No binary fixture files are checked in - every image is assembled by hand
from the same struct-level layouts phototime's readers expect, so a broken
parser and a broken fixture can't both happen to agree with each other.
"""

import struct

from phototime import exif, png


def _pack_ascii_ifd(tags, offset, extra_entries):
    """Pack one TIFF IFD of ASCII string tags plus arbitrary inline entries.

    Only used for ASCII values long enough (5+ bytes with the null
    terminator) that they're stored out-of-line via an offset, matching
    every EXIF datetime tag. extra_entries are (tag, type, count, value)
    tuples whose value fits inline in the 4-byte field (e.g. a LONG).
    Returns (ifd_bytes, values_bytes); `offset` is where ifd_bytes will
    sit in the final buffer, used to compute the values' offsets.
    """
    entries = list(tags.items())
    count = len(entries) + len(extra_entries)
    header_size = 2 + count * 12 + 4
    values_start = offset + header_size

    body = struct.pack("<H", count)
    values = b""
    value_pos = values_start
    for tag, value in entries:
        raw = value.encode("ascii") + b"\x00"
        body += struct.pack("<HHI", tag, exif._TYPE_ASCII, len(raw))
        body += struct.pack("<I", value_pos)
        values += raw
        value_pos += len(raw)
    for tag, typ, cnt, val in extra_entries:
        body += struct.pack("<HHI", tag, typ, cnt)
        body += struct.pack("<I", val)
    body += struct.pack("<I", 0)  # next IFD offset: none
    return body, values


def build_tiff(ifd0_tags=None, exif_tags=None):
    """Build a raw little-endian TIFF blob (the part shared by JPEG APP1,
    PNG eXIf, and HEIC Exif items).

    ifd0_tags go straight into IFD0. exif_tags, if given, go into an Exif
    sub-IFD linked from IFD0 via the ExifIFDPointer tag, the way a real
    camera splits DateTime (IFD0) from DateTimeOriginal/Digitized (Exif IFD).
    """
    ifd0_tags = dict(ifd0_tags or {})
    ifd0_offset = 8
    extra = [[exif.TAG_EXIF_IFD_POINTER, exif._TYPE_LONG, 1, 0]] if exif_tags else []

    ifd0_body, ifd0_values = _pack_ascii_ifd(ifd0_tags, ifd0_offset, extra)
    exif_ifd_offset = ifd0_offset + len(ifd0_body) + len(ifd0_values)

    exif_body = exif_values = b""
    if exif_tags:
        extra[0][3] = exif_ifd_offset
        ifd0_body, ifd0_values = _pack_ascii_ifd(ifd0_tags, ifd0_offset, extra)
        exif_body, exif_values = _pack_ascii_ifd(exif_tags, exif_ifd_offset, [])

    header = b"II" + struct.pack("<HI", 42, ifd0_offset)
    return header + ifd0_body + ifd0_values + exif_body + exif_values


def build_jpeg_with_exif(ifd0_tags=None, exif_tags=None):
    """A minimal JPEG: SOI, one APP1/Exif segment, EOI."""
    tiff = build_tiff(ifd0_tags, exif_tags)
    segment = b"Exif\x00\x00" + tiff
    app1 = struct.pack(">HH", 0xFFE1, len(segment) + 2) + segment
    return b"\xff\xd8" + app1 + b"\xff\xd9"


def _pack_png_chunk(chunk_type, data):
    # The CRC is never checked by png.py's reader, so a zero placeholder
    # is fine here - it only needs to hold four bytes of the right length.
    return struct.pack(">I", len(data)) + chunk_type + data + b"\x00\x00\x00\x00"


def build_png(exif_tiff=None, creation_time=None, chunks=()):
    """A minimal PNG: IHDR, optional eXIf/tEXt, then whatever extra chunks
    the caller wants, then IEND."""
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    out = png.SIGNATURE + _pack_png_chunk(b"IHDR", ihdr)
    if exif_tiff is not None:
        out += _pack_png_chunk(b"eXIf", exif_tiff)
    if creation_time is not None:
        out += _pack_png_chunk(b"tEXt", b"Creation Time\x00" + creation_time.encode("ascii"))
    for chunk_type, data in chunks:
        out += _pack_png_chunk(chunk_type, data)
    out += _pack_png_chunk(b"IEND", b"")
    return out


def _pack_box(box_type, content):
    return struct.pack(">I", 8 + len(content)) + box_type + content


def build_ftyp(major_brand=b"heic"):
    return _pack_box(b"ftyp", major_brand + b"\x00\x00\x00\x00")


def _pack_infe(item_id, item_type):
    body = b"\x02\x00\x00\x00"  # infe version 2, flags 0
    body += struct.pack(">H", item_id)
    body += b"\x00\x00"  # item_protection_index
    body += item_type
    return _pack_box(b"infe", body)


def build_iinf(items):
    """items: list of (item_id, item_type_bytes)."""
    content = b"\x00\x00\x00\x00"  # iinf version 0, flags 0
    content += struct.pack(">H", len(items))
    for item_id, item_type in items:
        content += _pack_infe(item_id, item_type)
    return _pack_box(b"iinf", content)


def build_iloc(locations):
    """locations: list of (item_id, offset, length), single extent each,
    construction_method 0 (plain file offset), matching real encoders."""
    content = b"\x00\x00\x00\x00"  # iloc version 0, flags 0
    content += bytes([0x44])  # offset_size=4, length_size=4
    content += bytes([0x00])  # base_offset_size=0, reserved=0
    content += struct.pack(">H", len(locations))
    for item_id, offset, length in locations:
        content += struct.pack(">H", item_id)
        content += b"\x00\x00"  # data_reference_index
        content += struct.pack(">H", 1)  # extent_count
        content += struct.pack(">II", offset, length)
    return _pack_box(b"iloc", content)


def build_meta(iinf_box, iloc_box):
    content = b"\x00\x00\x00\x00" + iinf_box + iloc_box  # meta version 0, flags 0
    return _pack_box(b"meta", content)


def build_heic_with_exif(ifd0_tags=None, exif_tags=None, item_id=1):
    """A minimal HEIC: ftyp, meta (iinf + iloc pointing at one Exif item),
    then the Exif item's bytes."""
    tiff = build_tiff(ifd0_tags, exif_tags)
    exif_item = struct.pack(">I", 0) + tiff  # offset-to-TIFF header of 0

    ftyp = build_ftyp()
    iinf = build_iinf([(item_id, b"Exif")])
    # The extent offset depends on the size of everything before it, which
    # depends on iloc itself - build once with a placeholder, then patch,
    # relying on the fact that patching the offset value doesn't change size.
    meta = build_meta(iinf, build_iloc([(item_id, 0, len(exif_item))]))
    exif_offset = len(ftyp) + len(meta)
    meta = build_meta(iinf, build_iloc([(item_id, exif_offset, len(exif_item))]))

    return ftyp + meta + exif_item
