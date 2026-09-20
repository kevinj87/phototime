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

    def test_gps_north_east_with_altitude(self):
        data = fixtures.build_jpeg_with_exif(
            gps_entries=fixtures.build_gps_entries(37.8199, 122.4783, altitude=30.5)
        )
        tags = exif.read_tags(self._write(data))
        gps = tags[exif.TAG_GPS]
        self.assertAlmostEqual(gps["latitude"], 37.8199, places=3)
        self.assertAlmostEqual(gps["longitude"], 122.4783, places=3)
        self.assertAlmostEqual(gps["altitude"], 30.5, places=1)

    def test_gps_south_west_and_below_sea_level(self):
        data = fixtures.build_jpeg_with_exif(
            gps_entries=fixtures.build_gps_entries(-33.8688, -151.2093, altitude=-5.0)
        )
        tags = exif.read_tags(self._write(data))
        gps = tags[exif.TAG_GPS]
        self.assertAlmostEqual(gps["latitude"], -33.8688, places=3)
        self.assertAlmostEqual(gps["longitude"], -151.2093, places=3)
        self.assertAlmostEqual(gps["altitude"], -5.0, places=1)

    def test_gps_without_altitude(self):
        data = fixtures.build_jpeg_with_exif(
            gps_entries=fixtures.build_gps_entries(1.5, 2.5)
        )
        tags = exif.read_tags(self._write(data))
        self.assertIsNone(tags[exif.TAG_GPS]["altitude"])

    def test_no_gps_ifd_pointer_means_no_gps_key(self):
        data = fixtures.build_jpeg_with_exif(
            exif_tags={exif.TAG_DATETIME_ORIGINAL: "2023:04:05 14:22:12"}
        )
        tags = exif.read_tags(self._write(data))
        self.assertNotIn(exif.TAG_GPS, tags)


if __name__ == "__main__":
    unittest.main()
