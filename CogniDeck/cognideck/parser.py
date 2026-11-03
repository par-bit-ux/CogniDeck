"""Offline, rule-based note parser (no cloud AI).

Raw notes are split into blocks at blank lines. Each block is parsed with one
strategy, either the one the student picked or, in "auto" mode, the one that
best fits the block's shape:

    qa           "Q: ... / A: ..." pairs, or a line ending in "?" followed by its answer
    definitions  "Term: meaning", "Term - meaning" or "Term = meaning" lines
    bullets      a heading followed by bullet points
    essay        prose paragraphs, broken down into a topic sentence + key points
    cloze        fill-in-the-blank cards made from the most important sentences

Essay key points are chosen by scoring each sentence: how many of the
paragraph's frequent content words it contains, signal words that mark
analysis ("shows", "because", "symbolises"), quotations and numbers.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

# Parsing modes: internal key → the label shown in the "Turn notes into" dropdown.
MODES = {
    "auto": "Auto-detect (mixed notes)",
    "essay": "Essay → key points",
    "definitions": "Definitions / glossary",
    "qa": "Questions & answers",
    "bullets": "Headings & bullet points",
    "cloze": "Fill in the blank",
}

# How each card type is named on the card itself (singular) and in summaries (plural).
CARD_TYPE_LABELS = {
    "essay": "Key points",
    "quote": "Quote analysis",
    "definition": "Definition",
    "qa": "Question",
    "bullets": "Topic",
    "cloze": "Fill in the blank",
    "manual": "Card",
}

CARD_TYPE_PLURALS = {
    "essay": "key-point cards",
    "quote": "quote analyses",
    "definition": "definitions",
    "qa": "questions",
    "bullets": "topics",
    "cloze": "fill-in-the-blanks",
    "manual": "cards",
}

# Common words that carry no meaning on their own. They're ignored when
# working out which words a paragraph is "about".
STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each even ever every few for from further
had has have having he her here hers herself him himself his how however i if in into is it its itself
just like made make many may me might more most much must my myself no nor not now of off on once one
only or other our ours ourselves out over own same shall she should so some such than that the their
theirs them themselves then there these they this those through thus to too under until up upon us
very was we were what when where which while who whom whose why will with within without would yet you
your yours yourself yourselves s t don t also really quite rather often
""".split())

# Words that usually mark analysis or an important point. Sentences containing
# them score higher when choosing key points.
SIGNAL_WORDS = {
    "because", "therefore", "thus", "hence", "consequently", "shows", "show", "showing", "suggests",
    "suggest", "reveals", "reveal", "highlights", "demonstrates", "represents", "symbolises",
    "symbolizes", "emphasises", "emphasizes", "illustrates", "conveys", "reflects", "means",
    "causes", "leads", "results", "ultimately", "key", "important", "significant", "main",
    "theme", "motif", "irony", "flaw", "contrast", "foreshadows", "foreshadowing", "defined",
}

# Linking phrases at the start of a sentence ("Furthermore, ...") that add
# nothing on a flashcard, so they're trimmed off key points.
LEADING_FILLERS = re.compile(
    r"^(furthermore|moreover|in addition|additionally|also|however|similarly|likewise|"
    r"firstly|secondly|thirdly|finally|lastly|overall|in conclusion|to conclude|"
    r"for example|for instance|as a result|in other words|on the other hand)\s*,?\s+",
    re.IGNORECASE,
)

