"""CogniDeck: turn raw study notes into active-recall flashcards and quizzes, fully offline."""

from pathlib import Path

__version__ = "1.0.0"

# Data files live in the project folder (one level above this package), whichever
# folder the app is started from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "cognideck.db"
EXPORT_PATH = PROJECT_ROOT / "flashcards.json"
