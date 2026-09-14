import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime

from phototime import cli, exif

from . import fixtures


class FromFilenameTests(unittest.TestCase):
    def test_full_datetime_variants(self):
        for name in (
            "IMG_20230405_142212.jpg",
            "20230405-142212.jpg",
            "Screenshot_20230405-142212.png",
        ):
            self.assertEqual(cli._from_filename(name), datetime(2023, 4, 5, 14, 22, 12))

    def test_date_only_fallback(self):
        self.assertEqual(cli._from_filename("IMG-20210630-WA0007.jpg"), datetime(2021, 6, 30))

    def test_no_date_found(self):
        self.assertIsNone(cli._from_filename("vacation_photo.jpg"))

    def test_implausible_date_rejected(self):
        self.assertIsNone(cli._from_filename("file_39991301_999999.jpg"))


class ParseExifDatetimeTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(
            cli._parse_exif_datetime("2023:04:05 14:22:12"),
            datetime(2023, 4, 5, 14, 22, 12),
        )

    def test_wrong_separator_rejected(self):
        self.assertIsNone(cli._parse_exif_datetime("2023-04-05 14:22:12"))

    def test_garbage_rejected(self):
        self.assertIsNone(cli._parse_exif_datetime("not a date"))


class GatherSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, name, data):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_exif_wins_over_filename_and_mtime(self):
        data = fixtures.build_jpeg_with_exif(
            exif_tags={exif.TAG_DATETIME_ORIGINAL: "2019:08:02 09:14:03"}
        )
        path = self._write("IMG_20230405_142212.jpg", data)
        sources = cli.gather_sources(path)
        self.assertEqual(
            sources[0], ("exif:DateTimeOriginal", datetime(2019, 8, 2, 9, 14, 3))
        )
        labels = [label for label, _ in sources]
        self.assertIn("filename", labels)
        self.assertIn("mtime", labels)

    def test_exif_priority_order(self):
        data = fixtures.build_jpeg_with_exif(
            ifd0_tags={exif.TAG_DATETIME: "2020:01:01 00:00:00"},
            exif_tags={
                exif.TAG_DATETIME_ORIGINAL: "2019:08:02 09:14:03",
                exif.TAG_DATETIME_DIGITIZED: "2019:08:03 09:14:03",
            },
        )
        path = self._write("photo.jpg", data)
        labels = [label for label, _ in cli.gather_sources(path)]
        self.assertEqual(
            labels[:3],
            ["exif:DateTimeOriginal", "exif:DateTimeDigitized", "exif:DateTime"],
        )

    def test_png_creation_time_used_when_no_exif(self):
        data = fixtures.build_png(creation_time="Wed, 02 Aug 2019 09:14:03 GMT")
        path = self._write("screenshot.png", data)
        sources = cli.gather_sources(path)
        self.assertEqual(sources[0], ("png:CreationTime", datetime(2019, 8, 2, 9, 14, 3)))

    def test_heic_exif(self):
        data = fixtures.build_heic_with_exif(
            exif_tags={exif.TAG_DATETIME_ORIGINAL: "2021:06:30 08:00:00"}
        )
        path = self._write("IMG_1234.heic", data)
        sources = cli.gather_sources(path)
        self.assertEqual(
            sources[0], ("exif:DateTimeOriginal", datetime(2021, 6, 30, 8, 0, 0))
        )

    def test_falls_back_to_mtime_only(self):
        path = self._write("plain.jpg", b"\xff\xd8\xff\xd9")
        mtime = datetime(2024, 1, 11, 16, 40, 55)
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
        self.assertEqual(cli.gather_sources(path), [("mtime", mtime)])


class FindMismatchesTests(unittest.TestCase):
    def test_flags_pairs_over_threshold_only(self):
        sources = [
            ("a", datetime(2020, 1, 1)),
            ("b", datetime(2020, 1, 1, 12)),
            ("c", datetime(2023, 1, 1)),
        ]
        pairs = {(a, b) for a, b, _ in cli.find_mismatches(sources)}
        self.assertEqual(pairs, {("a", "c"), ("b", "c")})


class BuildResultTests(unittest.TestCase):
    def test_json_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "photo.jpg")
            with open(path, "wb") as f:
                f.write(
                    fixtures.build_jpeg_with_exif(
                        exif_tags={exif.TAG_DATETIME_ORIGINAL: "2019:08:02 09:14:03"}
                    )
                )
            result = cli.build_result(path)
        self.assertEqual(result["taken"], {
            "datetime": "2019-08-02T09:14:03",
            "source": "exif:DateTimeOriginal",
        })
        self.assertIsInstance(result["sources"], list)
        self.assertIsInstance(result["mismatches"], list)
        self.assertTrue(any(s["source"] == "exif:DateTimeOriginal" for s in result["sources"]))


class MainCliTests(unittest.TestCase):
    def test_missing_file_json_reports_error_and_exit_code(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["--json", "/no/such/file.jpg"])
        self.assertEqual(code, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload, [{"path": "/no/such/file.jpg", "error": "no such file"}])

    def test_directory_without_recursive_flag_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main(["--json", tmp])
        self.assertEqual(code, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["path"], tmp)
        self.assertIn("directory", payload[0]["error"])

    def test_recursive_scan_finds_nested_images_and_skips_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "album")
            os.makedirs(nested)
            jpeg_path = os.path.join(nested, "photo.jpg")
            with open(jpeg_path, "wb") as f:
                f.write(
                    fixtures.build_jpeg_with_exif(
                        exif_tags={exif.TAG_DATETIME_ORIGINAL: "2019:08:02 09:14:03"}
                    )
                )
            with open(os.path.join(nested, "notes.txt"), "w") as f:
                f.write("not a photo")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main(["--json", "-r", tmp])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["path"], jpeg_path)
        self.assertEqual(payload[0]["taken"]["source"], "exif:DateTimeOriginal")

    def test_text_report_includes_source_and_mismatch_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "vacation_photo.jpg")
            with open(path, "wb") as f:
                f.write(
                    fixtures.build_jpeg_with_exif(
                        exif_tags={exif.TAG_DATETIME_ORIGINAL: "2019:08:02 09:14:03"}
                    )
                )
            old = datetime(2024, 1, 11, 16, 40, 55).timestamp()
            os.utime(path, (old, old))
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main([path])
        output = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("taken:  2019-08-02 09:14:03  (source: exif:DateTimeOriginal)", output)
        self.assertIn("disagree by", output)


if __name__ == "__main__":
    unittest.main()
