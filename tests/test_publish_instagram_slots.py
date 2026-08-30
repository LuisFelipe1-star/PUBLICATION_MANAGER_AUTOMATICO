import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
