from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from ..pipeline import IngestError, ingest_source


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IngestPipelineTests(unittest.TestCase):
    def test_png_is_ingested_without_resampling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.png"
            Image.new("RGB", (17, 11), (10, 20, 30)).save(source, dpi=(150, 150))

            manifest_path = ingest_source(source, root / "output")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            page = manifest["document"]["pages"][0]
            self.assertEqual(page["source"]["dimensions"]["width"], 17)
            self.assertEqual(page["source"]["dimensions"]["height"], 11)
            self.assertEqual(page["rendered"]["dimensions"]["width"], 17)
            self.assertEqual(page["rendered"]["dimensions"]["height"], 11)
            self.assertEqual(manifest["source"]["detected_format"], "png")

    def test_jpeg_exif_rotation_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.jpg"
            image = Image.new("RGB", (13, 7), (40, 50, 60))
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)

            manifest_path = ingest_source(source, root / "output")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            page = manifest["document"]["pages"][0]

            self.assertEqual(page["source"]["rotation_applied_degrees_clockwise"], 90)
            self.assertEqual(page["rendered"]["dimensions"]["width"], 7)
            self.assertEqual(page["rendered"]["dimensions"]["height"], 13)

    def test_same_source_produces_identical_manifest_and_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.png"
            Image.new("RGBA", (9, 5), (1, 2, 3, 4)).save(source)

            first_manifest = ingest_source(source, root / "first")
            second_manifest = ingest_source(source, root / "second")

            self.assertEqual(first_manifest.read_bytes(), second_manifest.read_bytes())
            self.assertEqual(
                _digest(first_manifest.parent / "pages" / "page_0001.png"),
                _digest(second_manifest.parent / "pages" / "page_0001.png"),
            )

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.png"
            destination = root / "output"
            destination.mkdir()
            sentinel = destination / "keep.txt"
            sentinel.write_text("untouched", encoding="utf-8")
            Image.new("RGB", (2, 2)).save(source)

            with self.assertRaises(IngestError):
                ingest_source(source, destination)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")


if __name__ == "__main__":
    unittest.main()
