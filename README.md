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
4. A date pattern in the filename (`IMG_20230405_142212.jpg`,
   `Screenshot_20230405-142212.png`, `IMG-20230405-WA0007.jpg`, and similar).
5. The filesystem's mtime, as a last resort.

## Current limitations

- Only reads EXIF from JPEG files. PNG (tEXt/eXIf chunks) and HEIC are not
  supported yet.
- EXIF parsing covers the DateTime tags only - no GPS, no camera model, no
  orientation.
- Assumes EXIF lives in the first 2MB of the file, which is true for every
  camera and phone JPEG encoder, but not guaranteed by the JPEG spec.

## License

MIT, see [LICENSE](LICENSE).
