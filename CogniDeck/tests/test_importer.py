"""Tests for importing notes from Word (.docx) and PDF files.

The test files are generated on the fly, so no sample documents need to be stored in the project.
"""

import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

from cognideck.importer import FileImportError, assemble, import_file, reflow_lines
from cognideck.parser import parse_notes, summarise
from cognideck.sample_notes import MACBETH_NOTES

# ----- helpers that build small test files on the fly -------------------------------

DOCX_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx_paragraph(text, style=None, numbered=False):
    props = ""
    if style or numbered:
        props = "<w:pPr>"
        props += f'<w:pStyle w:val="{style}"/>' if style else ""
        props += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if numbered else ""
        props += "</w:pPr>"
    return f"<w:p>{props}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def make_docx(path, body_xml):
    """Write a minimal but valid .docx: a zip holding word/document.xml."""
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document {DOCX_NS}><w:body>{body_xml}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        archive.writestr("word/document.xml", document)


def make_pdf(path, lines):
    """Write a one-page PDF with each string in `lines` on its own line (Helvetica, 12pt)."""
    escaped = [l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for l in lines]
    stream = "BT /F1 12 Tf 14 TL 50 780 Td " + " ".join(f"({l}) Tj T*" for l in escaped) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    Path(path).write_bytes(out.encode("latin-1"))


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ----- Word -----------------------------------------------------------------

    def test_docx_headings_bullets_and_tables(self):
        body = (
            _docx_paragraph("Blood Motif", style="Heading1")
            + _docx_paragraph("Blood symbolises guilt", numbered=True)
            + _docx_paragraph("Early on it represents honour", numbered=True)
            + "<w:tbl><w:tr><w:tc>" + _docx_paragraph("Hamartia") + "</w:tc><w:tc>"
            + _docx_paragraph("the fatal flaw of a tragic hero") + "</w:tc></w:tr></w:tbl>"
        )
        path = self.dir / "notes.docx"
        make_docx(path, body)
        text = import_file(path)
        self.assertIn("# Blood Motif\n- Blood symbolises guilt\n- Early on it represents honour", text)
        self.assertIn("Hamartia: the fatal flaw of a tragic hero", text)

        cards = parse_notes(text)
        self.assertEqual({c.card_type for c in cards}, {"bullets", "definition"})

    def test_bad_docx_gives_friendly_error(self):
        path = self.dir / "broken.docx"
        path.write_text("not a zip file")
        with self.assertRaises(FileImportError):
            import_file(path)

    # ----- PDF ------------------------------------------------------------------

    def test_pdf_text_is_extracted_and_parsed(self):
        path = self.dir / "notes.pdf"
        make_pdf(path, [
            "Key terms:",
            "Hamartia: the fatal flaw that leads to a tragic hero's downfall",
            "Motif: a recurring image or idea that develops a theme",
            "",
            "Q: Who kills Duncan?",
            "A: Macbeth, while Duncan sleeps.",
        ])
        text = import_file(path)
        cards = parse_notes(text)
        fronts = [c.front for c in cards]
        self.assertIn("Hamartia", fronts)
        self.assertIn("Who kills Duncan?", fronts)

    def test_wrapped_sample_notes_pdf_gives_same_deck(self):
        # Turn the sample notes into a PDF the way a word processor would: headings
        # without "#", bullet glyphs, and every paragraph hard-wrapped at 80 characters.
        lines = []
        for line in MACBETH_NOTES.splitlines():
            if line.startswith("# "):
                line = line[2:]
            elif line.startswith("- "):
                line = "\x95 " + line[2:]  # \x95 is the bullet character in PDF's WinAnsi encoding
            line = line.replace("’", "'").replace("“", '"').replace("”", '"')
            lines += textwrap.wrap(line, 80) or [""]
        path = self.dir / "macbeth.pdf"
        make_pdf(path, lines)
        self.assertEqual(summarise(parse_notes(import_file(path))), summarise(parse_notes(MACBETH_NOTES)))

    def test_empty_pdf_explains_it_may_be_scanned(self):
        path = self.dir / "scan.pdf"
        make_pdf(path, [])
        with self.assertRaisesRegex(FileImportError, "scanned"):
            import_file(path)

    # ----- reflowing PDF lines -----------------------------------------------------

    def test_reflow_joins_wrapped_lines_and_hyphens(self):
        lines = [
            "Macbeth's fatal flaw is his vaulting ambition, which turns a loyal sol-",
            "dier into a tyrant. The witches' prophecy awakens a desire for power that",
            "he cannot control.",
            "12",
            "Dramatic Irony",
            "Shakespeare uses dramatic irony to build tension in the play.",
        ]
        items = reflow_lines(lines)
        self.assertEqual(items[0][0], "para")
        self.assertIn("loyal soldier into a tyrant", items[0][1])
        self.assertTrue(items[0][1].endswith("he cannot control."))
        self.assertEqual(items[1], ("heading", "Dramatic Irony"))
        self.assertNotIn("12", " ".join(t for _, t in items))

    def test_reflow_keeps_bullets_separate(self):
        items = reflow_lines(["Blood Motif", "• Blood symbolises guilt", "• Represents honour early on"])
        self.assertEqual(assemble(items), "# Blood Motif\n- Blood symbolises guilt\n- Represents honour early on\n")

    def test_old_doc_format_is_rejected_with_advice(self):
        path = self.dir / "old.doc"
        path.write_bytes(b"\xd0\xcf\x11\xe0")
        with self.assertRaisesRegex(FileImportError, "docx"):
            import_file(path)


if __name__ == "__main__":
    unittest.main()
