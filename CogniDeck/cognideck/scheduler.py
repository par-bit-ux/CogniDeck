"""Spaced-repetition scheduling.

Each self-rating moves a card between four study states and decides when it
should come back. The rules are a simplified version of the SM-2 / Leitner idea:
cards you know well are shown less and less often, cards you miss come back soon.
"""

from datetime import datetime, timedelta

# The four study states a card can be in (stored as text in the database).
NEW = "new"
NEEDS_REVIEW = "needs_review"
IN_PROGRESS = "in_progress"
MASTERED = "mastered"

STATUSES = (NEW, NEEDS_REVIEW, IN_PROGRESS, MASTERED)

STATUS_LABELS = {
    NEW: "New",
    NEEDS_REVIEW: "Needs Review",
    IN_PROGRESS: "In Progress",
    MASTERED: "Mastered",
}

# "Ease" multiplies the gap between reviews each time a card is mastered.
# It's kept between these limits so intervals never stall or explode.
MIN_EASE = 1.3
MAX_EASE = 3.0


def schedule(card, rating, now=None):
    """Return the field updates for `card` after the student rates it.

    `card` is a mapping with `interval_days` and `ease`; `rating` is one of
    NEEDS_REVIEW, IN_PROGRESS or MASTERED.
    """
    if rating not in (NEEDS_REVIEW, IN_PROGRESS, MASTERED):
        raise ValueError(f"Unknown rating: {rating}")

    # `now` can be passed in so tests get predictable dates.
    now = now or datetime.now()
    interval = float(card["interval_days"] or 0)
    ease = float(card["ease"] or 2.5)

    if rating == NEEDS_REVIEW:
        # Missed it: see it again in this session (10 minutes) and make it harder to graduate.
        ease = max(MIN_EASE, ease - 0.2)
        interval = 0
        due = now + timedelta(minutes=10)
    elif rating == IN_PROGRESS:
        # Partly remembered: grow the gap slowly.
        interval = 1 if interval < 1 else round(interval * 1.5, 1)
        due = now + timedelta(days=interval)
    else:
        # Mastered: grow the gap quickly and make it easier next time.
        interval = max(3, round(max(interval, 1) * ease, 1))
        ease = min(MAX_EASE, ease + 0.1)
        due = now + timedelta(days=interval)

    return {
        "status": rating,
        "interval_days": interval,
        "ease": round(ease, 2),
        "due_at": due.isoformat(timespec="seconds"),
        "last_reviewed": now.isoformat(timespec="seconds"),
    }


def is_due(card, now=None):
    """A card is due if it has never been scheduled or its due time has passed."""
    if not card["due_at"]:
        return True
    now = now or datetime.now()
    return datetime.fromisoformat(card["due_at"]) <= now


def study_order(cards, now=None):
    """Order cards for a study session: missed cards first, then new, then due, then the rest."""
    now = now or datetime.now()
    priority = {NEEDS_REVIEW: 0, NEW: 1, IN_PROGRESS: 2, MASTERED: 3}

    # Python sorts tuples item by item: due cards first, then by status priority,
    # then in the order the cards were written.
    def key(card):
        due_rank = 0 if is_due(card, now) else 1
        return (due_rank, priority.get(card["status"], 4), card["position"], card["id"])

    return sorted(cards, key=key)
