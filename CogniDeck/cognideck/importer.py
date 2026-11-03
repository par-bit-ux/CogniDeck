"""Read notes from files (.txt, .md, .pdf, .docx) and turn them into plain text for the parser.

The parser works on plain text where blank lines separate blocks, headings
start with "#" and bullet points start with "-". PDFs and Word documents don't
store text that way, so this module rebuilds that shape:

    .docx   read straight from the file's XML (a .docx is a zip file), using
            Word's own heading and list styles to mark headings and bullets
    .pdf    text is pulled out page by page with pypdf, then the broken lines
            are "reflowed": wrapped lines are joined back into paragraphs,
            hyphenated words are rejoined and page numbers are dropped.
            Scanned PDFs (typed or handwritten) have no text to pull out, so on
            a Mac their pages are read with Apple's built-in text recognition.

Everything runs offline, like the rest of CogniDeck.
"""

import re
import sys
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .parser import ANSWER_RE, BULLET_RE, QUESTION_RE, _definition

SUPPORTED_TYPES = [
    ("All supported notes", ("*.pdf", "*.docx", "*.txt", "*.md", "*.markdown")),
    ("PDF documents", ("*.pdf",)),
    ("Word documents", ("*.docx",)),
    ("Text notes", ("*.txt", "*.md", "*.markdown")),
]

# Word's XML puts every tag in this namespace, e.g. <w:p> for a paragraph.
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Bullet symbols that PDFs and Word use but the parser doesn't recognise on its own.
BULLET_GLYPHS = "•●○◦▪■□►▸‣∙·–—*-"
GLYPH_BULLET_RE = re.compile(rf"^\s*[{re.escape(BULLET_GLYPHS)}]\s*(\S.*)$")
PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s*)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)
RULE_RE = re.compile(r"^\s*[-_=*~.•·—–]{3,}\s*$")
SENTENCE_END =tuple(".!?:;\"”')")


class FileImportError(Exception):
    """Raised with a student-friendly message when a file can't be turned into notes."""


def import_file(path):
    """Return the notes inside `path` as plain text, ready for parse_notes()."""
    path = Path(path)
    if not path.is_file():
        raise FileImportError(f"Couldn't find {path.name}.")
    # Pick a reader based on the file extension.
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = read_pdf(path)
    elif suffix == ".docx":
        text = read_docx(path)
    elif suffix == ".doc":
        raise FileImportError("Old .doc files aren't supported. Save it as .docx in Word, then open it again.")
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise FileImportError(f"Couldn't open that file: {error}") from error

    text = clean_text(text)
    if not text.strip():
        raise FileImportError("No text was found in that file.")
    return text


