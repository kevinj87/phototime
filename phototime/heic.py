"""Minimal HEIC/HEIF metadata reader.

HEIC files are ISOBMFF containers (the same box structure as MP4), not a
byte stream you can scan linearly like a JPEG or PNG. EXIF data lives as a
numbered "item" inside the top-level `meta` box: `iinf` names each item's
type, `iloc` says where its bytes sit in the file, and the item with type
`Exif` holds the same TIFF blob a JPEG APP1 segment or PNG eXIf chunk
carries, just with a 4-byte offset header in front of it instead of the
"Exif\\x00\\x00" marker.
"""

import struct

from . import exif

_HEIC_BRANDS = {
    b"heic", b"heix", b"heim", b"heis",
    b"hevc", b"hevx", b"hevm", b"hevs",
    b"mif1", b"msf1", b"avif", b"avis",
}

# The `meta` box and the Exif item it points to are always near the start of
# the file - mdat (the actual image data) comes after and can be huge, so we
# never need to read the whole thing.
_READ_LIMIT = 8 * 1024 * 1024


class HeicError(Exception):
    pass


def _iter_boxes(data, start, end):
    pos = start
    while pos + 8 <= end:
        size = struct.unpack_from(">I", data, pos)[0]
        box_type = data[pos + 4: pos + 8]
        header_size = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header_size = 16
        elif size == 0:
            size = end - pos
        if size < header_size or pos + size > end:
            return
        yield box_type, pos + header_size, pos + size
        pos += size


def _find_box(data, start, end, target):
    for box_type, box_start, box_end in _iter_boxes(data, start, end):
        if box_type == target:
            return box_start, box_end
    return None


def _check_brand(data):
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise HeicError("not an ISOBMFF file (missing ftyp box)")
    ftyp_size = struct.unpack_from(">I", data, 0)[0]
    major_brand = data[8:12]
    compatible = data[16:min(ftyp_size, len(data))]
    brands = {major_brand}
    brands.update(compatible[i:i + 4] for i in range(0, len(compatible) - 3, 4))
    if not (brands & _HEIC_BRANDS):
        raise HeicError("ftyp box does not advertise a HEIC/HEIF brand")


def _parse_iinf(data, start, end):
    """Return {item_id: item_type} for every item the `iinf` box describes."""
    version = data[start]
    pos = start + 4  # skip version(1) + flags(3)
    if version == 0:
        item_count = struct.unpack_from(">H", data, pos)[0]
        pos += 2
    else:
        item_count = struct.unpack_from(">I", data, pos)[0]
        pos += 4
    items = {}
    for _ in range(item_count):
        if pos + 8 > end:
            break
        infe_size = struct.unpack_from(">I", data, pos)[0]
        infe_type = data[pos + 4: pos + 8]
        if infe_type != b"infe" or infe_size < 8:
            break
        infe_version = data[pos + 8]
        body = pos + 12  # skip size(4) + type(4) + version(1) + flags(3)
        # Only version 2+ `infe` boxes carry a plain fourcc item_type - older
        # versions used a different, item-count-limited encoding we skip.
        if infe_version >= 2:
            if infe_version == 2:
                item_id = struct.unpack_from(">H", data, body)[0]
                body += 2
            else:
                item_id = struct.unpack_from(">I", data, body)[0]
                body += 4
            body += 2  # item_protection_index
            items[item_id] = data[body: body + 4]
        pos += infe_size
    return items


def _parse_iloc(data, start, end):
    """Return {item_id: (offset, length)} for the first extent of each item.

    Only construction_method 0 (plain file offset) is handled, which is
    what every camera and phone HEIC encoder in practice uses.
    """
    version = data[start]
    pos = start + 4  # skip version(1) + flags(3)
    offset_size, length_size = data[pos] >> 4, data[pos] & 0xF
    base_offset_size = data[pos + 1] >> 4
    index_size = (data[pos + 1] & 0xF) if version in (1, 2) else 0
    pos += 2
    if version < 2:
        item_count = struct.unpack_from(">H", data, pos)[0]
        pos += 2
    else:
        item_count = struct.unpack_from(">I", data, pos)[0]
        pos += 4

    def read_uint(size):
        nonlocal pos
        if size == 0:
            return 0
        value = int.from_bytes(data[pos:pos + size], "big")
        pos += size
        return value

    items = {}
    for _ in range(item_count):
        if version < 2:
            item_id = struct.unpack_from(">H", data, pos)[0]
            pos += 2
        else:
            item_id = struct.unpack_from(">I", data, pos)[0]
            pos += 4
        construction_method = 0
        if version in (1, 2):
            construction_method = struct.unpack_from(">H", data, pos)[0] & 0xF
            pos += 2
        pos += 2  # data_reference_index
        base_offset = read_uint(base_offset_size)
        extent_count = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        first_extent = None
        for _ in range(extent_count):
            if version in (1, 2) and index_size:
                read_uint(index_size)
            extent_offset = read_uint(offset_size)
            extent_length = read_uint(length_size)
            if first_extent is None:
                first_extent = (extent_offset, extent_length)
        if first_extent is not None and construction_method == 0:
            items[item_id] = (base_offset + first_extent[0], first_extent[1])
    return items


def _read_exif_tags(data):
    meta = _find_box(data, 0, len(data), b"meta")
    if meta is None:
        return {}
    meta_start, meta_end = meta
    meta_start += 4  # meta is a full box: skip version(1) + flags(3)

    iinf = _find_box(data, meta_start, meta_end, b"iinf")
    iloc = _find_box(data, meta_start, meta_end, b"iloc")
    if iinf is None or iloc is None:
        return {}

    items_by_type = _parse_iinf(data, iinf[0], iinf[1])
    exif_item_id = next(
        (item_id for item_id, item_type in items_by_type.items() if item_type == b"Exif"),
        None,
    )
    if exif_item_id is None:
        return {}

    locations = _parse_iloc(data, iloc[0], iloc[1])
    if exif_item_id not in locations:
        return {}
    offset, length = locations[exif_item_id]

    # The Exif item's own payload starts with a 4-byte offset to the TIFF
    # header, which skips over an optional "Exif\x00\x00" prefix.
    item_data = data[offset: offset + length]
    if len(item_data) < 4:
        return {}
    tiff_offset = struct.unpack_from(">I", item_data, 0)[0]
    tiff = item_data[4 + tiff_offset:]
    try:
        return exif.parse_tiff(tiff)
    except exif.ExifError:
        return {}


def read_tags(path):
    """Return a dict of {tag: str_value} for the DateTime EXIF tags, if present.

    Returns an empty dict if the file has no Exif item. Raises HeicError if
    the file isn't a recognizable HEIC/HEIF container.
    """
    with open(path, "rb") as f:
        data = f.read(_READ_LIMIT)
    _check_brand(data)
    try:
        return _read_exif_tags(data)
    except (struct.error, IndexError):
        return {}
