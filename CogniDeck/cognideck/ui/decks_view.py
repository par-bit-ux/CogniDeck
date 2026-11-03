"""Deck management: list decks, rename/delete/reset/export them, and add, edit or delete cards by hand."""

import subprocess
import sys
from tkinter import messagebox

import customtkinter as ctk

from .. import EXPORT_PATH
from ..parser import CARD_TYPE_LABELS
from ..scheduler import STATUS_LABELS
from . import theme


class DecksView(ctk.CTkFrame):
    """The Decks screen: deck list and actions on the left, the selected deck's cards on the right."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        # Id of the card loaded into the form for editing (None means the form adds a new card).
        self.editing_card_id = None

        self.grid_columnconfigure(0, weight=2, uniform="cols")
        self.grid_columnconfigure(1, weight=5, uniform="cols")
        self.grid_rowconfigure(0, weight=1)
        self._build_deck_panel()
        self._build_card_panel()

    # ----- decks -----------------------------------------------------------------

    def _build_deck_panel(self):
        panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="Your decks", font=theme.font(20, "bold"), text_color=theme.TEXT,
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        self.deck_list = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self.deck_list.grid(row=1, column=0, sticky="nsew", padx=10)
        self.deck_list.grid_columnconfigure(0, weight=1)

        # Six action buttons laid out in a 2-column grid (i // 2 = row, i % 2 = column).
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 20))
        actions.grid_columnconfigure((0, 1), weight=1)
        buttons = [
            ("New empty deck", self.new_deck), ("Rename", self.rename_deck),
            ("Reset progress", self.reset_deck), ("Delete deck", self.delete_deck),
            ("Export JSON", self.export), ("Show JSON file", self.reveal_export),
        ]
        for i, (text, command) in enumerate(buttons):
            button = theme.secondary_button(actions, text, command, width=120)
            if text == "Delete deck":
                button.configure(text_color=theme.RED)
            button.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
        self.export_label = ctk.CTkLabel(actions, text="", font=theme.font(12), text_color=theme.MUTED,
                                         wraplength=260, justify="left")
        self.export_label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _render_decks(self):
        """Rebuild the deck list; the current deck is highlighted. Clicking a deck selects it."""
        for child in self.deck_list.winfo_children():
            child.destroy()
        decks = self.app.db.list_decks()
        if not decks:
            ctk.CTkLabel(self.deck_list, text="No decks yet.\nGenerate one on the Study screen.",
                         text_color=theme.MUTED, font=theme.font(13)).grid(row=0, column=0, pady=20)
        for row, deck in enumerate(decks):
            selected = deck["id"] == self.app.current_deck_id
            mastered = deck["mastered_count"] or 0
            text = f"{deck['name']}\n{deck['card_count']} cards  ·  {mastered} mastered"
            ctk.CTkButton(
                self.deck_list, text=text, anchor="w", height=56, corner_radius=theme.SMALL_RADIUS, font=theme.font(14),
                fg_color=theme.ACCENT if selected else theme.PANEL_ALT,
                hover_color=theme.ACCENT_HOVER if selected else theme.SECONDARY_HOVER,
                text_color="#FFFFFF" if selected else theme.TEXT,
                command=lambda d=deck["id"]: self.app.set_deck(d),
            ).grid(row=row, column=0, sticky="ew", padx=6, pady=4)

    # Each deck action below changes the database, then calls data_changed() (to update
    # flashcards.json) and set_deck() (so every screen reloads).

    def new_deck(self):
        """Ask for a name and create an empty deck to fill in by hand."""
        dialog = ctk.CTkInputDialog(text="Name for the new deck:", title="New deck")
        name = (dialog.get_input() or "").strip()
        if name:
            deck_id = self.app.db.create_deck(name, mode="manual")
            self.app.data_changed()
            self.app.set_deck(deck_id)
            self.front_box.focus_set()

    def rename_deck(self):
        deck_id = self.app.current_deck_id
        if deck_id is None:
            return
        dialog = ctk.CTkInputDialog(text="New name:", title="Rename deck")
        name = (dialog.get_input() or "").strip()
        if name:
            self.app.db.rename_deck(deck_id, name)
            self.app.data_changed()
            self.app.set_deck(deck_id)

    def reset_deck(self):
        deck_id = self.app.current_deck_id
        if deck_id and messagebox.askyesno("Reset progress", "Set every card in this deck back to New?"):
            self.app.db.reset_progress(deck_id)
            self.app.data_changed()
            self.app.set_deck(deck_id)

    def delete_deck(self):
        deck_id = self.app.current_deck_id
        if deck_id is None:
            return
        deck = self.app.db.get_deck(deck_id)
        # Deleting is permanent, so always confirm first.
        if messagebox.askyesno("Delete deck", f"Delete “{deck['name']}” and all its cards? This can't be undone."):
            self.app.db.delete_deck(deck_id)
            self.app.data_changed()
            # Switch to the newest remaining deck (or none).
            remaining = self.app.db.list_decks()
            self.app.set_deck(remaining[0]["id"] if remaining else None)

    def export(self):
        self.app.data_changed()
        self.export_label.configure(text=f"Saved {EXPORT_PATH.name} to the project folder.")

    def reveal_export(self):
        self.app.data_changed()
        # On a Mac, "open -R" shows the file in Finder; elsewhere just print its path.
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(EXPORT_PATH)], check=False)
        else:
            self.export_label.configure(text=str(EXPORT_PATH))

    # ----- cards -----------------------------------------------------------------

    def _build_card_panel(self):
        panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        self.cards_title = ctk.CTkLabel(panel, text="Cards", font=theme.font(20, "bold"), text_color=theme.TEXT,
                                        anchor="w")
        self.cards_title.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 8))

        # The add/edit form: front and back boxes side by side, then Save and Cancel buttons.
        form = ctk.CTkFrame(panel, fg_color=theme.PANEL_ALT, corner_radius=theme.RADIUS)
        form.grid(row=1, column=0, sticky="ew", padx=22)
        form.grid_columnconfigure((0, 1), weight=1)
        self.form_title = ctk.CTkLabel(form, text="Add a card", font=theme.font(14, "bold"), text_color=theme.TEXT,
                                       anchor="w")
        self.form_title.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(form, text="Front (question, term or prompt)", font=theme.font(12), text_color=theme.MUTED,
                     anchor="w").grid(row=1, column=0, sticky="ew", padx=14)
        ctk.CTkLabel(form, text="Back (answer — start lines with • for bullet points)", font=theme.font(12),
                     text_color=theme.MUTED, anchor="w").grid(row=1, column=1, sticky="ew", padx=14)
        self.front_box = ctk.CTkTextbox(form, height=80, wrap="word", corner_radius=theme.SMALL_RADIUS, border_width=1,
                                        border_color=theme.BORDER, fg_color=theme.INPUT_BG, text_color=theme.INPUT_TEXT)
        self.front_box.grid(row=2, column=0, sticky="ew", padx=(14, 7), pady=(2, 8))
        self.back_box = ctk.CTkTextbox(form, height=80, wrap="word", corner_radius=theme.SMALL_RADIUS, border_width=1,
                                       border_color=theme.BORDER, fg_color=theme.INPUT_BG, text_color=theme.INPUT_TEXT)
        self.back_box.grid(row=2, column=1, sticky="ew", padx=(7, 14), pady=(2, 8))

        buttons = ctk.CTkFrame(form, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 12))
        self.save_button = ctk.CTkButton(buttons, text="Add card", width=130, height=34, corner_radius=theme.SMALL_RADIUS,
                                         fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                                         font=theme.font(13, "bold"), command=self.save_card)
        self.save_button.pack(side="left")
        # Created now but only shown (packed) while editing a card.
        self.cancel_button = theme.secondary_button(buttons, "Cancel edit", self.cancel_edit)
        self.form_message = ctk.CTkLabel(buttons, text="", font=theme.font(12), text_color=theme.MUTED)
        self.form_message.pack(side="left", padx=12)

        # Scrollable list of every card in the deck.
        self.card_list = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self.card_list.grid(row=2, column=0, sticky="nsew", padx=12, pady=(10, 16))
        self.card_list.grid_columnconfigure(0, weight=1)

    def _render_cards(self):
        """Rebuild the card list for the current deck."""
        for child in self.card_list.winfo_children():
            child.destroy()
        deck_id = self.app.current_deck_id
        if deck_id is None:
            self.cards_title.configure(text="Cards")
            return
        deck = self.app.db.get_deck(deck_id)
        cards = self.app.db.get_cards(deck_id)
        self.cards_title.configure(text=f"{deck['name']}  ·  {len(cards)} cards")
        for row, card in enumerate(cards):
            self._card_row(row, card)

    def _card_row(self, row, card):
        """One row in the card list: front and back text on the left; status, type and buttons on the right."""
        frame = ctk.CTkFrame(self.card_list, fg_color=theme.PANEL_ALT, corner_radius=theme.SMALL_RADIUS)
        frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        frame.grid_columnconfigure(0, weight=1)

        # Show a one-line preview of each side, cut short if it's long.
        wrap = max(260, self.card_list.winfo_width() - 230)
        front = card["front"].replace("\n", " ")
        back = card["back"].replace("\n", "  ")
        ctk.CTkLabel(frame, text=front if len(front) < 160 else front[:157] + "…", font=theme.font(14, "bold"),
                     text_color=theme.TEXT, anchor="w", justify="left", wraplength=wrap).grid(
            row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        ctk.CTkLabel(frame, text=back if len(back) < 200 else back[:197] + "…", font=theme.font(13),
                     text_color=theme.MUTED, anchor="w", justify="left", wraplength=wrap).grid(
            row=1, column=0, sticky="ew", padx=14, pady=(2, 10))

        side = ctk.CTkFrame(frame, fg_color="transparent")
        side.grid(row=0, column=1, rowspan=2, padx=(4, 12), pady=8)
        ctk.CTkLabel(side, text=STATUS_LABELS[card["status"]], width=104, height=24, corner_radius=8,
                     fg_color=theme.STATUS_COLORS[card["status"]], text_color="#FFFFFF",
                     font=theme.font(11, "bold")).pack(pady=(0, 4))
        ctk.CTkLabel(side, text=f"{CARD_TYPE_LABELS.get(card['card_type'], 'Card')} · {card['review_count']} reviews",
                     font=theme.font(11), text_color=theme.MUTED).pack(pady=(0, 4))
        buttons = ctk.CTkFrame(side, fg_color="transparent")
        buttons.pack()
        theme.secondary_button(buttons, "Edit", lambda c=card: self.edit_card(c), width=50).pack(side="left", padx=2)
        delete = theme.secondary_button(buttons, "Delete", lambda c=card: self.delete_card(c), width=58)
        delete.configure(text_color=theme.RED)
        delete.pack(side="left", padx=2)

    def save_card(self):
        """Add a new card, or save changes to the one being edited."""
        deck_id = self.app.current_deck_id
        front = self.front_box.get("1.0", "end").strip()
        back = self.back_box.get("1.0", "end").strip()
        if deck_id is None:
            self.form_message.configure(text="Create or pick a deck first.", text_color=theme.RED)
            return
        if not front or not back:
            self.form_message.configure(text="Fill in both sides.", text_color=theme.RED)
            return
        if self.editing_card_id:
            self.app.db.update_card(self.editing_card_id, front, back)
            message = "Card updated."
        else:
            self.app.db.add_card(deck_id, front, back)
            message = "Card added."
        # Clear the form, then refresh everything that shows this deck.
        self.cancel_edit()
        self.form_message.configure(text=message, text_color=theme.GREEN)
        self.app.data_changed()
        self.app.refresh_decks()
        self._refresh()
        self.app.views["Study"].reload(keep_position=True)

    def edit_card(self, card):
        """Load a card into the form and switch the form into edit mode."""
        self.editing_card_id = card["id"]
        self.front_box.delete("1.0", "end")
        self.front_box.insert("1.0", card["front"])
        self.back_box.delete("1.0", "end")
        self.back_box.insert("1.0", card["back"])
        self.form_title.configure(text="Edit card")
        self.save_button.configure(text="Save changes")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.form_message.configure(text="")
        self.front_box.focus_set()

    def cancel_edit(self):
        """Empty the form and put it back into "Add a card" mode."""
        self.editing_card_id = None
        self.front_box.delete("1.0", "end")
        self.back_box.delete("1.0", "end")
        self.form_title.configure(text="Add a card")
        self.save_button.configure(text="Add card")
        self.cancel_button.pack_forget()
        self.form_message.configure(text="")

    def delete_card(self, card):
        if messagebox.askyesno("Delete card", "Delete this card?"):
            self.app.db.delete_card(card["id"])
            # Don't leave a deleted card sitting in the edit form.
            if self.editing_card_id == card["id"]:
                self.cancel_edit()
            self.app.data_changed()
            self.app.refresh_decks()
            self._refresh()
            self.app.views["Study"].reload(keep_position=False)

    # ----- hooks from the app -----------------------------------------------------

    def _refresh(self):
        self._render_decks()
        self._render_cards()

    def on_show(self):
        self._refresh()

    def on_deck_changed(self):
        self.cancel_edit()
        # Only redraw now if this screen is visible; otherwise on_show() will do it later.
        if self.winfo_ismapped():
            self._refresh()