def clean_text(text):
    """Normalise odd characters: ligatures like "ﬁ" become "fi", non-breaking spaces become spaces."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("­", "")
    # Collapse runs of 3+ blank lines down to one blank line.
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    return text.strip() + "\n"


# ----- Word (.docx) -------------------------------------------------------------


def read_docx(path):
    """Pull paragraphs, headings, bullet lists and tables out of a .docx file."""
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise FileImportError("That doesn't look like a valid Word (.docx) file.") from error

    body = ElementTree.fromstring(xml).find(f"{W}body")
    items = []
    # The body is a mix of paragraphs (<w:p>) and tables (<w:tbl>), in reading order.
    for element in body if body is not None else []:
        if element.tag == f"{W}p":
            item = _docx_paragraph(element)
            if item:
                items.append(item)
        elif element.tag == f"{W}tbl":
            items.extend(_docx_table(element))
    return assemble(items)


def _docx_text(element):
    """Join the text runs inside a paragraph, turning tabs and line breaks into spaces/newlines."""
    parts = []
    for node in element.iter():
        if node.tag == f"{W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{W}tab":
            parts.append(" ")
        elif node.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _docx_paragraph(paragraph):
    """Classify one Word paragraph as a heading, bullet or plain paragraph using its style."""
    text = _docx_text(paragraph)
    if not text:
        return None
    props = paragraph.find(f"{W}pPr")
    style = ""
    is_list = False
    if props is not None:
        style_tag = props.find(f"{W}pStyle")
        style = (style_tag.get(f"{W}val") or "").lower() if style_tag is not None else ""
        # <w:numPr> means Word is numbering or bulleting this paragraph.
        is_list = props.find(f"{W}numPr") is not None
    if style.startswith(("heading", "title", "subtitle")):
        return ("heading", text)
    if is_list or "list" in style:
        return ("bullet", text)
    return ("para", text)


def _docx_table(table):
    """Two-column tables become "Term: meaning" lines (great for glossaries); wider ones are joined with semicolons."""
    items = []
    for row in table.iter(f"{W}tr"):
        cells = [_docx_text(cell).replace("\n", " ") for cell in row.iter(f"{W}tc")]
        cells = [c for c in cells if c]
        if len(cells) == 2:
            items.append(("line", f"{cells[0]}: {cells[1]}"))
        elif cells:
            items.append(("line", "; ".join(cells)))
    return items


# ----- PDF ----------------------------------------------------------------------


def read_pdf(path):
    """Extract the text of every page and reflow it into paragraphs.

    PDFs with a text layer are read with pypdf. Scanned PDFs (photos or scans of
    typed or handwritten pages) have no text layer, so on a Mac they are read with
    Apple's built-in text recognition instead, which also runs offline.
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as error:
        raise FileImportError("PDF support needs the pypdf package: run  pip install -r requirements.txt") from error

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # Many PDFs are "encrypted" with an empty password just to block editing.
            reader.decrypt("")
        pages = [_page_text(page) for page in reader.pages]
    except (OSError, PdfReadError, ValueError) as error:
        raise FileImportError(f"Couldn't read that PDF: {error}") from error
    except Exception as error:  # pypdf can raise many internal errors on damaged files
        raise FileImportError("That PDF couldn't be read. It may be damaged or password-protected.") from error

    if sum(len(p.split()) for p in pages) < 5 * max(1, len(pages)):
        # Almost no text layer: it's a scan, so read the page images instead.
        return assemble(reflow_lines(ocr_pdf(path)))

    # Pages are reflowed together so a paragraph that runs onto the next page stays in one piece.
    lines = [line for page in pages for line in page.split("\n")]
    return assemble(reflow_lines(lines))


# Short words that are real English, so they don't count as "broken word" fragments.
_SHORT_WORDS = set("a i am an as at be by do go he if in is it me my no of oh on or ok so to up us we".split())


def _text_quality(text):
    """Score extracted text: lower when words are glued together, split into fragments,
    or scattered one per line. Used to choose between pypdf's two extraction modes."""
    tokens = text.split()
    if not tokens:
        return float("-inf")
    words = [t.strip(".,;:!?\"'“”‘’()[]") for t in tokens]
    glued = sum(len(w) >= 20 for w in words) / len(words)
    fragments = sum(1 for w in words if 0 < len(w) <= 2 and w.isalpha() and w.lower() not in _SHORT_WORDS) / len(words)
    lines = [l for l in text.split("\n") if l.strip()]
    single = sum(len(l.split()) == 1 for l in lines) / len(lines)
    return -(3 * glued + 3 * fragments + single)


def _page_text(page):
    """Get one page's text with its real line breaks.

    pypdf has two ways to read a page and each fails on different PDFs:
    - the default mode breaks Google Docs exports (which store every word separately)
      into one word per line, sometimes losing the spaces between words
    - layout mode places words by their position, which fixes that, but on PDFs with
      unusual letter spacing it splits words apart ("Assess ment")
    So read the page both ways and keep whichever looks more like normal writing.
    """
    candidates = []
    for mode in ("plain", "layout"):
        try:
            text = page.extract_text(extraction_mode=mode) or ""
        except Exception:
            continue
        if text.strip():
            candidates.append(text)
    return max(candidates, key=_text_quality) if candidates else ""


# ----- scanned PDFs (text recognition) ---------------------------------------------


def ocr_pdf(path):
    """Read a scanned PDF with macOS text recognition. Returns lines, with "" between paragraphs."""
    if sys.platform != "darwin":
        raise FileImportError(
            "This PDF is a scan with no selectable text. Reading scans needs macOS text recognition, "
            "which isn't available on this computer."
        )
    try:
        import pypdfium2 as pdfium
        from ocrmac import ocrmac
    except ImportError as error:
        raise FileImportError(
            "This PDF is a scan. Reading scans needs two extra packages: run  pip install -r requirements.txt"
        ) from error

    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as error:
        raise FileImportError("That PDF couldn't be opened for text recognition.") from error

    lines = []
    for page in document:
        image = page.render(scale=250 / 72).to_pil()
        boxes = _recognise(ocrmac, image)
        lines.extend(_boxes_to_lines(boxes))
        lines.append("")
    if not any(lines):
        raise FileImportError("No text could be recognised in this scanned PDF.")
    return lines


