"""Quiz generation: multiple-choice and true/false questions built from a deck's cards.

Wrong options (distractors) are taken from the other cards in the deck, preferring
cards of the same type, so every option looks plausible.
"""

import random
import re
from dataclasses import dataclass, field

from .parser import shorten

# Answer options longer than this are shortened so they fit on screen.
MAX_OPTION_WORDS = 28


@dataclass
class Question:
    """One quiz question, ready for the quiz screen to display."""
    kind: str                # "mcq" or "tf"
    prompt: str
    options: list
    answer_index: int
    card_id: int = None
    explanation: str = ""
    topic: str = field(default="")


def _points(back):
    """The individual answer snippets on the back of a card."""
    lines = [re.sub(r"^\s*[•\-*]\s*", "", l).strip() for l in back.split("\n")]
    return [l for l in lines if l]


def _clean(text):
    """Collapse whitespace and cap the length of an answer option."""
    return shorten(re.sub(r"\s+", " ", text).strip(), MAX_OPTION_WORDS)


def _same(a, b):
    """True if two options are the same once case and punctuation are ignored."""
    return re.sub(r"\W+", "", a.lower()) == re.sub(r"\W+", "", b.lower())


def _answer_for(card, rng):
    """Pick the text that counts as the correct answer for this card."""
    points = _points(card["back"])
    if not points:
        return None
    # Cards with several key points: any one of them is a correct answer.
    if card["card_type"] in ("essay", "bullets", "quote"):
        return _clean(rng.choice(points))
    # Fill-in-the-blank: the first line on the back is the missing word.
    if card["card_type"] == "cloze":
        return _clean(points[0])
    # Definitions and Q&A: the whole (short) answer.
    return _clean(" ".join(points) if len(points) <= 2 else points[0])


def _topic(card):
    """First line of the front: the heading, term, question or quote."""
    first = next((l for l in card["front"].split("\n") if l.strip()), card["front"])
    return shorten(first.strip(), 35)


def _prompt_for(card):
    """Word the multiple-choice question to suit the card type."""
    front = card["front"].strip()
    kind = card["card_type"]
    if kind == "definition":
        return f"What does “{front}” mean?"
    if kind == "cloze":
        return f"Fill in the blank:\n\n{front}"
    if kind == "quote":
        return f"Which point explains this quote?\n\n{_topic(card)}"
    if kind in ("essay", "bullets"):
        return f"Which of these is a key point about:\n\n{shorten(front.replace(chr(10), ' — '), 35)}"
    return front


def _pool(cards, exclude_id, kind=None):
    """Candidate wrong answers from other cards (optionally only of one card type)."""
    pool = []
    for card in cards:
        if card["id"] == exclude_id or (kind and card["card_type"] != kind):
            continue
        points = _points(card["back"])
        # Use the same "unit" of answer that _answer_for would, so options look alike.
        if card["card_type"] == "cloze":
            points = points[:1]
        elif card["card_type"] in ("definition", "qa", "manual") and len(points) <= 2:
            points = [" ".join(points)]
        pool.extend(_clean(p) for p in points)
    return pool


def _distractors(correct, card, cards, k, rng):
    """Pick `k` wrong answers: same card type first (most convincing), then any other card."""
    same_type = _pool(cards, card["id"], card["card_type"])
    if card["card_type"] == "cloze":
        # Terms from definition cards make good fill-in-the-blank distractors too.
        same_type += [_clean(c["front"]) for c in cards if c["card_type"] == "definition"]
    others = _pool(cards, card["id"])
    own = set(_points(card["back"]))
    chosen = []
    for pool in (same_type, others):
        rng.shuffle(pool)
        for option in pool:
            if len(chosen) == k:
                return chosen
            # Skip anything that's actually right, or a repeat of an option already chosen.
            if option in own or _same(option, correct) or any(_same(option, c) for c in chosen):
                continue
            chosen.append(option)
    return chosen


def make_mcq(card, cards, rng):
    """A 4-option multiple-choice question about `card`, or None if one can't be made."""
    correct = _answer_for(card, rng)
    if not correct:
        return None

    # Definitions are sometimes asked in reverse: show the meaning, pick the term.
    definitions = [c for c in cards if c["card_type"] == "definition" and c["id"] != card["id"]]
    if card["card_type"] == "definition" and len(definitions) >= 2 and rng.random() < 0.4:
        terms = [c["front"] for c in rng.sample(definitions, min(3, len(definitions)))]
        options = terms + [card["front"]]
        rng.shuffle(options)
        return Question(
            "mcq", f"Which term matches this definition?\n\n{_clean(card['back'])}", options,
            options.index(card["front"]), card["id"], f"{card['front']}: {card['back']}", card["front"],
        )

    wrong = _distractors(correct, card, cards, 3, rng)
    if not wrong:
        return None
    # Shuffle so the right answer isn't always in the same place, then remember where it went.
    options = wrong + [correct]
    rng.shuffle(options)
    return Question(
        "mcq", _prompt_for(card), options, options.index(correct), card["id"],
        card["back"], card["front"],
    )


def make_true_false(card, cards, rng):
    """A true/false question: pair the card with its real answer, or with another card's (50/50)."""
    correct = _answer_for(card, rng)
    if not correct:
        return None
    is_true = rng.random() < 0.5
    statement = correct
    # For a "false" statement, borrow a wrong answer; if none exist, fall back to a true one.
    if not is_true:
        wrong = _distractors(correct, card, cards, 1, rng)
        if not wrong:
            is_true = True
        else:
            statement = wrong[0]

    # Word the statement to fit the card type.
    front = _topic(card)
    kind = card["card_type"]
    if kind == "quote":
        prompt = f"True or false? This explains the quote {front}:\n\n{statement}"
    elif kind == "definition":
        prompt = f"True or false?\n\n“{front}” means: {statement}"
    elif kind == "cloze":
        prompt = f"True or false?\n\n“{statement}” fills the blank in:\n{front}"
    elif kind in ("essay", "bullets", "quote"):
        prompt = f"True or false? This is a key point about “{front}”:\n\n{statement}"
    else:
        prompt = f"True or false?\n\n{front}\n→ {statement}"
    options = ["True", "False"]
    return Question("tf", prompt, options, 0 if is_true else 1, card["id"], card["back"], card["front"])


def build_quiz(cards, count=10, kind="mixed", seed=None):
    """Build up to `count` questions. `kind` is "mixed", "mcq" or "tf"."""
    # Database rows are read-only, so copy them into ordinary dicts.
    cards = [dict(c) for c in cards]
    # Wrong answers come from other cards, so one card alone can't make a quiz.
    if len(cards) < 2:
        return []
    # A seeded random generator lets tests get the same quiz every time.
    rng = random.Random(seed)
    order = cards[:]
    rng.shuffle(order)

    # Take cards one at a time until there are enough questions or no cards left.
    questions = []
    while len(questions) < count and order:
        card = order.pop()
        if kind == "mcq":
            question = make_mcq(card, cards, rng)
        elif kind == "tf":
            question = make_true_false(card, cards, rng)
        else:
            # Mixed: about two thirds multiple choice. True/false is the fallback if MCQ fails.
            maker = make_mcq if rng.random() < 0.65 else make_true_false
            question = maker(card, cards, rng) or make_true_false(card, cards, rng)
        if question:
            questions.append(question)
    return questions