# Regular expressions that recognise the shape of a line:
#   BULLET_RE      "- point", "• point", "1. point" or "2) point"
#   QUESTION_RE    "Q: ..." / "Question 3: ..."      ANSWER_RE  "A: ..." / "Answer: ..."
#   DEFINITION_RE  "Term: meaning", "Term = meaning" or "Term - meaning"
#   HEADING_RE     "# Markdown heading" or a short line ending in a colon
#   QUOTE_RE       text inside straight or curly double quotes
BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦‣–]|\d{1,2}[.)])\s+(.*)$")
QUESTION_RE = re.compile(r"^\s*(?:Q|Question)\s*\d*\s*[:.)\-]\s*(.+)$", re.IGNORECASE)
ANSWER_RE = re.compile(r"^\s*(?:A|Ans|Answer)\s*\d*\s*[:.)\-]\s*(.+)$", re.IGNORECASE)
DEFINITION_RE = re.compile(
    r"^\s*(?:[-*•▪◦‣]\s*)?(?P<term>[^:=\n]{1,60}?)\s*(?::|=|\s[-–—]\s)\s*(?P<meaning>\S.*)$"
)
HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s*(?P<md>.+?)|(?P<colon>[^.!?]{2,70}):)\s*$")
QUOTE_RE = re.compile(r"[\"“]([^\"”]{8,160})[\"”]")
# Splits after . ! or ? when the next sentence starts with a capital letter or number.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])[\"”')\]]?\s+(?=[\"“'(\[]?[A-Z0-9])")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")

# Length caps so cards stay readable at a glance.
MAX_FRONT_WORDS = 40
MAX_POINT_WORDS = 32


@dataclass
class Card:
    """One flashcard produced by the parser (before it's saved to the database)."""
    front: str
    back: str
    card_type: str


# ----- text helpers ----------------------------------------------------------


def split_blocks(text):
    """Split notes into blocks at blank lines, keeping each block's lines."""
    blocks, current = [], []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip():
            current.append(line.rstrip())
        elif current:
            # A blank line closes the current block.
            blocks.append(current)
            current = []
    # Don't forget the last block if the notes don't end with a blank line.
    if current:
        blocks.append(current)
    return blocks


def split_sentences(text):
    """Break a paragraph into sentences (whitespace is tidied first)."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]


def content_words(text):
    """The meaningful words in `text`: lower-cased, no stopwords, at least 3 letters."""
    return [w.lower().strip("'’-") for w in WORD_RE.findall(text) if w.lower() not in STOPWORDS and len(w) > 2]


def shorten(text, max_words):
    """Cut `text` to `max_words` words, adding "…" if anything was removed."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).rstrip(",;:") + "…"


def compress_point(sentence):
    """Turn a sentence into a tighter key point: drop linking fillers, cap the length."""
    point = LEADING_FILLERS.sub("", sentence.strip())
    point = point[:1].upper() + point[1:]
    return shorten(point, MAX_POINT_WORDS)


def as_bullets(points):
    """Format a list of points as "• point" lines for the back of a card."""
    return "\n".join(f"• {p}" for p in points if p)


def _is_heading(line):
    """True for "# Heading" or "Heading:" lines (but not for a bullet that ends in a colon)."""
    return bool(HEADING_RE.match(line)) and not BULLET_RE.match(line)


def _heading_text(line):
    """The heading's words without the "#" or trailing colon."""
    match = HEADING_RE.match(line)
    return (match.group("md") or match.group("colon")).strip()


def _definition(line):
    """Return (term, meaning) if the line looks like a glossary entry, otherwise None."""
    match = DEFINITION_RE.match(line)
    if not match:
        return None
    term, meaning = match.group("term").strip(), match.group("meaning").strip()
    # "Q: ..." and "A: ..." also contain a colon, but they're not definitions.
    if QUESTION_RE.match(line) or ANSWER_RE.match(line):
        return None
    # A real term is short and isn't a question; a real meaning is more than one word.
    if len(term.split()) > 6 or term.endswith("?") or len(meaning.split()) < 2:
        return None
    return term.strip("*_ "), meaning


# ----- strategies --------------------------------------------------------------


def parse_qa(lines):
    """Turn "Q: ... / A: ..." pairs (or a "...?" line followed by its answer) into question cards."""
    cards, question, answer = [], None, []

    def flush():
        # Save the question collected so far, as long as it has an answer.
        if question and answer:
            cards.append(Card(question, " ".join(answer), "qa"))

    for line in lines:
        q, a = QUESTION_RE.match(line), ANSWER_RE.match(line)
        bullet = BULLET_RE.match(line)
        text = bullet.group(1) if bullet else line.strip()
        if q:
            # "Q:" starts a new question.
            flush()
            question, answer = q.group(1).strip(), []
        elif a:
            # "A:" adds to the current answer.
            answer.append(a.group(1).strip())
        elif text.endswith("?") and (question is None or answer):
            # An unlabelled line ending in "?" also starts a new question.
            flush()
            question, answer = text, []
        elif question is not None:
            # Any other line is more of the answer.
            answer.append(text)
    flush()

    # Answers with several lines read better as bullet points.
    for card in cards:
        parts = [p for p in re.split(r"\s*;\s*", card.back) if p]
        if len(parts) > 1:
            card.back = as_bullets(parts)
    return cards


