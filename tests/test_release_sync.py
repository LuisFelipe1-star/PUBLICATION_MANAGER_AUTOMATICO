import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sync_release", ROOT / "scripts" / "sync_release.py")
SYNC = importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SYNC)


class ReleaseSyncTests(unittest.TestCase):
    def test_build_entries_uses_global_order_and_existing_caption(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root=Path(temp_dir);video=root/"CAPITULO_02"/"parte_01.mp4";video.parent.mkdir();video.write_bytes(b"video")
            metadata=root/"metadata.json";metadata.write_text(json.dumps({"parts":[{"order":17,"video_file":"CAPITULO_02/parte_01.mp4","post_text":"novo"}]}),encoding="utf-8")
            entries,assets=SYNC.build_entries(metadata,{"videos":[{"id":"parte_17","caption":"revisada"}]})
            self.assertEqual(entries[0]["video_path"],"parte_17.mp4");self.assertEqual(entries[0]["caption"],"revisada");self.assertEqual(assets["parte_17.mp4"],video)
    def test_override_rebuilds_structured_caption(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root=Path(temp_dir);video=root/"parte.mp4";video.write_bytes(b"video");metadata=root/"metadata.json";metadata.write_text(json.dumps({"parts":[{"order":2,"video_file":"parte.mp4","title":"A","description":"B","hashtags":["#A"],"post_text":"old"}]}),encoding="utf-8")
            entries,_=SYNC.build_entries(metadata,overrides={"parte_02":{"title":"Título","description":"Descrição","hashtags":["#Um"]}})
            self.assertIn("Título:\nTítulo",entries[0]["caption"]);self.assertIn("PARTE 2",entries[0]["caption"]);self.assertIn("#Um",entries[0]["caption"])
    def test_duplicate_order_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root=Path(temp_dir);video=root/"parte.mp4";video.write_bytes(b"video");metadata=root/"metadata.json";metadata.write_text(json.dumps({"parts":[{"order":1,"video_file":"parte.mp4","post_text":"one"},{"order":1,"video_file":"parte.mp4","post_text":"two"}]}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"duplicada"):SYNC.build_entries(metadata)


if __name__ == "__main__":unittest.main()
