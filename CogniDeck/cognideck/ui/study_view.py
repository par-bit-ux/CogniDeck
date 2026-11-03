"""Main screen. Left column: paste notes and generate a deck. Right column: study it."""

import random
import re
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..importer import SUPPORTED_TYPES, FileImportError, import_file
from ..parser import CARD_TYPE_LABELS, MODES, parse_notes, summarise
from ..scheduler import IN_PROGRESS, MASTERED, NEEDS_REVIEW, STATUS_LABELS, STATUSES, is_due, study_order
from . import theme
from .flipcard import FlipCard

# Choices in the order/filter dropdown above the card (see reload()).
ORDERS = ["Smart order", "Due now", "Needs review", "Not mastered", "Original order"]

# The hint shown under the front of each card type.
PROMPTS = {
    "essay": "What are the key points?",
    "quote": "Explain the quote",
    "definition": "Define this term",
    "qa": "Answer the question",
    "bullets": "Recall the key points",
    "cloze": "Fill in the blank",
    "manual": "",
}


class StudyView(ctk.CTkFrame):
    """The Study screen: notes in on the left, flashcards out on the right."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        # The cards being studied (already filtered and ordered) and which one is showing.
        self.cards = []
        self.index = 0
        # The pending "move to the next card" timer after a rating, so it can be cancelled.
        self._advance_job = None

        self.grid_rowconfigure(0, weight=1)
        # The notes panel can be hidden so you can't peek at the answers while studying.
        self.notes_hidden = False
        self._set_column_widths()

        self._build_input_panel()
        self._build_hidden_strip()
        self._build_study_panel()

    def _set_column_widths(self):
        if self.notes_hidden:
            # Notes hidden: a thin strip on the left, the flashcards take the rest.
            self.grid_columnconfigure(0, weight=0, uniform="")
            self.grid_columnconfigure(1, weight=1, uniform="")
        else:
            # Two columns in a 2:3 width ratio; `uniform` keeps that ratio as the window resizes.
            self.grid_columnconfigure(0, weight=2, uniform="cols")
            self.grid_columnconfigure(1, weight=3, uniform="cols")

    def toggle_notes(self):
        """Hide the notes panel (so you can't see the answers) or bring it back."""
        self.notes_hidden = not self.notes_hidden
        if self.notes_hidden:
            self.input_panel.grid_remove()
            self.hidden_strip.grid()
            self.app.focus_set()
        else:
            self.hidden_strip.grid_remove()
            self.input_panel.grid()
        self._set_column_widths()

    def _build_hidden_strip(self):
        """The thin bar shown in place of the notes while they're hidden."""
        strip = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS, width=64)
        strip.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        strip.grid_propagate(False)
        strip.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            strip, text="▶", width=40, height=40, corner_radius=theme.SMALL_RADIUS, font=theme.font(16, "bold"),
            fg_color=theme.SECONDARY, hover_color=theme.SECONDARY_HOVER, text_color=theme.TEXT,
            command=self.toggle_notes,
        ).grid(row=0, column=0, pady=(20, 8))
        # Tk can't rotate text, so spell "NOTES" downwards.
        ctk.CTkLabel(strip, text="\n".join("NOTES"), font=theme.font(13, "bold"), text_color=theme.MUTED,
                     ).grid(row=1, column=0)
        strip.grid_remove()
        self.hidden_strip = strip

    # ----- left column: input ------------------------------------------------

    def _build_input_panel(self):
        panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.input_panel = panel
        panel.grid_columnconfigure(0, weight=1)
        # Row 4 (the notes box) takes up any spare height.
        panel.grid_rowconfigure(4, weight=1)

        theme.section_title(panel, "Input (Passive Reading)").grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 0))
        # Hide button, top right of the panel (shortcut: N).
        theme.secondary_button(panel, "◀  Hide  (N)", self.toggle_notes, width=110).grid(
            row=0, column=0, sticky="e", padx=22, pady=(20, 0))
        ctk.CTkLabel(
            panel, text="Paste essays, lecture notes, glossaries or Q&A, or open a PDF / Word file. "
                        "Everything is parsed offline.",
            font=theme.font(13), text_color=theme.MUTED, anchor="w", justify="left", wraplength=380,
        ).grid(row=1, column=0, sticky="ew", padx=22, pady=(2, 12))

        # Deck name box and parsing-mode dropdown, side by side.
        options = ctk.CTkFrame(panel, fg_color="transparent")
        options.grid(row=2, column=0, sticky="ew", padx=22)
        options.grid_columnconfigure(0, weight=1)
        options.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(options, text="Deck name", font=theme.font(12, "bold"), text_color=theme.MUTED,
                     anchor="w").grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(options, text="Turn notes into", font=theme.font(12, "bold"), text_color=theme.MUTED,
                     anchor="w").grid(row=0, column=1, sticky="ew", padx=(10, 0))

        self.name_entry = ctk.CTkEntry(options, placeholder_text="e.g. Macbeth themes", height=36,
                                       corner_radius=theme.SMALL_RADIUS, border_color=theme.BORDER)
        self.name_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.mode_menu = ctk.CTkOptionMenu(
            options, values=list(MODES.values()), height=36, corner_radius=theme.SMALL_RADIUS, dynamic_resizing=False,
            fg_color=theme.SECONDARY, button_color=theme.SECONDARY_HOVER,
            button_hover_color=theme.BORDER, text_color=theme.TEXT,
        )
        self.mode_menu.set(MODES["auto"])
        self.mode_menu.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(4, 0))

        # Toolbar: open a file (.txt/.md/.pdf/.docx), clear, plus a word count.
        tools = ctk.CTkFrame(panel, fg_color="transparent")
        tools.grid(row=3, column=0, sticky="ew", padx=22, pady=(12, 6))
        theme.secondary_button(tools, "Open file…", self.open_file, width=100).pack(side="left")
        theme.secondary_button(tools, "Clear", self.clear_input, width=70).pack(side="left", padx=6)
        self.char_count = ctk.CTkLabel(tools, text="", font=theme.font(12), text_color=theme.MUTED)
        self.char_count.pack(side="right")

        self.textbox = ctk.CTkTextbox(
            panel, wrap="word", font=ctk.CTkFont(size=15), corner_radius=theme.RADIUS, border_width=2,
            fg_color=theme.INPUT_BG, text_color=theme.INPUT_TEXT, border_color=theme.BORDER,
            border_spacing=10,
        )
        self.textbox.grid(row=4, column=0, sticky="nsew", padx=22)
        # Keep the word count live while typing.
        self.textbox.bind("<KeyRelease>", lambda _e: self._update_count())
        # Esc leaves the text box so Space / arrows / 1-2-3 work as study shortcuts again.
        self.textbox.bind("<Escape>", lambda _e: self.app.focus_set())

        self.generate_button = ctk.CTkButton(
            panel, text="Generate Deck", height=44, corner_radius=theme.RADIUS,
            font=theme.font(16, "bold"), fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self.generate,
        )
        self.generate_button.grid(row=5, column=0, sticky="ew", padx=22, pady=(14, 6))

        self.result_label = ctk.CTkLabel(panel, text="", font=theme.font(13), text_color=theme.MUTED,
                                         wraplength=380, justify="left", anchor="w")
        self.result_label.grid(row=6, column=0, sticky="ew", padx=22, pady=(0, 16))


    def clear_input(self):
        self.textbox.delete("1.0", "end")
        self.name_entry.delete(0, "end")
        self._update_count()
        self.textbox.focus_set()

    def open_file(self):
        """Load notes from a .txt, .md, .pdf or .docx file into the notes box."""
        path = filedialog.askopenfilename(
            title="Open notes", filetypes=SUPPORTED_TYPES + [("All files", "*.*")],
        )
        if not path:
            return
        # Big PDFs take a moment, so say so before the window pauses to read it.
        self._show_result("Reading file… (scanned pages take a few seconds each)")
        self.update_idletasks()
        try:
            text = import_file(path)
        except FileImportError as error:
            self._show_result(str(error), error=True)
            return
        except Exception as error:  # never fail silently: show what went wrong in the window
            self._show_result(f"Couldn't import {Path(path).name}: {error}", error=True)
            return
        # Show the extracted text so the student can check or tidy it before generating.
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)
        filename = Path(path).name
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, re.sub(r"[_-]+", " ", Path(path).stem).strip())
        self._update_count()
        self._show_result(f"Imported {filename}. Check the text, then press Generate.")

    def _update_count(self):
        text = self.textbox.get("1.0", "end").strip()
        words = len(text.split())
        self.char_count.configure(text=f"{words} words" if words else "")

    def _show_result(self, message, error=False):
        self.result_label.configure(text=message, text_color=theme.RED if error else theme.MUTED)

    def generate(self):
        """The big button: parse the notes, save them as a new deck and show its first card."""
        text = self.textbox.get("1.0", "end").strip()
        if not text:
            self._show_result("Paste some notes first.", error=True)
            return
        # The dropdown shows labels, so look up which mode key the chosen label belongs to.
        mode = next(key for key, label in MODES.items() if label == self.mode_menu.get())
        cards = parse_notes(text, mode)
        if not cards:
            self._show_result(summarise(cards), error=True)
            return

        name = self.name_entry.get().strip() or self._guess_name(text)
        deck_id = self.app.db.create_deck(name, cards, mode, text)
        self._show_result(f"✓ Created “{name}” — {summarise(cards)}")
        # Update flashcards.json, switch every screen to the new deck and enable shortcuts.
        self.app.data_changed()
        self.app.set_deck(deck_id)
        self.app.focus_set()
        # Hide the notes so the answers aren't on screen while you study (press N to see them again).
        if not self.notes_hidden:
            self.toggle_notes()

    @staticmethod
    def _guess_name(text):
        """No name typed? Use the first few words of the first line (without "#" or bullets)."""
        first = next((l for l in text.splitlines() if l.strip()), "New deck")
        first = re.sub(r"^[#\s*•-]+", "", first).split(":")[0]
        return " ".join(first.split()[:6]) or "New deck"

    # ----- right column: study deck ----------------------------------------------

    def _build_study_panel(self):
        panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)
        # Clicking anywhere on this side takes focus away from the notes box.
        panel.bind("<Button-1>", lambda _e: self.app.focus_set())

        # Header: deck name, order dropdown, Shuffle, and the "Card 1 of 5 — FRONT" counter.
        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 0))
        header.grid_columnconfigure(0, weight=1)

        self.deck_title = theme.section_title(header, "Output (Active Recall)")
        self.deck_title.grid(row=0, column=0, sticky="ew")
        self.order_menu = ctk.CTkOptionMenu(
            header, values=ORDERS, width=150, height=32, corner_radius=theme.SMALL_RADIUS, command=lambda _v: self.reload(),
            fg_color=theme.SECONDARY, button_color=theme.SECONDARY_HOVER,
            button_hover_color=theme.BORDER, text_color=theme.TEXT,
        )
        self.order_menu.grid(row=0, column=1, padx=(8, 0))
        theme.secondary_button(header, "Shuffle", self.shuffle, width=80).grid(row=0, column=2, padx=(8, 0))

        self.counter = ctk.CTkLabel(header, text="", font=theme.font(14, "bold"), text_color=theme.ACCENT,
                                    anchor="w")
        self.counter.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        # Green bar showing how much of the deck is mastered.
        progress = ctk.CTkFrame(panel, fg_color="transparent")
        progress.grid(row=1, column=0, sticky="ew", padx=24, pady=(10, 0))
        progress.grid_columnconfigure(0, weight=1)
        self.mastery_bar = ctk.CTkProgressBar(progress, height=10, corner_radius=5,
                                              progress_color=theme.GREEN, fg_color=theme.SECONDARY)
        self.mastery_bar.grid(row=0, column=0, sticky="ew")
        self.mastery_bar.set(0)
        self.mastery_label = ctk.CTkLabel(progress, text="", font=theme.font(12), text_color=theme.MUTED, anchor="w")
        self.mastery_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        self.flipcard = FlipCard(panel, on_flip=self._flipped, on_click=self.app.focus_set)
        self.flipcard.grid(row=3, column=0, sticky="nsew", padx=24, pady=14)

        # Previous / Flip / Next buttons under the card.
        nav = ctk.CTkFrame(panel, fg_color="transparent")
        nav.grid(row=4, column=0, pady=(0, 8))
        theme.secondary_button(nav, "←  Previous", self.previous, width=130).pack(side="left", padx=5)
        ctk.CTkButton(nav, text="Flip card  (Space)", command=self.flipcard.flip, width=170, height=38,
                      corner_radius=theme.SMALL_RADIUS, font=theme.font(14, "bold"), fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER).pack(side="left", padx=5)
        theme.secondary_button(nav, "Next  →", self.next, width=130).pack(side="left", padx=5)

        # The three rating buttons, numbered 1–3 to match their keyboard shortcuts.
        ratings = ctk.CTkFrame(panel, fg_color="transparent")
        ratings.grid(row=5, column=0, pady=(2, 4))
        for key, (status, color, hover) in enumerate(
            [(NEEDS_REVIEW, theme.RED, theme.RED_HOVER), (IN_PROGRESS, theme.AMBER, theme.AMBER_HOVER),
             (MASTERED, theme.GREEN, theme.GREEN_HOVER)], start=1,
        ):
            ctk.CTkButton(
                ratings, text=f"{STATUS_LABELS[status]}  ({key})", width=160, height=40, corner_radius=theme.SMALL_RADIUS,
                font=theme.font(14, "bold"), fg_color=color, hover_color=hover, text_color="#FFFFFF",
                # s=status freezes the value now; otherwise every button would use the loop's last status.
                command=lambda s=status: self.rate(s),
            ).pack(side="left", padx=5)

        ctk.CTkLabel(
            panel, text="Space flip   ·   ← → move   ·   1 2 3 rate   ·   N hide/show notes   ·   Esc leaves the notes box",
            font=theme.font(12), text_color=theme.MUTED,
        ).grid(row=6, column=0, pady=(2, 16))

    # ----- deck loading ------------------------------------------------------

    # The app calls these hooks: a new deck starts at card 1; coming back to this screen
    # keeps your place.
    def on_deck_changed(self):
        self.reload(keep_position=False)

    def on_show(self):
        self.reload(keep_position=True)

    def reload(self, keep_position=False):
        """Fetch the deck's cards again and apply the chosen order/filter."""
        deck_id = self.app.current_deck_id
        # Remember which card was showing so we can find it again after reloading.
        current_id = self.cards[self.index]["id"] if keep_position and self.cards else None
        if deck_id is None:
            self.cards = []
            self._show_current()
            return

        deck = self.app.db.get_deck(deck_id)
        all_cards = self.app.db.get_cards(deck_id)
        order = self.order_menu.get()
        # "Smart order" (the default, in the else) uses the spaced-repetition priority.
        if order == "Due now":
            cards = [c for c in study_order(all_cards) if is_due(c)]
        elif order == "Needs review":
            cards = [c for c in all_cards if c["status"] == NEEDS_REVIEW]
        elif order == "Not mastered":
            cards = study_order([c for c in all_cards if c["status"] != MASTERED])
        elif order == "Original order":
            cards = list(all_cards)
        else:
            cards = study_order(all_cards)
        self.cards = cards
        # Go back to the remembered card if it's still in the list, otherwise start at the top.
        ids = [c["id"] for c in cards]
        self.index = ids.index(current_id) if current_id in ids else 0
        # The mastery bar always counts the whole deck, not just the filtered cards.
        self._update_mastery(all_cards)
        self._show_current()

    def shuffle(self):
        """Put the current cards in a random order and start from the first."""
        if self.cards:
            random.shuffle(self.cards)
            self.index = 0
            self._show_current(direction="next")

    def _update_mastery(self, all_cards=None):
        """Update the green progress bar and the "3 new  2 mastered ..." line under it."""
        if all_cards is None:
            all_cards = self.app.db.get_cards(self.app.current_deck_id) if self.app.current_deck_id else []
        total = len(all_cards)
        counts = {s: sum(1 for c in all_cards if c["status"] == s) for s in STATUSES}
        self.mastery_bar.set(counts[MASTERED] / total if total else 0)
        self.mastery_label.configure(
            text="   ".join(f"{counts[s]} {STATUS_LABELS[s].lower()}" for s in STATUSES) if total else ""
        )

    # ----- study actions -----------------------------------------------------

    def _show_current(self, direction=None):
        """Put the card at self.index on the flip card (sliding it in if `direction` is set)."""
        # No cards: show a helpful message on the card instead.
        if not self.cards:
            if self.app.current_deck_id is None:
                message = "Paste your notes on the left and press\n“Generate Deck”."
            else:
                message = "No cards match this filter.\nTry “Smart order” or pick another deck."
            self.flipcard.set_empty(message)
            self.counter.configure(text="")
            return
        card = self.cards[self.index]
        self.flipcard.set_card(
            card["front"], card["back"], status=card["status"],
            card_label=CARD_TYPE_LABELS.get(card["card_type"], "Card"),
            prompt=PROMPTS.get(card["card_type"], ""), direction=direction,
        )
        self._update_counter(False)

    def _update_counter(self, back):
        if self.cards:
            side = "BACK" if back else "FRONT"
            self.counter.configure(text=f"Card {self.index + 1} of {len(self.cards)} — {side}")

    def _flipped(self, back):
        self._update_counter(back)

    def next(self):
        # Ignore presses mid-animation; % wraps from the last card back to the first.
        if self.cards and not self.flipcard.animating:
            self._cancel_advance()
            self.index = (self.index + 1) % len(self.cards)
            self._show_current(direction="next")

    def previous(self):
        if self.cards and not self.flipcard.animating:
            self._cancel_advance()
            self.index = (self.index - 1) % len(self.cards)
            self._show_current(direction="prev")

    def rate(self, status):
        """Save a self-rating (Needs Review / In Progress / Mastered) and move on."""
        if not self.cards or self.flipcard.animating:
            return
        # The database applies the spaced-repetition rules and hands back the updated card.
        card = self.app.db.rate_card(self.cards[self.index]["id"], status)
        self.cards[self.index] = card
        self.flipcard.update_status(status)
        self._update_mastery()
        self.app.data_changed()
        # Give the student a moment to see the new status, then move on.
        self._cancel_advance()
        self._advance_job = self.after(350, self._advance_after_rating)

    def _advance_after_rating(self):
        self._advance_job = None
        # On the last card, show a summary instead of wrapping round to the start.
        if self.index == len(self.cards) - 1:
            left = sum(1 for c in self.cards if c["status"] != MASTERED)
            self.counter.configure(
                text="Deck complete! " + (f"{left} cards still to master — keep going." if left
                                          else "Every card mastered. 🎉")
            )
            return
        self.next()

    def _cancel_advance(self):
        if self._advance_job:
            self.after_cancel(self._advance_job)
            self._advance_job = None

    def handle_key(self, event):
        """Keyboard shortcuts (the app only sends keys here when no text box has focus)."""
        key = event.keysym
        if key == "space":
            self.flipcard.flip()
        elif key == "Right":
            self.next()
        elif key == "Left":
            self.previous()
        elif key in ("n", "N"):
            self.toggle_notes()
        elif key in ("1", "2", "3"):
            self.rate((NEEDS_REVIEW, IN_PROGRESS, MASTERED)[int(key) - 1])