def parse_definitions(lines):
    """One card per "Term: meaning" line; the term goes on the front, the meaning on the back."""
    cards = []
    for line in lines:
        found = _definition(line)
        if found:
            term, meaning = found
            cards.append(Card(term, meaning, "definition"))
        elif cards and not _is_heading(line):
            # Continuation of the previous definition.
            extra = BULLET_RE.match(line)
            cards[-1].back += " " + (extra.group(1) if extra else line.strip())
    return cards


def parse_bullets(lines, heading=None):
    """A heading (or the given one) followed by bullets becomes one card per heading."""
    cards, title, points = [], heading, []

    def flush():
        if points:
            front = title or "Recall the points in this list"
            cards.append(Card(front, as_bullets(compress_point(p) for p in points), "bullets"))

    for line in lines:
        bullet = BULLET_RE.match(line)
        if bullet:
            points.append(bullet.group(1).strip())
        elif _is_heading(line) or (not points and len(line.split()) <= 10):
            # A new heading (or a short line before any bullets) starts a new card.
            flush()
            title, points = _heading_text(line) if _is_heading(line) else line.strip(), []
        elif points:
            # A wrapped line belongs to the bullet above it.
            points[-1] += " " + line.strip()
        else:
            points.append(line.strip())
    flush()
    return cards


def _score_sentences(sentences, doc_freq):
    """Score sentences by keyword density, analysis signal words, quotes and numbers."""
    # How often each content word appears in this paragraph.
    para_freq = Counter(w for s in sentences for w in content_words(s))
    scores = []
    for index, sentence in enumerate(sentences):
        words = content_words(sentence)
        if not words:
            scores.append(0.0)
            continue
        # Keyword score: words that repeat across the paragraph (and the whole document)
        # suggest the sentence is on-topic. Dividing by √length stops long sentences winning by default.
        keyword = sum(para_freq[w] + 0.5 * doc_freq.get(w, 0) for w in words) / math.sqrt(len(words))
        signals = sum(1 for w in WORD_RE.findall(sentence.lower()) if w in SIGNAL_WORDS)
        bonus = 1.5 * signals
        bonus += 2.0 if QUOTE_RE.search(sentence) else 0.0
        bonus += 0.5 if re.search(r"\d", sentence) else 0.0
        bonus -= 1.0 if len(words) < 3 else 0.0
        bonus += 0.5 if index == len(sentences) - 1 else 0.0  # concluding sentences often sum up
        scores.append(keyword + bonus)
    return scores


def parse_essay(lines, doc_freq=None, heading=None, used=None):
    """Break prose into cards: topic sentence on the front, key points on the back.

    Quotations inside the prose also become their own "what does this quote show?" cards.
    """
    paragraph = " ".join(line.strip() for line in lines)
    sentences = split_sentences(paragraph)
    doc_freq = doc_freq or Counter(content_words(paragraph))
    cards = []

    if len(sentences) == 1:
        return parse_cloze(lines, doc_freq, used=used)

    # Long paragraphs are split into chunks so each card stays digestible.
    chunk_size = 6
    chunks = [sentences[i:i + chunk_size] for i in range(0, len(sentences), chunk_size)]
    if len(chunks) > 1 and len(chunks[-1]) < 3:
        chunks[-2].extend(chunks.pop())

    for chunk in chunks:
        # The first sentence of a paragraph is usually its topic sentence.
        topic, rest = chunk[0], chunk[1:]
        if not rest:
            continue
        # Keep the best 2–4 of the remaining sentences (about 60%), in their original order.
        scores = _score_sentences(rest, doc_freq)
        keep = min(len(rest), max(2, math.ceil(len(rest) * 0.6)), 4)
        best = sorted(range(len(rest)), key=lambda i: scores[i], reverse=True)[:keep]
        points = [compress_point(rest[i]) for i in sorted(best)]
        front = shorten(topic, MAX_FRONT_WORDS)
        # Put the section heading above the topic sentence for context.
        if heading and heading.lower() not in front.lower():
            front = f"{heading}\n\n{front}"
        cards.append(Card(front, as_bullets(points), "essay"))

    # Second pass: every quotation becomes a "what does this show?" card.
    for index, sentence in enumerate(sentences):
        for quote in QUOTE_RE.findall(sentence):
            # Skip one-word "quotes", which are usually just emphasis.
            if len(quote.split()) < 2:
                continue
            explanation = [sentence]
            # The sentence after a quote usually analyses it.
            if index + 1 < len(sentences) and any(
                w in SIGNAL_WORDS for w in WORD_RE.findall(sentences[index + 1].lower())
            ):
                explanation.append(sentences[index + 1])
            cards.append(
                Card(f"“{quote.strip()}”\n\nWhat does this quote show?",
                     as_bullets(compress_point(e) for e in explanation), "quote")
            )
    return cards


