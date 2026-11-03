"""Tests for the spaced-repetition scheduler, the SQLite database, quiz building and JSON export."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from cognideck.database import Database
from cognideck.exporter import export_all
from cognideck.parser import parse_notes
from cognideck.quiz import build_quiz
from cognideck.sample_notes import MACBETH_NOTES
from cognideck.scheduler import IN_PROGRESS, MASTERED, NEEDS_REVIEW, schedule


class SchedulerTests(unittest.TestCase):
    # A plain dict is enough to stand in for a database row here.
    def card(self, interval=0, ease=2.5):
        return {"interval_days": interval, "ease": ease}

    def test_needs_review_comes_back_soon(self):
        now = datetime(2026, 1, 1, 12, 0)
        result = schedule(self.card(5), NEEDS_REVIEW, now)
        self.assertEqual(result["interval_days"], 0)
        self.assertEqual(result["due_at"], "2026-01-01T12:10:00")

    def test_mastered_grows_interval(self):
        first = schedule(self.card(), MASTERED)
        second = schedule(first, MASTERED)
        self.assertGreaterEqual(first["interval_days"], 3)
        self.assertGreater(second["interval_days"], first["interval_days"])

    def test_in_progress_starts_at_one_day(self):
        self.assertEqual(schedule(self.card(), IN_PROGRESS)["interval_days"], 1)


class DatabaseAndQuizTests(unittest.TestCase):
    # Each test gets its own throwaway database (filled with the Macbeth sample deck),
    # so tests never touch the real cognideck.db.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.deck = self.db.create_deck("Macbeth", parse_notes(MACBETH_NOTES))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_rating_updates_card_and_logs_review(self):
        card = self.db.get_cards(self.deck)[0]
        updated = self.db.rate_card(card["id"], MASTERED)
        self.assertEqual(updated["status"], MASTERED)
        self.assertEqual(updated["review_count"], 1)
        self.assertEqual(self.db.reviews_today(), 1)
        self.assertEqual(self.db.study_streak(), 1)

    def test_wrong_quiz_answer_needs_review(self):
        card = self.db.get_cards(self.deck)[0]
        self.db.record_quiz_answer(card["id"], correct=False)
        self.assertEqual(self.db.get_card(card["id"])["status"], NEEDS_REVIEW)

    def test_quiz_questions_are_well_formed(self):
        # seed=7 makes the "random" quiz the same on every run.
        questions = build_quiz(self.db.get_cards(self.deck), 50, seed=7)
        self.assertTrue(questions)
        # Every question needs a valid answer index and no duplicate options.
        for q in questions:
            self.assertIn(q.kind, ("mcq", "tf"))
            self.assertTrue(0 <= q.answer_index < len(q.options))
            self.assertEqual(len(set(q.options)), len(q.options))

    def test_export_json(self):
        path = export_all(self.db, Path(self.tmp.name) / "flashcards.json")
        data = json.loads(path.read_text())
        self.assertEqual(data["decks"][0]["name"], "Macbeth")
        self.assertEqual(len(data["decks"][0]["cards"]), len(self.db.get_cards(self.deck)))

    def test_delete_deck_removes_cards(self):
        self.db.delete_deck(self.deck)
        self.assertEqual(self.db.all_cards(), [])


if __name__ == "__main__":
    unittest.main()
