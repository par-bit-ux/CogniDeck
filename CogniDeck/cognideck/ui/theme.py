"""Colours, fonts and shapes. CogniDeck uses one dark graphite theme with a blue accent."""

import customtkinter as ctk

from ..scheduler import IN_PROGRESS, MASTERED, NEEDS_REVIEW, NEW

# Backgrounds, panels and text: neutral graphite greys, darkest at the edges.
BG = "#1E1F23"            # window background
SIDEBAR = "#17181B"       # icon sidebar on the left
PANEL = "#25262A"         # main panels
PANEL_ALT = "#2C2D32"     # boxes inside panels (list rows, quiz options)
INPUT_BG = "#1B1C1F"
INPUT_TEXT = "#E6E6E8"
BORDER = "#393A40"
DIVIDER = "#2F3035"
TEXT = "#ECECEE"
MUTED = "#9A9BA2"

# The blue accent, used for main buttons, the selected sidebar icon and highlights.
ACCENT = "#2F80ED"
ACCENT_HOVER = "#2468C8"
ACCENT_SOFT = "#1D3150"

# Flashcard faces: the front has a blue outline, the back is tinted so you can tell the sides apart.
CARD_FRONT = "#2A2B30"
CARD_BACK = "#262D3A"
CARD_BORDER = "#3D3E45"

# Self-ratings (and right/wrong in quizzes).
RED = "#E5534B"
RED_HOVER = "#C7443D"
AMBER = "#D9962E"
AMBER_HOVER = "#BB7F22"
GREEN = "#3BA776"
GREEN_HOVER = "#2F8C62"
GREY = "#686A72"

# Quieter grey buttons for less important actions.
SECONDARY = "#34353B"
SECONDARY_HOVER = "#3F4047"

# Corner rounding: panels and cards are only slightly rounded, like native macOS windows.
RADIUS = 12
SMALL_RADIUS = 8

# Which colour each card status is shown in.
STATUS_COLORS = {
    NEW: GREY,
    NEEDS_REVIEW: RED,
    IN_PROGRESS: AMBER,
    MASTERED: GREEN,
}


def pick(color):
    """Return a plain hex colour (matplotlib needs one). Kept for older (light, dark) pairs."""
    return color if isinstance(color, str) else color[-1]


def font(size=14, weight="normal"):
    """Shortcut for the app's font at a given size and weight."""
    return ctk.CTkFont(size=size, weight=weight)


def section_title(master, text):
    """A panel heading like "Input (Passive Reading)"."""
    return ctk.CTkLabel(master, text=text, font=font(20, "bold"), text_color=TEXT, anchor="w")


def secondary_button(master, text, command, width=110, **kwargs):
    """A grey button with the app's standard size and rounding (used all over the UI)."""
    return ctk.CTkButton(
        master, text=text, command=command, width=width, height=32, corner_radius=SMALL_RADIUS,
        fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT, font=font(13), **kwargs,
    )
