"""Minimal EXIF reader for JPEG files, and the shared TIFF parser PNG and
HEIC readers build on for their own EXIF blocks.

This only extracts the handful of tags phototime cares about: the
DateTime family and GPS latitude/longitude/altitude. Not a general-
purpose EXIF library: no writing, no thumbnails, no camera model, no
maker notes.
"""

import struct

_JPEG_SOI = b"\xff\xd8"
_APP1_MARKER = 0xFFE1
_START_OF_SCAN = 0xFFDA
_EXIF_HEADER = b"Exif\x00\x00"

TAG_DATETIME = 0x0132
TAG_EXIF_IFD_POINTER = 0x8769
TAG_GPS_IFD_POINTER = 0x8825
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004

# Key under which parse_tiff stores the decoded GPS dict, if present. A
# string rather than a numeric tag, same trick png.py uses for
# TAG_CREATION_TIME, so it can share the same tags dict without colliding
# with any real EXIF tag number.
TAG_GPS = "gps"

# Tags within the GPS sub-IFD (pointed to by TAG_GPS_IFD_POINTER), not
# top-level EXIF tags, so they're kept private.
_GPS_TAG_LATITUDE_REF = 1
_GPS_TAG_LATITUDE = 2
_GPS_TAG_LONGITUDE_REF = 3
_GPS_TAG_LONGITUDE = 4
_GPS_TAG_ALTITUDE_REF = 5
_GPS_TAG_ALTITUDE = 6

_TYPE_BYTE = 1
_TYPE_ASCII = 2
_TYPE_SHORT = 3
_TYPE_LONG = 4
_TYPE_RATIONAL = 5

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
        elif typ == _TYPE_BYTE:
            entries[tag] = value_bytes[0]
        elif typ == _TYPE_RATIONAL:
            # Always stored out-of-line: even a single rational is 8 bytes,
            # too big for the 4-byte inline value field.
            value_offset = struct.unpack_from(byte_order + "I", value_bytes)[0]
            rationals = [
                struct.unpack_from(byte_order + "II", tiff, value_offset + i * 8)
                for i in range(num)
            ]
            entries[tag] = rationals[0] if num == 1 else rationals
        entry_offset += 12
    next_ifd = struct.unpack_from(byte_order + "I", tiff, entry_offset)[0]
    return entries, next_ifd


def _rational_to_float(rational):
    numerator, denominator = rational
    return numerator / denominator if denominator else 0.0


def _dms_to_degrees(dms):
    degrees, minutes, seconds = (_rational_to_float(v) for v in dms)
    return degrees + minutes / 60 + seconds / 3600


def _parse_gps_ifd(gps_ifd):
    """Turn a raw GPS sub-IFD into {"latitude", "longitude", "altitude"}
    (signed decimal degrees and meters), or None if it lacks a position."""
    if _GPS_TAG_LATITUDE not in gps_ifd or _GPS_TAG_LONGITUDE not in gps_ifd:
        return None
    latitude = _dms_to_degrees(gps_ifd[_GPS_TAG_LATITUDE])
    if gps_ifd.get(_GPS_TAG_LATITUDE_REF) == "S":
        latitude = -latitude
    longitude = _dms_to_degrees(gps_ifd[_GPS_TAG_LONGITUDE])
    if gps_ifd.get(_GPS_TAG_LONGITUDE_REF) == "W":
        longitude = -longitude
    altitude = None
    if _GPS_TAG_ALTITUDE in gps_ifd:
        altitude = _rational_to_float(gps_ifd[_GPS_TAG_ALTITUDE])
        if gps_ifd.get(_GPS_TAG_ALTITUDE_REF) == 1:  # 1 == below sea level
            altitude = -altitude
    return {"latitude": latitude, "longitude": longitude, "altitude": altitude}


def parse_tiff(tiff):
    """Parse a raw TIFF byte string (byte-order marker onward) into tags.

    This is the part of EXIF parsing that's format-agnostic: a JPEG APP1
    segment and a PNG eXIf chunk both wrap this same TIFF structure, just
    with different container framing around it.
    """
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
    if TAG_GPS_IFD_POINTER in ifd0:
        gps_ifd, _ = _read_ifd(tiff, byte_order, ifd0[TAG_GPS_IFD_POINTER])
        gps = _parse_gps_ifd(gps_ifd)
        if gps is not None:
            tags[TAG_GPS] = gps
    return tags


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
    return parse_tiff(tiff)
