# CogniDeck

A Python desktop study app that turns raw notes into active-recall flashcard decks and quizzes. It runs fully offline: notes are broken down by a parser that follows fixed rules, so there are no cloud AI calls, API keys or rate limits.

## Run it

```bash
cd ~/Documents/CogniDeck
source .venv/bin/activate
python main.py
```

In VS Code, press **F5** ("Run CogniDeck"). Run the tests with `python -m unittest discover -s tests -v`.

If you set up a fresh virtual environment, install the packages first with `pip install -r requirements.txt`.

## Features

- **Two-column study screen.** Paste notes into **Input (Passive Reading)** on the left, then click **Generate Deck**. The cards appear under **Output (Active Recall)** on the right. A "Card 1 of 5 — FRONT" line shows where you are.
- **Hide your notes while studying.** After you generate a deck, the notes panel shrinks to a thin strip so the answers aren't on screen. Click **▶** on the strip, or press **N**, to bring it back. **◀ Hide** on the notes panel hides it again.
- **Import PDF and Word files.** Click **Open file…** to load notes from a `.pdf`, `.docx`, `.txt` or `.md` file. The text is extracted offline and placed in the notes box, so you can check or tidy it before generating, exactly like pasted notes.
  - **Word (.docx):** headings, bullet and numbered lists keep their structure. Two-column tables become `Term: meaning` lines, so a glossary table turns straight into definition cards.
  - **PDF:** lines that were wrapped are joined back into paragraphs, words split with a hyphen across lines are rejoined, page numbers are removed, and bullet symbols (•, ▪, ►…) are recognised. Short title-like lines are treated as headings.
  - **Google Docs PDFs** store every word separately, which used to break them into one word per line. Each page is now read in two ways and the cleaner result is kept.
  - **Scanned PDFs** (photos or scans of typed or handwritten pages, with no text layer) are read on a Mac with Apple's built-in Live Text recognition, offline. It takes a few seconds per page. Handwriting won't come out perfectly, so check the text before generating.
  - Old `.doc` files need to be saved as `.docx` first.
- **Six parsing modes.** Auto-detect handles mixed notes. The others are:
  - **Essay → key points:** the topic sentence goes on the front and the 2–4 highest-scoring sentences go on the back. Quotes get their own analysis cards.
  - **Definitions:** lines like `Term: meaning`.
  - **Q&A:** `Q:` / `A:` pairs.
  - **Headings & bullets:** one card per heading.
  - **Fill in the blank.**
- **Animated cards.** The card flips over (it squashes and stretches to fake a 3D turn) and slides when you move between cards.
- **Self-rating.** Rate each card **Needs Review**, **In Progress** or **Mastered**. A spaced-repetition scheduler then decides when each card comes back.
- **Quizzes.** Multiple-choice and true/false questions, with wrong options taken from the deck's other cards. Wrong answers send the card back to Needs Review.
- **Deck manager.** Add, edit and delete cards by hand. You can also rename, reset or delete whole decks.
- **Progress dashboard.** Built with matplotlib: a mastery donut, cards reviewed per day, quiz accuracy over time, and your study streak.
- **Storage.** Everything is saved in `cognideck.db` (SQLite) and automatically exported to `flashcards.json`.
- **Dark graphite look with a blue accent.** Switch screens (Study, Quiz, Decks, Progress) with the icon sidebar on the left. The deck picker is at the top right.

## Keyboard shortcuts

| Key | Study screen | Quiz screen |
| --- | --- | --- |
| Space | Flip card | Next question |
| ← / → | Previous / next card | → next question |
| 1 / 2 / 3 | Needs Review / In Progress / Mastered | Pick answer 1–4 |
| N | Hide / show the notes panel | |
| Esc | Leave the notes box so shortcuts work | |

## Project layout

```
main.py                    entry point
cognideck/
  parser.py                offline note parser (essays, definitions, Q&A, bullets, cloze)
  importer.py              reads .pdf / .docx / .txt / .md files into parser-ready text
  quiz.py                  multiple-choice and true/false question builder
  scheduler.py             spaced-repetition rules and study ordering
  database.py              SQLite schema and queries (cognideck.db)
  exporter.py              JSON export (flashcards.json)
  sample_notes.py          Macbeth sample notes (used by the tests)
  ui/
    app.py                 main window, icon sidebar, header and deck picker
    flipcard.py            animated flip card widget
    study_view.py          two-column notes → deck → study screen
    quiz_view.py           quiz screen
    decks_view.py          deck and card manager
    progress_view.py       matplotlib dashboard
    theme.py               colours, fonts and corner rounding (one dark theme)
tests/                     unit tests for the parser, importer, scheduler, database, quiz and export
JOURNAL.txt                week-by-week development journal (weeks 7–12)
```

## How file import works

`cognideck/importer.py` turns a file into the same plain-text format you'd paste in: blocks separated by blank lines, `# ` for headings and `- ` for bullets. The parser then handles it exactly like typed notes.

- A `.docx` file is a zip archive containing XML. The importer reads `word/document.xml` with Python's built-in `zipfile` and `xml` modules, so Word support needs no extra package. Each paragraph's style (`Heading1`, `ListParagraph`, …) decides whether it becomes a heading, a bullet or prose.
- PDFs are read with `pypdf`, which gives back text one printed line at a time. The importer rebuilds paragraphs by assuming a line only continues onto the next one when it is close to full width. A short line means the paragraph, bullet or heading ended there.

## Code comments

Every module starts with a docstring explaining its job. Comments throughout the code explain the reasoning behind each step: how the parser scores sentences, how the scheduler spaces reviews, and how the flip animation is faked in Tkinter.

## Requirements

- Python 3.14 with Tk. On Homebrew, install Tk with `brew install python-tk@3.14`.
- `customtkinter`, `matplotlib` and `pypdf`, listed in `requirements.txt`.
- For scanned PDFs on a Mac: `ocrmac` and `pypdfium2` (also in `requirements.txt`).
