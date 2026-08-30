import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publish_instagram", ROOT / "scripts" / "publish_instagram.py"
)
PUBLISHER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PUBLISHER)


class PublicationSlotTests(unittest.TestCase):
    def test_known_slot_uses_bahia_calendar_day(self):
        now = datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(PUBLISHER.publication_slot_key("1930", now), "2026-08-30:1930")

    def test_manual_execution_has_no_slot(self):
        self.assertIsNone(PUBLISHER.publication_slot_key("manual"))

    def test_completed_slot_is_idempotent(self):
        state = {"published": [], "completed_slots": ["2026-08-30:1245"]}
        PUBLISHER.mark_slot_completed(state, "2026-08-30:1245")
        self.assertEqual(state["completed_slots"], ["2026-08-30:1245"])

    def test_completed_slots_are_bounded(self):
        state = {"completed_slots": [f"slot-{index}" for index in range(120)]}
        PUBLISHER.mark_slot_completed(state, "new-slot")
        self.assertEqual(len(state["completed_slots"]), 120)
        self.assertEqual(state["completed_slots"][-1], "new-slot")

    def test_dry_run_validates_credentials_without_publishing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "manifest.json"
            published = root / "published.json"
            manifest.write_text(
                json.dumps([{"id": "video-1", "video_path": "video.mp4"}]),
                encoding="utf-8",
            )
            published.write_text(json.dumps({"published": []}), encoding="utf-8")
            env = {
                "IG_ACCESS_TOKEN": "token",
                "IG_USER_ID": "17841400000000000",
                "GRAPH_VERSION": "v26.0",
                "DRY_RUN": "true",
                "PUBLISH_SLOT": "manual",
            }
            with (
                patch.object(PUBLISHER, "MANIFEST", manifest),
                patch.object(PUBLISHER, "PUBLISHED", published),
                patch.dict(os.environ, env, clear=True),
                patch.object(
                    PUBLISHER,
                    "api",
                    return_value={
                        "id": "17841400000000000",
                        "username": "passaproladoofc",
                    },
                ) as api_mock,
            ):
                self.assertEqual(PUBLISHER.main(), 0)

            api_mock.assert_called_once_with(
                "GET",
                "https://graph.facebook.com/v26.0/17841400000000000",
                "token",
                params={"fields": "id,username"},
            )
            self.assertEqual(
                json.loads(published.read_text(encoding="utf-8")),
                {"published": []},
            )

    def test_dry_run_requires_credentials(self):
        with patch.dict(os.environ, {"DRY_RUN": "true"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "IG_ACCESS_TOKEN"):
                PUBLISHER.main()


if __name__ == "__main__":
    unittest.main()