def _recognise(ocrmac, image):
    """Run text recognition on one page image.

    Live Text (macOS 14+) reads handwriting far better and returns one box per word;
    older Macs fall back to the Vision engine, which returns one box per line.
    """
    try:
        return ocrmac.OCR(image, framework="livetext", language_preference=["en-US"]).recognize()
    except Exception:
        return ocrmac.OCR(image, recognition_level="accurate", language_preference=["en-US"]).recognize()


def _line_pitch(words):
    """The usual distance between one line and the next, measured from words stacked
    above each other. Word boxes in handwriting are taller than the line spacing,
    so box height alone would merge neighbouring lines."""
    distances = []
    for word in words:
        below = [
            other["mid"] - word["mid"]
            for other in words
            if other["mid"] > word["mid"] + 0.004 and other["x"] < word["right"] and other["right"] > word["x"]
        ]
        if below:
            distances.append(min(below))
    if not distances:
        return sorted(w["h"] for w in words)[len(words) // 2]
    distances.sort()
    return distances[len(distances) // 2]


def _boxes_to_lines(boxes):
    """Turn recognised word boxes into lines of text, with "" marking paragraph breaks.

    Each box is (text, confidence, [x, y, width, height]) in 0–1 page units with the
    origin at the bottom-left. Words are grouped into lines by their height on the page
    (handwriting slopes, so each word is compared with the one before it), then a
    bigger-than-usual gap between lines, or a short line ending a sentence, starts a
    new paragraph.
    """
    words = []
    for text, _confidence, (x, y, w, h) in boxes:
        text = text.strip()
        # Skip empty boxes and scribbles misread as non-Latin letters (e.g. "も" or "Деонс").
        if text and all(ord(c) < 0x250 or c in "“”‘’—–…" for c in text):
            words.append({"text": text, "x": x, "right": x + w, "mid": 1 - (y + h / 2), "h": h})
    if not words:
        return []

    tolerance = _line_pitch(words) * 0.45

    # Follow each handwritten line from left to right: a word joins the line whose most
    # recent word sits closest to its height, so sloping lines don't merge into each other.
    rows = []
    for word in sorted(words, key=lambda w: w["x"]):
        best, best_distance = None, tolerance
        for row in rows:
            distance = abs(word["mid"] - row[-1]["mid"])
            if distance <= best_distance and row[-1]["x"] < word["x"]:
                best, best_distance = row, distance
        if best is None:
            rows.append([word])
        else:
            best.append(word)
    rows.sort(key=lambda row: sum(w["mid"] for w in row) / len(row))
    # Rejoin pieces of the same line that were split by a big gap or a crossed-out word.
    merged = []
    for row in rows:
        prev = merged[-1] if merged else None
        if prev and abs(prev[-1]["mid"] - row[0]["mid"]) <= tolerance and prev[-1]["x"] < row[0]["x"]:
            prev.extend(row)
        else:
            merged.append(row)
    rows = merged

    lines = []
    for row in rows:
        lines.append({
            "text": _tidy_spacing(" ".join(w["text"] for w in row)),
            "mid": sum(w["mid"] for w in row) / len(row),
            "left": row[0]["x"],
            "right": row[-1]["right"],
        })

    gaps = sorted(b["mid"] - a["mid"] for a, b in zip(lines, lines[1:]))
    usual_gap = gaps[len(gaps) // 2] if gaps else 0
    usual_right = sorted(l["right"] for l in lines)[int(len(lines) * 0.8)]

    out, paragraph = [], []
    for i, line in enumerate(lines):
        paragraph.append(line["text"])
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        big_gap = nxt is not None and usual_gap and nxt["mid"] - line["mid"] > usual_gap * 1.4
        short_end = line["text"].endswith((".", "!", "?", "\"", "”")) and line["right"] < usual_right - 0.2
        if nxt is None or big_gap or short_end:
            # Write the paragraph as one long line so the reflow step keeps it together.
            out.append(" ".join(paragraph))
            out.append("")
            paragraph = []
    return out


def reflow_lines(lines):
    """Rebuild paragraphs from the hard-wrapped lines a PDF gives back.

    Returns a list of (kind, text) items like read_docx does. The rules:
    - bullets, "Q:"/"A:" lines and "Term: meaning" lines always start a new item
    - a short line with no closing punctuation, after a finished sentence, is a heading
    - a line continues the previous paragraph unless that one ended a sentence
      on a noticeably short line (the last line of a paragraph is usually short)
    """
    lines = [_tidy_spacing(re.sub(r"\s+", " ", l)).strip() for l in lines]
    lines = [l for l in lines if not PAGE_NUMBER_RE.match(l)]
    # Divider lines ("-----", "_____", "*****") separate sections, so treat them as blank lines.
    lines = ["" if RULE_RE.match(l) else l for l in lines]
    widths = sorted(len(l) for l in lines if l)
    if not widths:
        return []
    # A "full" line is about as long as the longer lines on the page.
    full_width = widths[int(len(widths) * 0.8)]

    items, previous = [], ""
    for line in lines:
        if not line:
            # A real blank line in the PDF always ends the paragraph.
            if items and items[-1][0] != "break":
                items.append(("break", ""))
            previous = ""
            continue

        glyph = GLYPH_BULLET_RE.match(line)
        numbered = BULLET_RE.match(line)
        # Text only wraps onto the next line when a line is full, so a short line means
        # the paragraph (or bullet, or heading) stopped there.
        finished = previous.endswith(SENTENCE_END)
        para_ended = not previous or len(previous) < full_width * 0.75
        last = items[-1] if items else None
        definition = _definition(line)

        if glyph or numbered:
            items.append(("bullet", (glyph or numbered).group(1).strip()))
        elif QUESTION_RE.match(line) or ANSWER_RE.match(line):
            items.append(("qa", line))
        elif (finished or para_ended) and _looks_like_heading(line) and (not definition or _title_case(line)):
            # "Macbeth: Fatal Flaw" is a heading, "Hamartia: the fatal flaw" is a definition.
            items.append(("heading", line.rstrip(":")))
        elif definition and (para_ended or (last and last[0] == "line")):
            # Glossary lines follow each other, so one definition right after another starts a new line.
            items.append(("line", line))
        elif last and last[0] in ("para", "bullet", "line", "qa") and not para_ended:
            # Wrapped line: glue it back on, rejoining words split with a hyphen.
            text = last[1]
            if re.search(r"[A-Za-z]-$", text) and line[:1].islower():
                text = text[:-1] + line
            else:
                text = f"{text} {line}"
            items[-1] = (last[0], text)
        else:
            items.append(("para", line))
        previous = line
    return [item for item in items if item[0] != "break"]


def _tidy_spacing(line):
    """Remove the stray spaces some PDFs put inside punctuation: "word ," → "word,", "“ quote ”" → "“quote”"."""
    line = re.sub(r"(?<=\S) +([,.;:!?)\]”])", r"\1", line)
    return re.sub(r"([(\[“]) +(?=\S)", r"\1", line)


def _looks_like_heading(line):
    """Short, title-like lines with no sentence punctuation (e.g. "Blood Motif" or "Key terms:")."""
    words = line.split()
    if not 1 <= len(words) <= 8 or line.endswith((".", "!", "?", ",", ";")):
        return False
    return line[0].isupper() or line[0].isdigit()


def _title_case(line):
    """True when every longer word is capitalised, as in a title ("Macbeth: Fatal Flaw")."""
    words = [w for w in re.findall(r"[A-Za-z][\w'’-]*", line) if len(w) > 3]
    return bool(words) and all(w[0].isupper() for w in words)


# ----- shared: items → parser-friendly text ---------------------------------------


def assemble(items):
    """Write (kind, text) items out in the format the parser understands.

    Headings become "# Heading" with a blank line before them, bullets become
    "- point", and consecutive bullets or structured lines (definitions, Q&A)
    are kept together in one block so the parser sees them as a group.
    """
    out, previous = [], None
    for kind, text in items:
        text = text.strip()
        if not text:
            continue
        if kind == "heading":
            out.append("")
            out.append(f"# {text}")
        elif kind == "bullet":
            # Bullets stay attached to the heading or bullets right above them.
            if previous not in ("heading", "bullet"):
                out.append("")
            out.append(f"- {text}")
        elif kind in ("line", "qa"):
            # Definitions group with definitions and Q&A with Q&A, never with each other,
            # otherwise the parser would treat a whole glossary as one long question.
            if previous not in ("heading", kind):
                out.append("")
            out.append(text)
        else:
            # A paragraph after a heading belongs to that heading; otherwise it's a new block.
            if previous != "heading":
                out.append("")
            out.append(text)
        previous = kind
    return "\n".join(out).strip() + "\n"
