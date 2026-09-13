import os
import tempfile
import unittest

from phototime import exif, heic

from . import fixtures


class ReadTagsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, data, name="fixture.heic"):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_datetime_original_from_exif_item(self):
        data = fixtures.build_heic_with_exif(
            exif_tags={exif.TAG_DATETIME_ORIGINAL: "2021:06:30 08:00:00"}
        )
        tags = heic.read_tags(self._write(data))
        self.assertEqual(tags[exif.TAG_DATETIME_ORIGINAL], "2021:06:30 08:00:00")

    def test_exif_item_present_but_no_datetime_tags(self):
        tags = heic.read_tags(self._write(fixtures.build_heic_with_exif()))
        self.assertEqual(tags, {})

    def test_meta_without_exif_item_returns_empty(self):
        ftyp = fixtures.build_ftyp()
        iinf = fixtures.build_iinf([(1, b"mime")])
        iloc = fixtures.build_iloc([(1, 0, 0)])
        data = ftyp + fixtures.build_meta(iinf, iloc)
        self.assertEqual(heic.read_tags(self._write(data)), {})

    def test_missing_meta_box_returns_empty(self):
        self.assertEqual(heic.read_tags(self._write(fixtures.build_ftyp())), {})

    def test_unrecognized_brand_raises(self):
        path = self._write(fixtures.build_ftyp(major_brand=b"jpeg"))
        with self.assertRaises(heic.HeicError):
            heic.read_tags(path)

    def test_not_isobmff_raises(self):
        path = self._write(b"not isobmff data at all")
        with self.assertRaises(heic.HeicError):
            heic.read_tags(path)


if __name__ == "__main__":
    unittest.main()
