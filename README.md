# phototime

When was a photo actually taken? It sounds like a solved problem until you
look at a folder pulled together from a phone backup, a WhatsApp export, and
an old hard drive. The file's modified time is usually just "when it was
copied here." Some files have EXIF data with a real capture date, some don't
(screenshots, WhatsApp forwards, anything that's been re-encoded), and some
only have a date because it's baked into the filename.

`phototime` looks at all three sources for a given image and tells you which
one it trusts and why, and flags it when they disagree by more than a day.

## Usage

```
$ phototime IMG_20230405_142212.jpg
IMG_20230405_142212.jpg
  taken:  2023-04-05 14:22:12  (source: exif:DateTimeOriginal)
```

If EXIF is missing but the filename has a recognizable date pattern:

```
$ phototime IMG-20210630-WA0007.jpg
IMG-20210630-WA0007.jpg
  taken:  2021-06-30 00:00:00  (source: filename)
```

With `-v` you see every source phototime found, not just the winner, and any
mismatches worth a second look:

```
$ phototime -v vacation_photo.jpg
vacation_photo.jpg
  taken:  2019-08-02 09:14:03  (source: exif:DateTimeOriginal)
  also:   2024-01-11 16:40:55  (source: mtime)
  note:   exif:DateTimeOriginal and mtime disagree by 1621 days, 7:26:52
```

That's the case phototime exists for: the file's mtime says January 2024
because that's when it was copied off an old phone, but the photo itself was
taken in 2019.

`--json` prints a JSON array instead, one object per file, always with every
source and mismatch (there's no separate verbose mode for JSON - a consumer
can just ignore fields it doesn't need):

```
$ phototime --json vacation_photo.jpg
[
  {
    "path": "vacation_photo.jpg",
    "taken": {"datetime": "2019-08-02T09:14:03", "source": "exif:DateTimeOriginal"},
    "sources": [
      {"datetime": "2019-08-02T09:14:03", "source": "exif:DateTimeOriginal"},
      {"datetime": "2024-01-11T16:40:55", "source": "mtime"}
    ],
    "mismatches": [
      {"a": "exif:DateTimeOriginal", "b": "mtime", "days": 1621.31}
    ]
  }
]
```

A file that can't be read shows up as `{"path": ..., "error": ...}` instead
of a `taken` field, and the process still exits non-zero.

## Install

No third-party dependencies, standard library only.

```
pip install -e .
```

or just run it in place:

```
python -m phototime.cli photo.jpg
```

## How it decides

In order of trust:

1. `EXIF DateTimeOriginal` - when the shutter actually fired, if the camera
   recorded it.
2. `EXIF DateTimeDigitized` - falls back to this if `DateTimeOriginal` is
   missing (common on scanned or re-processed images).
3. `EXIF DateTime` - the IFD0 "file changed" tag, least specific of the three.
4. `png:CreationTime` - a PNG's `Creation Time` tEXt/zTXt chunk, when there's
   no EXIF data to use instead (most PNGs are screenshots or re-encodes with
   no camera EXIF at all).
5. A date pattern in the filename (`IMG_20230405_142212.jpg`,
   `Screenshot_20230405-142212.png`, `IMG-20230405-WA0007.jpg`, and similar).
6. The filesystem's mtime, as a last resort.

PNGs are detected by file signature, not extension, and read the same
DateTimeOriginal/DateTimeDigitized/DateTime tags as JPEGs when the file has
an `eXIf` chunk (common for PNGs exported from RAW converters or phones
that happen to save PNG).

HEIC/HEIF files (the default photo format on recent iPhones) are detected by
their `ftyp` box and a recognized brand (`heic`, `mif1`, `avif`, and similar).
The same DateTimeOriginal/DateTimeDigitized/DateTime tags are read from the
`Exif` item inside the file's `meta` box.

## Current limitations

- JPEG, PNG, and HEIC/HEIF only.
- EXIF parsing covers the DateTime tags only - no GPS, no camera model, no
  orientation.
- Assumes EXIF lives in the first 2MB of a JPEG (4MB of a PNG, 8MB of a
  HEIC), which is true for every camera and phone encoder, but not
  guaranteed by the spec.
- PNG `iTXt` chunks (the international-text variant) aren't read, only
  `tEXt` and `zTXt`.
- HEIC Exif items stored with a construction method other than a plain file
  offset (rare in practice) aren't read.

## License

MIT, see [LICENSE](LICENSE).
