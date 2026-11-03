"""Main window: icon sidebar on the left, a header (page title and deck picker) and the four screens."""

import tkinter as tk

import customtkinter as ctk

from ..database import Database
from ..exporter import export_all
from . import theme
from .decks_view import DecksView
from .progress_view import ProgressView
from .quiz_view import QuizView
from .study_view import StudyView

SCREENS = ("Study", "Quiz", "Decks", "Progress")
# Sidebar icon for each screen.
ICONS = {"Study": "⌂", "Quiz": "✎", "Decks": "❒", "Progress": "◔"}


class CogniDeckApp(ctk.CTk):
    """The main window. It owns the database and the "current deck" that every screen shows."""

    def __init__(self, db=None):
        # CogniDeck only has a dark theme. Appearance has to be set before the window is created.
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title("CogniDeck")
        self.geometry("1320x840")
        self.minsize(1080, 720)
        self.configure(fg_color=theme.BG)

        # Shared state: tests can pass in their own database.
        self.db = db or Database()
        self.current_deck_id = None
        # Maps the names shown in the deck dropdown to deck ids.
        self._deck_labels = {}

        # Column 0 is the icon sidebar. In column 1, row 0 is the header and row 2 (the screens)
        # stretches to fill the window.
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_sidebar()
        self._build_header()

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=2, column=1, sticky="nsew", padx=20, pady=(16, 20))
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        # All four screens are built once and stacked in the same grid cell;
        # switching screens just raises one to the top (see show_view).
        self.views = {
            "Study": StudyView(container, self),
            "Quiz": QuizView(container, self),
            "Decks": DecksView(container, self),
            "Progress": ProgressView(container, self),
        }
        for view in self.views.values():
            view.grid(row=0, column=0, sticky="nsew")
        self.current_view = None

        # Open on the newest deck (if there is one) and the Study screen.
        decks = self.db.list_decks()
        self.refresh_decks()
        self.set_deck(decks[0]["id"] if decks else None)
        self.show_view("Study")

        # One key handler for the whole window; it passes keys on to the visible screen.
        self.bind("<KeyPress>", self._on_key)
        # Close the database cleanly when the window's close button is clicked.
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ----- layout ------------------------------------------------------------

    def _build_sidebar(self):
        """The dark strip of screen icons down the left edge; the current screen's icon is blue."""
        bar = ctk.CTkFrame(self, fg_color=theme.SIDEBAR, corner_radius=0, width=76)
        bar.grid(row=0, column=0, rowspan=3, sticky="ns")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bar, text="◆", font=theme.font(22, "bold"), text_color=theme.ACCENT).grid(
            row=0, column=0, pady=(18, 22))

        self.nav_buttons = {}
        for i, name in enumerate(SCREENS, start=1):
            item = ctk.CTkFrame(bar, fg_color="transparent")
            item.grid(row=i, column=0, pady=(0, 12))
            button = ctk.CTkButton(
                item, text=ICONS[name], width=44, height=44, corner_radius=10, font=theme.font(20),
                fg_color="transparent", hover_color=theme.SECONDARY, text_color=theme.MUTED,
                command=lambda n=name: self.show_view(n),
            )
            button.pack()
            caption = ctk.CTkLabel(item, text=name, font=theme.font(10), text_color=theme.MUTED, height=14)
            caption.pack(pady=(2, 0))
            caption.bind("<Button-1>", lambda _e, n=name: self.show_view(n))
            self.nav_buttons[name] = (button, caption)

    def _build_header(self):
        """Page title on the left, deck picker on the right, and a thin line underneath."""
        header = ctk.CTkFrame(self, fg_color="transparent", height=60)
        header.grid(row=0, column=1, sticky="ew", padx=24, pady=(14, 10))
        header.grid_columnconfigure(0, weight=1)

        self.page_title = ctk.CTkLabel(header, text="", font=theme.font(24, "bold"), text_color=theme.TEXT,
                                       anchor="w")
        self.page_title.grid(row=0, column=0, sticky="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(right, text="Deck", font=theme.font(13, "bold"), text_color=theme.MUTED).pack(side="left", padx=(0, 8))
        self.deck_menu = ctk.CTkOptionMenu(
            right, values=["No decks yet"], command=self._deck_picked, width=240, height=34,
            corner_radius=theme.SMALL_RADIUS, dynamic_resizing=False, fg_color=theme.PANEL,
            button_color=theme.SECONDARY, button_hover_color=theme.SECONDARY_HOVER, text_color=theme.TEXT,
            dropdown_fg_color=theme.PANEL, dropdown_hover_color=theme.SECONDARY, dropdown_text_color=theme.TEXT,
        )
        self.deck_menu.pack(side="left")

        ctk.CTkFrame(self, fg_color=theme.DIVIDER, height=1, corner_radius=0).grid(row=1, column=1, sticky="ew")

    # ----- navigation and shared state -----------------------------------------

    def show_view(self, name):
        """Switch to a screen and let it refresh its data."""
        for screen, (button, caption) in self.nav_buttons.items():
            selected = screen == name
            button.configure(fg_color=theme.ACCENT if selected else "transparent",
                             hover_color=theme.ACCENT_HOVER if selected else theme.SECONDARY,
                             text_color="#FFFFFF" if selected else theme.MUTED)
            caption.configure(text_color=theme.TEXT if selected else theme.MUTED)
        self.page_title.configure(text=name)
        self.current_view = self.views[name]
        self.current_view.tkraise()
        self.current_view.on_show()
        # Take focus off any text box so keyboard shortcuts work straight away.
        self.focus_set()

    def refresh_decks(self):
        """Rebuild the deck picker from the database."""
        decks = self.db.list_decks()
        names = [d["name"] for d in decks]
        self._deck_labels = {}
        for deck in decks:
            # Two decks with the same name get their id added so they can be told apart.
            label = deck["name"] if names.count(deck["name"]) == 1 else f"{deck['name']} (#{deck['id']})"
            self._deck_labels[label] = deck["id"]
        self.deck_menu.configure(values=list(self._deck_labels) or ["No decks yet"])
        self._sync_deck_menu()

    def _sync_deck_menu(self):
        """Make the dropdown show the current deck's name."""
        label = next((l for l, i in self._deck_labels.items() if i == self.current_deck_id), None)
        self.deck_menu.set(label or "No decks yet")

    def set_deck(self, deck_id):
        """Make `deck_id` the current deck and tell every screen to reload."""
        # Guard against a deck that has just been deleted.
        if deck_id is not None and self.db.get_deck(deck_id) is None:
            deck_id = None
        self.current_deck_id = deck_id
        self.refresh_decks()
        for view in self.views.values():
            view.on_deck_changed()

    def _deck_picked(self, label):
        if label in self._deck_labels:
            self.set_deck(self._deck_labels[label])

    def data_changed(self):
        """Called after anything is written to the database: keeps flashcards.json in sync."""
        export_all(self.db)

    # ----- keyboard ------------------------------------------------------------

    def _on_key(self, event):
        focus = self.focus_get()
        # While typing in a text box, Space and the number keys must type, not trigger shortcuts.
        if isinstance(focus, (tk.Text, tk.Entry)):
            return
        # Only screens that define handle_key (Study and Quiz) respond to shortcuts.
        handler = getattr(self.current_view, "handle_key", None)
        if handler:
            handler(event)

    def _close(self):
        self.db.close()
        self.destroy()
