import os
import tempfile
import unittest

from phototime import exif

from . import fixtures


class ReadTagsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, data, name="fixture.jpg"):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_missing_exif_returns_empty(self):
        path = self._write(b"\xff\xd8\xff\xd9")
        self.assertEqual(exif.read_tags(path), {})

    def test_datetime_original_and_digitized(self):
        data = fixtures.build_jpeg_with_exif(
            exif_tags={
                exif.TAG_DATETIME_ORIGINAL: "2023:04:05 14:22:12",
                exif.TAG_DATETIME_DIGITIZED: "2023:04:05 14:25:00",
            }
        )
        tags = exif.read_tags(self._write(data))
        self.assertEqual(tags[exif.TAG_DATETIME_ORIGINAL], "2023:04:05 14:22:12")
        self.assertEqual(tags[exif.TAG_DATETIME_DIGITIZED], "2023:04:05 14:25:00")

    def test_ifd0_datetime_without_exif_subifd(self):
        data = fixtures.build_jpeg_with_exif(ifd0_tags={exif.TAG_DATETIME: "2020:01:01 00:00:00"})
        tags = exif.read_tags(self._write(data))
        self.assertEqual(tags, {exif.TAG_DATETIME: "2020:01:01 00:00:00"})

    def test_not_a_jpeg_raises(self):
        path = self._write(b"not a jpeg at all")
        with self.assertRaises(exif.ExifError):
            exif.read_tags(path)


if __name__ == "__main__":
    unittest.main()
