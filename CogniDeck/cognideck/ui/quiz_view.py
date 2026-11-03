"""Quiz screen: setup → questions (multiple choice / true-false) → results."""

import customtkinter as ctk

from ..quiz import build_quiz
from ..scheduler import MASTERED
from . import theme

# Setup choices: number of questions, and question type (label → quiz.py's kind).
COUNTS = ["5", "10", "20", "All"]
KINDS = {"Mixed": "mixed", "Multiple choice": "mcq", "True / False": "tf"}


class OptionTile(ctk.CTkFrame):
    """A clickable answer option whose text wraps (CTkButton text can't wrap)."""

    def __init__(self, master, number, text, command):
        super().__init__(master, fg_color=theme.PANEL_ALT, corner_radius=theme.RADIUS, border_width=2,
                         border_color=theme.BORDER)
        self.command = command
        self.locked = False
        self.grid_columnconfigure(1, weight=1)
        self.badge = ctk.CTkLabel(self, text=str(number), width=32, height=32, corner_radius=8,
                                  fg_color=theme.SECONDARY, text_color=theme.TEXT, font=theme.font(14, "bold"))
        self.badge.grid(row=0, column=0, padx=(14, 12), pady=12)
        self.label = ctk.CTkLabel(self, text=text, font=theme.font(15), text_color=theme.TEXT,
                                  justify="left", anchor="w", wraplength=760)
        self.label.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=12)
        # Make the whole tile clickable and highlight its border on hover.
        for widget in (self, self.badge, self.label):
            widget.bind("<Button-1>", lambda _e: self._click())
            widget.bind("<Enter>", lambda _e: self._hover(True))
            widget.bind("<Leave>", lambda _e: self._hover(False))

    def _click(self):
        if not self.locked:
            self.command()

    def _hover(self, inside):
        if not self.locked:
            self.configure(border_color=theme.ACCENT if inside else theme.BORDER)

    def mark(self, color):
        """Fill the tile green (right answer) or red (wrong pick) and stop it being clicked."""
        self.locked = True
        self.configure(border_color=color, fg_color=color)
        self.label.configure(text_color="#FFFFFF")
        self.badge.configure(fg_color="#FFFFFF", text_color=color)

    def dim(self):
        """Grey out the options that weren't involved once an answer is chosen."""
        self.locked = True
        self.configure(border_color=theme.BORDER)
        self.label.configure(text_color=theme.MUTED)


