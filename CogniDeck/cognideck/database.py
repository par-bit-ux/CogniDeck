"""Local SQLite storage for decks, cards, reviews and quiz results (cognideck.db)."""

import sqlite3
from datetime import date, datetime, timedelta

from . import DB_PATH
from .scheduler import NEEDS_REVIEW, NEW, STATUSES, schedule

# The four tables. "IF NOT EXISTS" means this is safe to run every time the app starts.
#   decks         one row per deck, plus the original notes it was made from
#   cards         flashcards, with their study status and spaced-repetition schedule
#   reviews       a log of every rating and quiz answer (powers the charts and streak)
#   quiz_results  the score of each finished quiz
# ON DELETE CASCADE means deleting a deck also deletes its cards, reviews and results.
SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    mode        TEXT NOT NULL DEFAULT 'auto',
    source_text TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id        INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL DEFAULT 0,
    front          TEXT NOT NULL,
    back           TEXT NOT NULL,
    card_type      TEXT NOT NULL DEFAULT 'manual',
    status         TEXT NOT NULL DEFAULT 'new',
    review_count   INTEGER NOT NULL DEFAULT 0,
    correct_count  INTEGER NOT NULL DEFAULT 0,
    ease           REAL NOT NULL DEFAULT 2.5,
    interval_days  REAL NOT NULL DEFAULT 0,
    due_at         TEXT,
    last_reviewed  TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    rating      TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'study',
    reviewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_results (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id  INTEGER REFERENCES decks(id) ON DELETE CASCADE,
    score    INTEGER NOT NULL,
    total    INTEGER NOT NULL,
    taken_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cards_deck ON cards(deck_id);
CREATE INDEX IF NOT EXISTS idx_reviews_card ON reviews(card_id);
"""


def _now():
    """Current time as text, e.g. "2026-03-14T16:05:09" (sorts correctly as a string)."""
    return datetime.now().isoformat(timespec="seconds")


class Database:
    """All reading and writing of cognideck.db goes through this class."""

    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(str(path))
        # Rows behave like dictionaries, so code can write card["front"] instead of card[3].
        self.conn.row_factory = sqlite3.Row
        # SQLite only enforces REFERENCES / ON DELETE CASCADE when this is switched on.
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ----- decks -------------------------------------------------------------

    def create_deck(self, name, cards=(), mode="auto", source_text=""):
        """Create a deck and insert its cards in one transaction. Returns the deck id."""
        # `with self.conn` commits if everything succeeds and rolls back if anything fails,
        # so a deck is never saved half-finished.
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO decks (name, mode, source_text, created_at) VALUES (?, ?, ?, ?)",
                (name.strip() or "Untitled deck", mode, source_text, _now()),
            )
            deck_id = cur.lastrowid
            for position, card in enumerate(cards):
                self._insert_card(deck_id, card.front, card.back, card.card_type, position)
        return deck_id

    def list_decks(self):
        """Every deck, newest first, with how many cards it has and how many are mastered."""
        # LEFT JOIN keeps decks that have no cards yet (their count is 0).
        return self.conn.execute(
            """
            SELECT d.*, COUNT(c.id) AS card_count,
                   SUM(CASE WHEN c.status = 'mastered' THEN 1 ELSE 0 END) AS mastered_count
            FROM decks d LEFT JOIN cards c ON c.deck_id = d.id
            GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC
            """
        ).fetchall()

    def get_deck(self, deck_id):
        return self.conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()

    def rename_deck(self, deck_id, name):
        with self.conn:
            self.conn.execute("UPDATE decks SET name = ? WHERE id = ?", (name.strip(), deck_id))

    def delete_deck(self, deck_id):
        with self.conn:
            self.conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))

    # ----- cards -------------------------------------------------------------

    def _insert_card(self, deck_id, front, back, card_type, position):
        """Insert one new card (status "new"). The caller handles the transaction."""
        # The ? placeholders let SQLite insert the values safely (no SQL injection).
        return self.conn.execute(
            """INSERT INTO cards (deck_id, position, front, back, card_type, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (deck_id, position, front.strip(), back.strip(), card_type, NEW, _now()),
        ).lastrowid

    def add_card(self, deck_id, front, back, card_type="manual"):
        """Add a hand-written card to the end of a deck."""
        with self.conn:
            # Next position = highest position in the deck + 1 (or 0 for an empty deck).
            position = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM cards WHERE deck_id = ?", (deck_id,)
            ).fetchone()[0]
            return self._insert_card(deck_id, front, back, card_type, position)

    def update_card(self, card_id, front, back):
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET front = ?, back = ? WHERE id = ?", (front.strip(), back.strip(), card_id)
            )

    def delete_card(self, card_id):
        with self.conn:
            self.conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))

    def get_card(self, card_id):
        return self.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()

    def get_cards(self, deck_id):
        return self.conn.execute(
            "SELECT * FROM cards WHERE deck_id = ? ORDER BY position, id", (deck_id,)
        ).fetchall()

    def all_cards(self):
        return self.conn.execute("SELECT * FROM cards ORDER BY deck_id, position, id").fetchall()

    def rate_card(self, card_id, rating, source="study"):
        """Apply a self-rating: update the schedule and log the review."""
        card = self.get_card(card_id)
        # The scheduler works out the new status, interval and due date.
        updates = schedule(card, rating)
        # Update the card and log the review together, so they can't get out of step.
        with self.conn:
            self.conn.execute(
                """UPDATE cards SET status = ?, interval_days = ?, ease = ?, due_at = ?,
                       last_reviewed = ?, review_count = review_count + 1
                   WHERE id = ?""",
                (updates["status"], updates["interval_days"], updates["ease"],
                 updates["due_at"], updates["last_reviewed"], card_id),
            )
            self.conn.execute(
                "INSERT INTO reviews (card_id, rating, source, reviewed_at) VALUES (?, ?, ?, ?)",
                (card_id, rating, source, updates["last_reviewed"]),
            )
        return self.get_card(card_id)

    def record_quiz_answer(self, card_id, correct):
        """Count a quiz answer; a wrong answer sends the card back to Needs Review."""
        # The card may have been deleted while the quiz was running.
        if card_id is None or self.get_card(card_id) is None:
            return
        # A right answer is counted but doesn't change the card's status or schedule.
        if correct:
            with self.conn:
                self.conn.execute(
                    "UPDATE cards SET correct_count = correct_count + 1, review_count = review_count + 1,"
                    " last_reviewed = ? WHERE id = ?",
                    (_now(), card_id),
                )
                self.conn.execute(
                    "INSERT INTO reviews (card_id, rating, source, reviewed_at) VALUES (?, 'correct', 'quiz', ?)",
                    (card_id, _now()),
                )
        else:
            self.rate_card(card_id, NEEDS_REVIEW, source="quiz")

    def reset_progress(self, deck_id):
        """Put every card in a deck back to "new" with a fresh schedule (the review log is kept)."""
        with self.conn:
            self.conn.execute(
                """UPDATE cards SET status = 'new', review_count = 0, correct_count = 0, ease = 2.5,
                       interval_days = 0, due_at = NULL, last_reviewed = NULL WHERE deck_id = ?""",
                (deck_id,),
            )

    # ----- quizzes -----------------------------------------------------------

    def save_quiz_result(self, deck_id, score, total):
        with self.conn:
            self.conn.execute(
                "INSERT INTO quiz_results (deck_id, score, total, taken_at) VALUES (?, ?, ?, ?)",
                (deck_id, score, total, _now()),
            )

    def quiz_history(self, deck_id=None, limit=30):
        """The latest `limit` quiz results (for one deck, or all), returned oldest first for charting."""
        if deck_id is None:
            rows = self.conn.execute(
                "SELECT * FROM quiz_results ORDER BY taken_at DESC, id DESC LIMIT ?", (limit,)
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM quiz_results WHERE deck_id = ? ORDER BY taken_at DESC, id DESC LIMIT ?",
                (deck_id, limit),
            )
        # The query takes the newest rows; reverse them so the chart reads left to right in time.
        return list(reversed(rows.fetchall()))

    # ----- statistics --------------------------------------------------------

    def status_counts(self, deck_id=None):
        """How many cards are in each status, e.g. {"new": 4, "mastered": 2, ...}."""
        # Start every status at 0 so statuses with no cards still appear.
        counts = dict.fromkeys(STATUSES, 0)
        if deck_id is None:
            rows = self.conn.execute("SELECT status, COUNT(*) FROM cards GROUP BY status")
        else:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) FROM cards WHERE deck_id = ? GROUP BY status", (deck_id,)
            )
        for status, count in rows:
            counts[status] = count
        return counts

    def reviews_per_day(self, days=14):
        """Return [(date, count)] for the last `days` days, oldest first, zero-filled."""
        start = date.today() - timedelta(days=days - 1)
        # substr(..., 1, 10) takes just the date part ("2026-03-14") of the timestamp.
        rows = self.conn.execute(
            "SELECT substr(reviewed_at, 1, 10) AS day, COUNT(*) FROM reviews WHERE day >= ? GROUP BY day",
            (start.isoformat(),),
        )
        by_day = {day: count for day, count in rows}
        # Days with no reviews aren't in the query result, so fill them in with 0.
        return [
            (start + timedelta(days=i), by_day.get((start + timedelta(days=i)).isoformat(), 0))
            for i in range(days)
        ]

    def study_streak(self):
        """Number of consecutive days, ending today (or yesterday), with at least one review."""
        days = {
            row[0]
            for row in self.conn.execute("SELECT DISTINCT substr(reviewed_at, 1, 10) FROM reviews")
        }
        day = date.today()
        # Not studied yet today? The streak isn't broken until the day is over, so count from yesterday.
        if day.isoformat() not in days:
            day -= timedelta(days=1)
        # Walk backwards one day at a time until a day with no reviews.
        streak = 0
        while day.isoformat() in days:
            streak += 1
            day -= timedelta(days=1)
        return streak

    def reviews_today(self):
        """Number of ratings and quiz answers logged today."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE substr(reviewed_at, 1, 10) = ?", (date.today().isoformat(),)
        ).fetchone()[0]