def _cloze_target(sentence, doc_freq, used=()):
    """Pick the word or name to blank out: proper nouns and frequent content words win,
    and answers already used on other cards are avoided so the deck has variety."""
    tokens = list(WORD_RE.finditer(sentence))
    best, best_score = None, 0.0
    for i, match in enumerate(tokens):
        word = match.group(0).strip("'’-")
        lower = word.lower()
        if lower in STOPWORDS or len(word) < 4:
            continue
        # Frequent and longer words make better blanks.
        score = doc_freq.get(lower, 0) + len(word) / 4
        # Capitalised mid-sentence means a name or place: great for recall.
        if word[0].isupper() and i > 0:
            score += 2.5
        # Words like "shows" or "because" are too vague to test.
        if lower in SIGNAL_WORDS:
            score -= 2
        # Avoid blanking the same answer on several cards.
        if lower in used:
            score *= 0.2
        if score > best_score:
            best, best_score = match, score
    if not best:
        return None
    # Extend to a multi-word proper noun such as "Lady Macbeth".
    start, end = best.start(), best.end()
    if sentence[start].isupper():
        for match in tokens:
            if match.start() == end + 1 and match.group(0)[0].isupper():
                end = match.end()
        for match in reversed(tokens):
            word = match.group(0)
            if match.end() == start - 1 and word[0].isupper() and word.lower() not in STOPWORDS:
                start = match.start()
    return start, end


def _cloze_lines(lines):
    """Strip headings, bullet markers and Q/A labels so every line reads as a sentence."""
    cleaned = []
    for line in lines:
        if _is_heading(line):
            continue
        match = BULLET_RE.match(line) or QUESTION_RE.match(line) or ANSWER_RE.match(line)
        text = (match.group(1) if match else line).strip()
        if text and text[-1] not in ".!?\"”'":
            text += "."
        cleaned.append(text)
    return cleaned


def parse_cloze(lines, doc_freq=None, per_block=3, used=None):
    """Make up to `per_block` fill-in-the-blank cards from the block's most important sentences."""
    cards, prose = [], []
    for line in lines:
        found = None if _is_heading(line) or len(line.split()) > 30 else _definition(line)
        if found:
            # For glossary lines, the term itself is the blank.
            term, meaning = found
            cards.append(Card(f"_____: {meaning}", f"{term}\n\n{term}: {meaning}", "cloze"))
        else:
            prose.append(line)

    # Rank the prose sentences with the same scoring used for essay key points.
    text = " ".join(_cloze_lines(prose))
    sentences = split_sentences(text)
    doc_freq = doc_freq or Counter(content_words(text))
    used = set() if used is None else used
    scores = _score_sentences(sentences, doc_freq)
    ranked = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)
    for i in sorted(ranked[:per_block]):
        sentence = shorten(sentences[i], MAX_FRONT_WORDS)
        # Very short sentences don't give enough context to guess the blank.
        if len(sentence.split()) < 5:
            continue
        target = _cloze_target(sentence, doc_freq, used)
        if not target:
            continue
        # Swap the chosen word(s) for a blank; the back shows the answer and the full sentence.
        start, end = target
        answer = sentence[start:end]
        used.update(w.lower() for w in WORD_RE.findall(answer))
        front = sentence[:start] + "_____" + sentence[end:]
        cards.append(Card(front, f"{answer}\n\n{sentence}", "cloze"))
    return cards