class QuizView(ctk.CTkFrame):
    """The Quiz screen. It has three stages built as separate frames: setup, question and results."""

    def __init__(self, master, app):
        super().__init__(master, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        self.app = app
        # State for the quiz in progress.
        self.questions = []
        self.position = 0       # index of the current question
        self.score = 0
        self.answered = False   # has the current question been answered yet?
        self.missed = []        # questions answered wrongly, listed on the results page
        self.tiles = []         # the OptionTile widgets for the current question

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_setup()
        self._build_question()
        self._build_results()
        self._show(self.setup)

    def _show(self, frame):
        """Show one stage and hide the other two."""
        for f in (self.setup, self.question_frame, self.results):
            f.grid_remove()
        frame.grid(row=0, column=0, sticky="nsew", padx=40, pady=30)

    # ----- setup ---------------------------------------------------------------

    def _build_setup(self):
        self.setup = ctk.CTkFrame(self, fg_color="transparent")
        # `inner` is centred in the screen, and everything is stacked inside it with pack().
        inner = ctk.CTkFrame(self.setup, fg_color="transparent")
        inner.place(relx=0.5, rely=0.45, anchor="center")

        ctk.CTkLabel(inner, text="Quiz yourself", font=theme.font(30, "bold"), text_color=theme.TEXT).pack()
        self.setup_deck = ctk.CTkLabel(inner, text="", font=theme.font(15), text_color=theme.MUTED)
        self.setup_deck.pack(pady=(4, 26))

        ctk.CTkLabel(inner, text="Questions", font=theme.font(13, "bold"), text_color=theme.MUTED).pack()
        self.count_picker = ctk.CTkSegmentedButton(inner, values=COUNTS, height=36, font=theme.font(14),
                                                   selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER)
        self.count_picker.set("10")
        self.count_picker.pack(pady=(6, 18))

        ctk.CTkLabel(inner, text="Question type", font=theme.font(13, "bold"), text_color=theme.MUTED).pack()
        self.kind_picker = ctk.CTkSegmentedButton(inner, values=list(KINDS), height=36, font=theme.font(14),
                                                  selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER)
        self.kind_picker.set("Mixed")
        self.kind_picker.pack(pady=(6, 18))

        self.weak_switch = ctk.CTkSwitch(inner, text="Only cards I haven't mastered", font=theme.font(14),
                                         progress_color=theme.ACCENT, text_color=theme.TEXT)
        self.weak_switch.pack(pady=(0, 24))

        self.start_button = ctk.CTkButton(inner, text="Start quiz", width=240, height=48, corner_radius=theme.RADIUS,
                                          font=theme.font(17, "bold"), fg_color=theme.ACCENT,
                                          hover_color=theme.ACCENT_HOVER, command=self.start)
        self.start_button.pack()
        self.setup_message = ctk.CTkLabel(inner, text="", font=theme.font(13), text_color=theme.RED)
        self.setup_message.pack(pady=(10, 0))
        self.history_label = ctk.CTkLabel(inner, text="", font=theme.font(13), text_color=theme.MUTED)
        self.history_label.pack(pady=(6, 0))

    def start(self, cards=None):
        """Build a quiz and show the first question. `cards` limits it (used by "Retry missed")."""
        deck_id = self.app.current_deck_id
        if deck_id is None:
            self.setup_message.configure(text="Generate or pick a deck first.")
            return
        all_cards = self.app.db.get_cards(deck_id)
        # Decide which cards the questions should be about.
        if cards is None:
            cards = [c for c in all_cards if c["status"] != MASTERED] if self.weak_switch.get() else all_cards
        if len(all_cards) < 2:
            self.setup_message.configure(text="A quiz needs at least 2 cards in the deck.")
            return
        if not cards:
            self.setup_message.configure(text="Every card is mastered — turn off the filter to quiz them all.")
            return

        count = self.count_picker.get()
        count = len(cards) if count == "All" else int(count)
        # Questions come from the chosen cards; wrong options can come from the whole deck.
        chosen_ids = {c["id"] for c in cards}
        questions = build_quiz(all_cards, len(all_cards), KINDS[self.kind_picker.get()])
        questions = [q for q in questions if q.card_id in chosen_ids][:count]
        if not questions:
            self.setup_message.configure(text="Couldn't build questions from this deck — add more cards.")
            return

        # Reset the score and switch to the question stage.
        self.setup_message.configure(text="")
        self.questions, self.position, self.score, self.missed = questions, 0, 0, []
        self._show(self.question_frame)
        self._show_question()

    # ----- questions -----------------------------------------------------------

    def _build_question(self):
        self.question_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.question_frame.grid_columnconfigure(0, weight=1)
        self.question_frame.grid_rowconfigure(3, weight=1)

        # Top line: "Question 3 of 10", the score and an End quiz button.
        top = ctk.CTkFrame(self.question_frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self.q_counter = ctk.CTkLabel(top, text="", font=theme.font(14, "bold"), text_color=theme.ACCENT, anchor="w")
        self.q_counter.grid(row=0, column=0, sticky="w")
        self.q_score = ctk.CTkLabel(top, text="", font=theme.font(14, "bold"), text_color=theme.MUTED)
        self.q_score.grid(row=0, column=1, sticky="e")
        theme.secondary_button(top, "End quiz", self._finish, width=90).grid(row=0, column=2, padx=(14, 0))

        self.q_progress = ctk.CTkProgressBar(self.question_frame, height=8, progress_color=theme.ACCENT,
                                             fg_color=theme.SECONDARY)
        self.q_progress.grid(row=1, column=0, sticky="ew", pady=(10, 24))

        self.q_prompt = ctk.CTkLabel(self.question_frame, text="", font=theme.font(22, "bold"),
                                     text_color=theme.TEXT, justify="left", anchor="w", wraplength=900)
        self.q_prompt.grid(row=2, column=0, sticky="ew", pady=(0, 20))

        # The answer tiles are created fresh for each question in _show_question().
        self.options_frame = ctk.CTkFrame(self.question_frame, fg_color="transparent")
        self.options_frame.grid(row=3, column=0, sticky="new")
        self.options_frame.grid_columnconfigure(0, weight=1)

        # Bottom line: right/wrong feedback, and the Next button (hidden until you answer).
        bottom = ctk.CTkFrame(self.question_frame, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        bottom.grid_columnconfigure(0, weight=1)
        self.feedback = ctk.CTkLabel(bottom, text="", font=theme.font(15), text_color=theme.TEXT,
                                     justify="left", anchor="w", wraplength=760)
        self.feedback.grid(row=0, column=0, sticky="ew")
        self.next_button = ctk.CTkButton(bottom, text="Next question  →", width=180, height=44, corner_radius=theme.SMALL_RADIUS,
                                         font=theme.font(15, "bold"), fg_color=theme.ACCENT,
                                         hover_color=theme.ACCENT_HOVER, command=self._next_question)
        self.next_button.grid(row=0, column=1, sticky="e", padx=(16, 0))
        # Wrap text to the panel's width (binding the label itself would loop: wrapping resizes it).
        self.question_frame.bind("<Configure>", self._rewrap)

    def _rewrap(self, event):
        if event.widget is not self.question_frame:
            return
        width = max(300, event.width - 20)
        self.q_prompt.configure(wraplength=width)
        self.feedback.configure(wraplength=max(250, width - 220))
        for tile in self.tiles:
            tile.label.configure(wraplength=max(250, width - 90))

    def _show_question(self):
        """Display the current question and build a tile for each option."""
        question = self.questions[self.position]
        self.answered = False
        total = len(self.questions)
        self.q_counter.configure(text=f"Question {self.position + 1} of {total}  ·  "
                                      f"{'Multiple choice' if question.kind == 'mcq' else 'True / False'}")
        self.q_score.configure(text=f"Score: {self.score}")
        self.q_progress.set(self.position / total)
        self.q_prompt.configure(text=question.prompt)
        self.feedback.configure(text="Pick an answer (or press its number).", text_color=theme.MUTED)
        self.next_button.grid_remove()

        # Remove the previous question's tiles, then add new ones numbered 1–4.
        for tile in self.tiles:
            tile.destroy()
        self.tiles = []
        for i, option in enumerate(question.options):
            tile = OptionTile(self.options_frame, i + 1, option, lambda i=i: self.answer(i))
            tile.label.configure(wraplength=max(250, self.question_frame.winfo_width() - 110))
            tile.grid(row=i, column=0, sticky="ew", pady=5)
            self.tiles.append(tile)

    def answer(self, index):
        """Mark option `index` as the student's answer, show feedback and record it."""
        # Only the first answer to each question counts.
        if self.answered:
            return
        self.answered = True
        question = self.questions[self.position]
        correct = index == question.answer_index
        if correct:
            self.score += 1
            self.feedback.configure(text="✓ Correct!", text_color=theme.GREEN)
        else:
            self.missed.append(question)
            answer = question.options[question.answer_index]
            self.feedback.configure(text=f"✗ Not quite. The answer is: {answer}", text_color=theme.RED)
            self.tiles[index].mark(theme.RED)
        # Always reveal the right answer in green, and fade out the rest.
        self.tiles[question.answer_index].mark(theme.GREEN)
        for i, tile in enumerate(self.tiles):
            if i not in (index, question.answer_index):
                tile.dim()
        self.q_score.configure(text=f"Score: {self.score}")
        # Save it: a wrong answer sends that card back to Needs Review.
        self.app.db.record_quiz_answer(question.card_id, correct)
        last = self.position == len(self.questions) - 1
        self.next_button.configure(text="See results  →" if last else "Next question  →")
        self.next_button.grid()

    def _next_question(self):
        if self.position < len(self.questions) - 1:
            self.position += 1
            self._show_question()
        else:
            self._finish()

    # ----- results ---------------------------------------------------------------

    def _build_results(self):
        self.results = ctk.CTkFrame(self, fg_color="transparent")
        self.results.grid_columnconfigure(0, weight=1)
        self.results.grid_rowconfigure(3, weight=1)

        self.r_score = ctk.CTkLabel(self.results, text="", font=theme.font(54, "bold"), text_color=theme.ACCENT)
        self.r_score.grid(row=0, column=0, pady=(10, 0))
        self.r_message = ctk.CTkLabel(self.results, text="", font=theme.font(17), text_color=theme.TEXT)
        self.r_message.grid(row=1, column=0, pady=(4, 18))

        buttons = ctk.CTkFrame(self.results, fg_color="transparent")
        buttons.grid(row=2, column=0, pady=(0, 18))
        ctk.CTkButton(buttons, text="Quiz again", width=150, height=42, corner_radius=theme.SMALL_RADIUS, font=theme.font(15, "bold"),
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, command=self.start).pack(side="left", padx=6)
        self.retry_missed_button = theme.secondary_button(buttons, "Retry missed", self._retry_missed, width=150)
        self.retry_missed_button.pack(side="left", padx=6)
        theme.secondary_button(buttons, "Study deck", lambda: self.app.show_view("Study"), width=130).pack(side="left", padx=6)
        theme.secondary_button(buttons, "Change settings", lambda: self._show(self.setup), width=150).pack(side="left", padx=6)

        self.missed_list = ctk.CTkScrollableFrame(self.results, fg_color=theme.PANEL_ALT, corner_radius=theme.RADIUS,
                                                  label_text="Questions to revisit", label_font=theme.font(14, "bold"),
                                                  label_fg_color=theme.SECONDARY, label_text_color=theme.TEXT)
        self.missed_list.grid(row=3, column=0, sticky="nsew")
        self.missed_list.grid_columnconfigure(0, weight=1)

    def _finish(self):
        """Save the result and show the results stage (also used by "End quiz" part-way through)."""
        # If the quiz was ended early, only count the questions actually answered.
        answered = self.position + (1 if self.answered else 0)
        total = answered if answered < len(self.questions) else len(self.questions)
        if total == 0:
            self._show(self.setup)
            return
        self.app.db.save_quiz_result(self.app.current_deck_id, self.score, total)
        self.app.data_changed()
        # Card statuses may have changed, so refresh the Study screen too.
        self.app.views["Study"].reload(keep_position=True)

        # Score and an encouraging message.
        percent = round(100 * self.score / total)
        self.r_score.configure(text=f"{self.score} / {total}")
        if percent == 100:
            message = "Perfect score! 🎉"
        elif percent >= 80:
            message = f"{percent}% — excellent recall."
        elif percent >= 50:
            message = f"{percent}% — getting there. Missed cards were moved to Needs Review."
        else:
            message = f"{percent}% — study the Needs Review cards, then try again."
        self.r_message.configure(text=message)

        # Rebuild the "Questions to revisit" list from scratch.
        for child in self.missed_list.winfo_children():
            child.destroy()
        if not self.missed:
            ctk.CTkLabel(self.missed_list, text="Nothing missed — nice work.", text_color=theme.MUTED,
                         font=theme.font(14)).grid(row=0, column=0, pady=20)
        for row, question in enumerate(self.missed):
            text = f"{question.prompt}\n→ {question.options[question.answer_index]}"
            ctk.CTkLabel(self.missed_list, text=text, font=theme.font(14), text_color=theme.TEXT,
                         justify="left", anchor="w", wraplength=900).grid(row=row, column=0, sticky="ew", padx=14, pady=8)
        self.retry_missed_button.configure(state="normal" if self.missed else "disabled")
        self._show(self.results)

    def _retry_missed(self):
        """Start a new quiz using only the cards behind the missed questions."""
        ids = {q.card_id for q in self.missed}
        cards = [c for c in self.app.db.get_cards(self.app.current_deck_id) if c["id"] in ids]
        if cards:
            self.start(cards)

    # ----- hooks from the app -----------------------------------------------------

    def on_show(self):
        self._refresh_setup()

    def on_deck_changed(self):
        self._refresh_setup()
        self._show(self.setup)

    def _refresh_setup(self):
        """Show the current deck's name, card count and last few quiz scores on the setup stage."""
        deck_id = self.app.current_deck_id
        deck = self.app.db.get_deck(deck_id) if deck_id else None
        if deck:
            n = len(self.app.db.get_cards(deck_id))
            self.setup_deck.configure(text=f"{deck['name']}  ·  {n} cards")
            history = self.app.db.quiz_history(deck_id, limit=5)
            if history:
                scores = ", ".join(f"{h['score']}/{h['total']}" for h in history)
                self.history_label.configure(text=f"Recent scores: {scores}")
            else:
                self.history_label.configure(text="No quizzes taken on this deck yet.")
        else:
            self.setup_deck.configure(text="No deck selected")
            self.history_label.configure(text="")
        self.setup_message.configure(text="")

    def handle_key(self, event):
        """Keys: Enter starts the quiz, 1–4 pick an answer, Enter/Space/→ go to the next question."""
        # On the setup stage, only Enter does anything.
        if not self.question_frame.winfo_ismapped():
            if event.keysym == "Return" and self.setup.winfo_ismapped():
                self.start()
            return
        if event.keysym in ("1", "2", "3", "4") and not self.answered:
            index = int(event.keysym) - 1
            if index < len(self.tiles):
                self.answer(index)
        elif event.keysym in ("Return", "space", "Right") and self.answered:
            self._next_question()
