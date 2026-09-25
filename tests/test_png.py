import os
import tempfile
import unittest
import zlib

from phototime import exif, png

from . import fixtures


class ReadTagsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, data, name="fixture.png"):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_exif_chunk_read(self):
        tiff = fixtures.build_tiff(exif_tags={exif.TAG_DATETIME_ORIGINAL: "2023:04:05 14:22:12"})
        tags = png.read_tags(self._write(fixtures.build_png(exif_tiff=tiff)))
        self.assertEqual(tags[exif.TAG_DATETIME_ORIGINAL], "2023:04:05 14:22:12")

    def test_creation_time_text_chunk(self):
        data = fixtures.build_png(creation_time="Wed, 02 Aug 2019 09:14:03 GMT")
        tags = png.read_tags(self._write(data))
        self.assertEqual(tags[png.TAG_CREATION_TIME], "Wed, 02 Aug 2019 09:14:03 GMT")

    def test_creation_time_ztxt_chunk(self):
        text = b"Wed, 02 Aug 2019 09:14:03 GMT"
        chunk_data = b"Creation Time\x00\x00" + zlib.compress(text)
        data = fixtures.build_png(chunks=[(b"zTXt", chunk_data)])
        tags = png.read_tags(self._write(data))
        self.assertEqual(tags[png.TAG_CREATION_TIME], text.decode("ascii"))

    def test_creation_time_itxt_chunk(self):
        chunk_data = b"Creation Time\x00\x00\x00\x00\x00" + "Wed, 02 Aug 2019 09:14:03 GMT".encode("utf-8")
        data = fixtures.build_png(chunks=[(b"iTXt", chunk_data)])
        tags = png.read_tags(self._write(data))
        self.assertEqual(tags[png.TAG_CREATION_TIME], "Wed, 02 Aug 2019 09:14:03 GMT")

    def test_creation_time_itxt_chunk_compressed(self):
        text = "Wed, 02 Aug 2019 09:14:03 GMT".encode("utf-8")
        chunk_data = b"Creation Time\x00\x01\x00\x00\x00" + zlib.compress(text)
        data = fixtures.build_png(chunks=[(b"iTXt", chunk_data)])
        tags = png.read_tags(self._write(data))
        self.assertEqual(tags[png.TAG_CREATION_TIME], "Wed, 02 Aug 2019 09:14:03 GMT")

    def test_itxt_unicode_text(self):
        text = "2019-08-02 café".encode("utf-8")
        chunk_data = b"Creation Time\x00\x00\x00\x00\x00" + text
        data = fixtures.build_png(chunks=[(b"iTXt", chunk_data)])
        tags = png.read_tags(self._write(data))
        self.assertEqual(tags[png.TAG_CREATION_TIME], "2019-08-02 café")

    def test_no_metadata_returns_empty(self):
        self.assertEqual(png.read_tags(self._write(fixtures.build_png())), {})

    def test_not_a_png_raises(self):
        path = self._write(b"not a png")
        with self.assertRaises(png.PngError):
            png.read_tags(path)


if __name__ == "__main__":
    unittest.main()