# ----- classification ----------------------------------------------------------


def classify_block(lines):
    """Guess which strategy fits a block of lines."""
    n = len(lines)
    # Any Q:/A: label, or a block that opens with a question, is Q&A.
    if any(QUESTION_RE.match(l) or ANSWER_RE.match(l) for l in lines):
        return "qa"
    if n >= 2 and lines[0].strip().endswith("?") and not BULLET_RE.match(lines[0]):
        return "qa"
    # A heading on its own applies to the block after it.
    if n == 1 and _is_heading(lines[0]):
        return "heading"

    # Mostly "Term: meaning" lines (and no long prose lines) means a glossary.
    body = lines[1:] if _is_heading(lines[0]) else lines
    definitions = sum(1 for l in body if _definition(l))
    long_lines = sum(1 for l in body if len(l.split()) > 30)
    if body and definitions >= max(1, math.ceil(len(body) * 0.6)) and long_lines == 0:
        return "definitions"

    # All bullets (allowing one heading line) means a bullet list.
    bullets = sum(1 for l in lines if BULLET_RE.match(l))
    if bullets and bullets >= n - 1:
        return "bullets"
    # Anything else is treated as prose.
    return "essay"


def parse_notes(text, mode="auto"):
    """Parse raw notes into a list of Cards using `mode` (see MODES)."""
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")
    blocks = split_blocks(text)
    # Word counts across the whole document help decide which sentences matter most.
    doc_freq = Counter(content_words(text))
    # `heading` carries a heading-only block over to the block after it;
    # `used` stops fill-in-the-blank cards repeating the same answer.
    cards, heading, used = [], None, set()

    # In auto mode, an answer separated from its question by a blank line rejoins it.
    if mode in ("auto", "qa"):
        merged = []
        for block in blocks:
            if merged and ANSWER_RE.match(block[0]) and classify_block(merged[-1]) == "qa":
                merged[-1] = merged[-1] + block
            else:
                merged.append(block)
        blocks = merged

    for block in blocks:
        # Auto mode picks a strategy per block; other modes force one for everything.
        kind = classify_block(block) if mode == "auto" else mode
        if kind == "heading":
            heading = _heading_text(block[0])
            continue
        if mode != "auto" and len(block) == 1 and _is_heading(block[0]) and kind != "definitions":
            heading = _heading_text(block[0])
            continue
        if kind == "qa":
            new = parse_qa(block)
        elif kind == "definitions":
            new = parse_definitions(block)
        elif kind == "bullets":
            new = parse_bullets(block, heading)
        elif kind == "cloze":
            new = parse_cloze(block, doc_freq, used=used)
        else:
            # Essay: if the block starts with its own heading, split it off and pass it along.
            body = block[1:] if _is_heading(block[0]) and len(block) > 1 else block
            block_heading = _heading_text(block[0]) if body is not block else heading
            new = parse_essay(body, doc_freq, block_heading, used)
        cards.extend(new)
        heading = None

    return dedupe(cards)


def dedupe(cards):
    """Drop cards with an empty back or the same front as an earlier card (ignoring punctuation)."""
    seen, unique = set(), []
    for card in cards:
        key = re.sub(r"\W+", " ", card.front.lower()).strip()
        if key and key not in seen and card.back.strip():
            seen.add(key)
            unique.append(card)
    return unique


def summarise(cards):
    """Human-readable breakdown, e.g. '12 cards: 4 definitions, 3 questions'."""
    if not cards:
        return "No cards found. Try another parsing mode or add more detail to your notes."
    counts = Counter(c.card_type for c in cards)
    parts = ", ".join(
        f"{n} {CARD_TYPE_PLURALS.get(kind, kind) if n > 1 else CARD_TYPE_LABELS.get(kind, kind).lower()}"
        for kind, n in counts.most_common()
    )
    return f"{len(cards)} cards: {parts}"
