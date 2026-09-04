"""Reconcile EXIF, filename, and mtime dates into one best guess."""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta

from . import exif

_EXIF_DATETIME_RE = re.compile(r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")

# Covers IMG_20230405_120000.jpg, 20230405-120000.jpg, Screenshot_20230405-120000.png
_FILENAME_DATETIME_RE = re.compile(
    r"(?<!\d)(\d{4})(\d{2})(\d{2})[-_ ]?(\d{2})(\d{2})(\d{2})(?!\d)"
)
# Covers date-only names like IMG-20230405-WA0002.jpg
_FILENAME_DATE_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")

MISMATCH_THRESHOLD = timedelta(days=1)

_EXIF_SOURCE_LABELS = {
    exif.TAG_DATETIME_ORIGINAL: "exif:DateTimeOriginal",
    exif.TAG_DATETIME_DIGITIZED: "exif:DateTimeDigitized",
    exif.TAG_DATETIME: "exif:DateTime",
}

# Preference order when more than one EXIF date tag is present.
_EXIF_PRIORITY = (
    exif.TAG_DATETIME_ORIGINAL,
    exif.TAG_DATETIME_DIGITIZED,
    exif.TAG_DATETIME,
)


def _parse_exif_datetime(value):
    if not _EXIF_DATETIME_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _plausible(year, month, day, hour, minute, second):
    return (
        1990 <= year <= datetime.now().year + 1
        and 1 <= month <= 12
        and 1 <= day <= 31
        and hour <= 23
        and minute <= 59
        and second <= 59
    )


def _from_filename(name):
    match = _FILENAME_DATETIME_RE.search(name)
    if match:
        year, month, day, hour, minute, second = (int(g) for g in match.groups())
        if _plausible(year, month, day, hour, minute, second):
            try:
                return datetime(year, month, day, hour, minute, second)
            except ValueError:
                pass
    match = _FILENAME_DATE_RE.search(name)
    if match:
        year, month, day = (int(g) for g in match.groups())
        if _plausible(year, month, day, 0, 0, 0):
            try:
                return datetime(year, month, day)
            except ValueError:
                pass
    return None


def gather_sources(path):
    """Return an ordered list of (label, datetime) candidates, best first."""
    sources = []
    try:
        tags = exif.read_tags(path)
    except exif.ExifError:
        tags = {}
    for tag in _EXIF_PRIORITY:
        if tag in tags:
            parsed = _parse_exif_datetime(tags[tag])
            if parsed is not None:
                sources.append((_EXIF_SOURCE_LABELS[tag], parsed))
    filename_dt = _from_filename(os.path.basename(path))
    if filename_dt is not None:
        sources.append(("filename", filename_dt))
    mtime = datetime.fromtimestamp(os.stat(path).st_mtime)
    sources.append(("mtime", mtime))
    return sources


def find_mismatches(sources):
    """Pairs of sources whose dates disagree by more than the threshold."""
    mismatches = []
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            label_a, dt_a = sources[i]
            label_b, dt_b = sources[j]
            diff = abs(dt_a - dt_b)
            if diff > MISMATCH_THRESHOLD:
                mismatches.append((label_a, label_b, diff))
    return mismatches


def report(path, verbose):
    sources = gather_sources(path)
    label, dt = sources[0]
    print(path)
    print(f"  taken:  {dt:%Y-%m-%d %H:%M:%S}  (source: {label})")
    if verbose:
        for other_label, other_dt in sources[1:]:
            print(f"  also:   {other_dt:%Y-%m-%d %H:%M:%S}  (source: {other_label})")
    for label_a, label_b, diff in find_mismatches(sources):
        print(f"  note:   {label_a} and {label_b} disagree by {diff}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="phototime",
        description="Find the most trustworthy capture date for a photo.",
    )
    parser.add_argument("paths", nargs="+", help="image files to inspect")
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="show every date source found, not just the best guess",
    )
    args = parser.parse_args(argv)

    exit_code = 0
    for path in args.paths:
        if not os.path.isfile(path):
            print(f"{path}: no such file", file=sys.stderr)
            exit_code = 1
            continue
        try:
            report(path, args.verbose)
        except OSError as e:
            print(f"{path}: {e}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
