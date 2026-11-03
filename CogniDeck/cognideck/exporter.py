"""JSON export of every deck to flashcards.json, refreshed automatically after each change."""

import json
from datetime import datetime

from . import EXPORT_PATH, __version__


def deck_to_dict(db, deck):
    """Convert one deck and its cards into plain dictionaries that json can save."""
    return {
        "id": deck["id"],
        "name": deck["name"],
        "mode": deck["mode"],
        "created_at": deck["created_at"],
        "cards": [
            {
                "id": card["id"],
                "front": card["front"],
                "back": card["back"],
                "type": card["card_type"],
                "status": card["status"],
                "review_count": card["review_count"],
                "correct_count": card["correct_count"],
                "next_review": card["due_at"],
                "last_reviewed": card["last_reviewed"],
            }
            for card in db.get_cards(deck["id"])
        ],
    }


def export_all(db, path=EXPORT_PATH):
    """Write all decks and cards to `path`. Returns the path written."""
    data = {
        "app": "CogniDeck",
        "version": __version__,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "decks": [deck_to_dict(db, deck) for deck in db.list_decks()],
    }
    # Write to a temporary file first, then swap it in. If the app crashes mid-write,
    # the old flashcards.json is left intact instead of half-written.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path
