"""The animated flashcard.

Tkinter has no 3D transforms, so the flip is simulated: the card squashes
horizontally to a sliver (as if turning edge-on), swaps to the other face, then
stretches back out. Easing makes it speed up into the turn and settle out of it.
Moving to the next or previous card slides the card off one side and a new one
in from the other.
"""

import math

import customtkinter as ctk

from ..scheduler import STATUS_LABELS
from . import theme

FRAME_MS = 14          # ~70 fps
FLIP_FRAMES = 11       # frames per half-turn
SLIDE_FRAMES = 13


# Easing curves: `t` goes from 0 to 1 over the animation and the result is how far along
# the movement is. ease_in starts slow and speeds up; ease_out starts fast and slows down.
def ease_in(t):
    return 1 - math.cos(t * math.pi / 2)


def ease_out(t):
    return math.sin(t * math.pi / 2)


class FlipCard(ctk.CTkFrame):
    """A flashcard widget that flips between front and back and slides between cards."""

    def __init__(self, master, on_flip=None, on_click=None):
        super().__init__(master, fg_color="transparent")
        # Callbacks to the Study screen.
        self.on_flip = on_flip
        self.on_click = on_click
        # What's on the card right now.
        self.front_text = ""
        self.back_text = ""
        self.status = None
        self.card_label = ""
        self.showing_back = False
        # True mid-animation, so extra clicks or key presses are ignored until it finishes.
        self.animating = False
        self.has_card = False

        # `face` is the rounded card that gets squashed and slid; `content` holds the text on it.
        # Both use place() rather than grid() so their size and position can be animated.
        self.face = ctk.CTkFrame(
            self, corner_radius=theme.RADIUS, border_width=2,
            fg_color=theme.CARD_FRONT, border_color=theme.CARD_BORDER,
        )
        self.face.place(relx=0.5, rely=0.5, anchor="center", relwidth=1.0, relheight=1.0)

        self.content = ctk.CTkFrame(self.face, fg_color=theme.CARD_FRONT, corner_radius=0)
        self._place_content()
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_columnconfigure(1, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        # Top row: a small FRONT/BACK label on the left and the card's status on the right.
        self.side_pill = ctk.CTkLabel(
            self.content, text="FRONT", height=26, anchor="w",
            fg_color="transparent", text_color=theme.MUTED, font=theme.font(13, "bold"),
        )
        self.side_pill.grid(row=0, column=0, sticky="w")

        self.status_pill = ctk.CTkLabel(
            self.content, text="", corner_radius=theme.SMALL_RADIUS, height=26, width=110,
            fg_color=theme.GREY, text_color="#FFFFFF", font=theme.font(12, "bold"),
        )
        self.status_pill.grid(row=0, column=1, sticky="e")

        # Middle: the card text, with a hint such as "Define this term" underneath.
        self.prompt = ctk.CTkLabel(self.content, text="", text_color=theme.MUTED, font=theme.font(13))
        self.prompt.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        self.body = ctk.CTkLabel(
            self.content, text="", text_color=theme.TEXT, font=theme.font(24, "bold"),
            justify="center", wraplength=560,
        )
        self.body.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=12)

        self.footer = ctk.CTkLabel(
            self.content, text="Click the card or press Space to flip",
            text_color=theme.MUTED, font=theme.font(12),
        )
        self.footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # Clicking anywhere on the card flips it, so every part of it listens for clicks.
        for widget in (self.face, self.content, self.body, self.prompt, self.footer, self.side_pill, self.status_pill):
            widget.bind("<Button-1>", self._clicked)
        # Re-wrap the text whenever the card changes size.
        self.bind("<Configure>", self._resized)

    # ----- public API --------------------------------------------------------

    def set_card(self, front, back, status=None, card_label="", prompt="", direction=None):
        """Show a new card (front side up). `direction` is "next" or "prev" to slide it in."""
        # apply() swaps the content; it runs straight away or halfway through a slide.
        def apply():
            self.front_text, self.back_text = front, back
            self.status, self.card_label, self.prompt_text = status, card_label, prompt
            self.showing_back = False
            self.has_card = True
            self._render()

        if direction and self.has_card and not self.animating:
            self._slide(direction, apply)
        else:
            apply()

    def set_empty(self, message):
        """Show a message instead of a card (no deck yet, or no cards match the filter)."""
        self.has_card = False
        self.showing_back = False
        self.front_text, self.back_text = message, ""
        self.status, self.card_label, self.prompt_text = None, "", ""
        self._render()
        self.side_pill.configure(text="EMPTY")
        self.footer.configure(text="")

    def update_status(self, status):
        """Recolour the status pill after the student rates the card."""
        self.status = status
        self._render_status()

    def flip(self):
        """Animate the card turning over: squash to a sliver, swap sides, stretch back out."""
        if not self.has_card or self.animating:
            return
        self.animating = True
        # Hide the text during the flip; squashed text would look messy.
        self.content.place_forget()

        # Each step function gets t from 0 to 1 and sets the card's width (and a slight
        # height dip, which makes it look like it's tilting away).
        def squash(t):
            e = ease_in(t)
            self.face.place_configure(relwidth=max(0.015, 1 - e), relheight=1 - 0.05 * e)

        def stretch(t):
            e = ease_out(t)
            self.face.place_configure(relwidth=max(0.015, e), relheight=0.95 + 0.05 * e)

        # Halfway: the card is edge-on, so switch sides now, then stretch back out.
        def turned():
            self.showing_back = not self.showing_back
            self._render(content_visible=False)
            self._run(FLIP_FRAMES, stretch, finished)

        def finished():
            self.face.place_configure(relwidth=1.0, relheight=1.0)
            self._place_content()
            self.animating = False
            if self.on_flip:
                self.on_flip(self.showing_back)

        self._run(FLIP_FRAMES, squash, turned)

    # ----- drawing -----------------------------------------------------------

    def _place_content(self):
        self.content.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.9, relheight=0.86)

    def _render(self, content_visible=True):
        """Draw whichever side is showing: colours, text, pills and footer."""
        back = self.showing_back
        face_color = theme.CARD_BACK if back else theme.CARD_FRONT
        # Like the reference design: the front of a real card has a blue outline, the back a grey one.
        outline = theme.ACCENT if self.has_card and not back else theme.CARD_BORDER
        self.face.configure(fg_color=face_color, border_color=outline)
        self.content.configure(fg_color=face_color)

        text = self.back_text if back else self.front_text
        # Bullet-point answers read better left-aligned; everything else is centred.
        is_list = back and ("\n•" in "\n" + text)
        self.body.configure(
            text=text,
            font=theme.font(self._font_size(text), "normal" if back else "bold"),
            justify="left" if is_list else "center",
            anchor="w" if is_list else "center",
        )
        self.side_pill.configure(text="BACK" if back else "FRONT", text_color=theme.ACCENT if back else theme.MUTED)
        if self.has_card:
            label = f"{self.card_label}  ·  " if self.card_label else ""
            self.prompt.configure(text="" if back else getattr(self, "prompt_text", ""))
            self.footer.configure(text=f"{label}{'Rate yourself below' if back else 'Click or press Space to flip'}")
        else:
            self.prompt.configure(text="")
        self._render_status()
        if content_visible and not self.animating:
            self._place_content()

    def _render_status(self):
        if self.status:
            self.status_pill.configure(
                text=STATUS_LABELS[self.status].upper(), fg_color=theme.STATUS_COLORS[self.status],
            )
            self.status_pill.grid()
        else:
            self.status_pill.grid_remove()

    @staticmethod
    def _font_size(text):
        """Smaller text for longer cards, so everything fits on the card."""
        n = len(text)
        if n < 60:
            return 28
        if n < 140:
            return 23
        if n < 280:
            return 19
        if n < 480:
            return 16
        return 14

    def _resized(self, event):
        self.body.configure(wraplength=max(200, int(event.width * 0.9) - 40))

    # ----- animation ---------------------------------------------------------

    def _run(self, frames, step, done):
        """Play an animation: call step(t) once per frame, then done() at the end.

        Tkinter has no animation system, so each frame schedules the next one with
        after(). This keeps the window responsive (a loop with sleep() would freeze it).
        """
        def tick(i=1):
            step(i / frames)
            if i < frames:
                self.after(FRAME_MS, tick, i + 1)
            else:
                done()
        tick()

    def _slide(self, direction, swap):
        """Slide the card out, swap its content, slide the new card in from the other side."""
        self.animating = True
        # relx positions as a fraction of the width: 0.5 is centred, -0.65 and 1.65 are off-screen.
        # "Next" slides out to the left and in from the right; "previous" does the opposite.
        out_x = -0.65 if direction == "next" else 1.65
        in_x = 1.65 if direction == "next" else -0.65

        def slide_out(t):
            self.face.place_configure(relx=0.5 + (out_x - 0.5) * ease_in(t))

        def slide_in(t):
            self.face.place_configure(relx=in_x + (0.5 - in_x) * ease_out(t))

        def swapped():
            self.face.place_configure(relx=in_x)
            swap()
            self._run(SLIDE_FRAMES, slide_in, finished)

        def finished():
            self.face.place_configure(relx=0.5)
            self.animating = False

        self._run(SLIDE_FRAMES, slide_out, swapped)

    def _clicked(self, _event=None):
        # Let the Study screen take keyboard focus back from the notes box, then flip.
        if self.on_click:
            self.on_click()
        self.flip()
