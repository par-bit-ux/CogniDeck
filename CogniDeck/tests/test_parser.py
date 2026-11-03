"""Tests for the offline note parser: one test per note format, plus the mixed sample notes."""

import unittest

from cognideck.parser import parse_notes
from cognideck.sample_notes import MACBETH_NOTES


def types(cards):
    """The card type of each card, in order (makes assertions short)."""
    return [c.card_type for c in cards]


class ParserTests(unittest.TestCase):
    def test_definitions(self):
        cards = parse_notes("Hamartia: the fatal flaw of a tragic hero\nMotif - a recurring image or idea")
        self.assertEqual(types(cards), ["definition", "definition"])
        self.assertEqual(cards[0].front, "Hamartia")
        self.assertEqual(cards[1].back, "a recurring image or idea")

    def test_question_and_answer(self):
        cards = parse_notes("Q: Who kills Duncan?\nA: Macbeth.\n\nQuestion: Where?\nAnswer: Inverness castle.")
        self.assertEqual([(c.front, c.back) for c in cards],
                         [("Who kills Duncan?", "Macbeth."), ("Where?", "Inverness castle.")])

    def test_answer_after_blank_line_rejoins_question(self):
        cards = parse_notes("Q: Who kills Duncan?\n\nA: Macbeth.")
        self.assertEqual([(c.front, c.back) for c in cards], [("Who kills Duncan?", "Macbeth.")])

    def test_heading_with_bullets(self):
        cards = parse_notes("Blood motif:\n- Symbolises guilt\n- Shows honour in battle early on")
        self.assertEqual(types(cards), ["bullets"])
        self.assertEqual(cards[0].front, "Blood motif")
        self.assertIn("• Symbolises guilt", cards[0].back)

    def test_essay_becomes_key_points(self):
        essay = (
            "Macbeth's ambition is his fatal flaw. The witches awaken his desire for power. "
            "Lady Macbeth questions his manhood to push him. This shows how ambition overrides his judgement. "
            "Ultimately his ambition leads to his death."
        )
        cards = parse_notes(essay, "essay")
        self.assertEqual(cards[0].card_type, "essay")
        self.assertEqual(cards[0].front, "Macbeth's ambition is his fatal flaw.")
        points = cards[0].back.split("\n")
        self.assertTrue(2 <= len(points) <= 4)
        self.assertTrue(all(p.startswith("• ") for p in points))

    def test_quotes_get_their_own_cards(self):
        cards = parse_notes('He is praised as "brave Macbeth" in battle. This shows his early honour.', "essay")
        self.assertIn("quote", types(cards))

    def test_cloze_blanks_a_word(self):
        cards = parse_notes("Lady Macbeth exploits his ambition by questioning his manhood.", "cloze")
        self.assertEqual(len(cards), 1)
        self.assertIn("_____", cards[0].front)
        # Putting the answer back into the blank must give the original sentence.
        answer = cards[0].back.split("\n")[0]
        self.assertEqual(cards[0].front.replace("_____", answer),
                         "Lady Macbeth exploits his ambition by questioning his manhood.")

    def test_sample_notes_mixed(self):
        cards = parse_notes(MACBETH_NOTES)
        found = set(types(cards))
        self.assertTrue({"essay", "quote", "bullets", "definition", "qa"} <= found)

    def test_every_mode_handles_sample(self):
        for mode in ("auto", "essay", "definitions", "qa", "bullets", "cloze"):
            with self.subTest(mode=mode):
                self.assertTrue(parse_notes(MACBETH_NOTES, mode))

    def test_empty_input(self):
        self.assertEqual(parse_notes("   \n\n "), [])

    def test_pdf_reflow_dividers_and_spacing(self):
        """Divider lines split paragraphs instead of becoming bullets, and stray spaces inside punctuation go."""
        from cognideck.importer import assemble, reflow_lines

        lines = [
            "The telescreen , described as a “ never-sleeping ear ” , watches Winston.",
            "",
            "-------------------------------------------",
            "",
            "Julia rebels in secret, but the Party still wins.",
        ]
        text = assemble(reflow_lines(lines))
        self.assertIn("The telescreen, described as a “never-sleeping ear”, watches Winston.", text)
        self.assertNotIn("- ---", text)
        self.assertNotIn("#", text)


if __name__ == "__main__":
    unittest.main()
