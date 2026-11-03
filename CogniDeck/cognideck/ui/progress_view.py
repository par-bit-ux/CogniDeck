"""Progress dashboard: summary tiles plus matplotlib charts of mastery, study activity and quiz scores."""

import customtkinter as ctk
import matplotlib

# Tell matplotlib to draw into Tkinter widgets. This must happen before the imports
# below, which is why they come after code (and carry "noqa" to silence the linter).
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from ..scheduler import MASTERED, STATUS_LABELS, STATUSES, is_due  # noqa: E402
from . import theme  # noqa: E402


class ProgressView(ctk.CTkFrame):
    """The Progress screen: a row of number tiles above three charts."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Six equal-width summary tiles. Each value label is stored by name so refresh() can update it.
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.tiles = {}
        names = ["Cards in deck", "Mastered", "Due now", "Study streak", "Reviews today", "Avg quiz score"]
        for i, name in enumerate(names):
            tiles.grid_columnconfigure(i, weight=1, uniform="tiles")
            tile = ctk.CTkFrame(tiles, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
            tile.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0 if i == len(names) - 1 else 6))
            value = ctk.CTkLabel(tile, text="–", font=theme.font(28, "bold"), text_color=theme.TEXT)
            value.pack(pady=(14, 0))
            ctk.CTkLabel(tile, text=name, font=theme.font(12), text_color=theme.MUTED).pack(pady=(0, 14))
            self.tiles[name] = value

        # One matplotlib Figure, embedded in the window through a Tk canvas.
        self.chart_panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        self.chart_panel.grid(row=1, column=0, sticky="nsew")
        self.figure = Figure(figsize=(12, 4.6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.chart_panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=18, pady=18)

    def on_show(self):
        self.refresh()

    def on_deck_changed(self):
        if self.winfo_ismapped():
            self.refresh()

    def refresh(self):
        """Recalculate every tile and redraw the charts for the current deck."""
        db = self.app.db
        deck_id = self.app.current_deck_id
        cards = db.get_cards(deck_id) if deck_id else []
        counts = db.status_counts(deck_id) if deck_id else dict.fromkeys(STATUSES, 0)
        history = db.quiz_history(deck_id) if deck_id else []

        total = len(cards)
        streak = db.study_streak()
        self.tiles["Cards in deck"].configure(text=str(total))
        self.tiles["Mastered"].configure(text=f"{round(100 * counts[MASTERED] / total)}%" if total else "–")
        self.tiles["Due now"].configure(text=str(sum(1 for c in cards if is_due(c))))
        self.tiles["Study streak"].configure(text=f"{streak} day{'s' if streak != 1 else ''}")
        self.tiles["Reviews today"].configure(text=str(db.reviews_today()))
        # Average of each quiz's percentage (so short and long quizzes count equally).
        if history:
            avg = sum(h["score"] / h["total"] for h in history) / len(history)
            self.tiles["Avg quiz score"].configure(text=f"{round(100 * avg)}%")
        else:
            self.tiles["Avg quiz score"].configure(text="–")

        self._draw_charts(counts, db.reviews_per_day(14), history)

    def _draw_charts(self, counts, per_day, history):
        """Draw the donut, bar chart and line chart in colours that match the current theme."""
        # matplotlib needs single hex colours, not customtkinter's (light, dark) pairs.
        bg, text, muted, grid = (theme.pick(c) for c in (theme.PANEL, theme.TEXT, theme.MUTED, theme.BORDER))
        accent = theme.pick(theme.ACCENT)
        self.canvas.get_tk_widget().configure(bg=bg)
        # Start from a blank figure each time, split into 3 charts side by side.
        fig = self.figure
        fig.clear()
        fig.patch.set_facecolor(bg)
        axes = fig.subplots(1, 3, gridspec_kw={"width_ratios": [1, 1.4, 1.4]})
        # Shared styling: themed background, muted ticks, and no top/right border lines.
        for ax in axes:
            ax.set_facecolor(bg)
            ax.tick_params(colors=muted, labelsize=9)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color(grid)

        # 1. Mastery donut for the current deck.
        ax = axes[0]
        values = [counts[s] for s in STATUSES]
        if sum(values):
            colors = [theme.pick(theme.STATUS_COLORS[s]) for s in STATUSES]
            # A pie with a "width" under 1 becomes a donut, leaving room for text in the middle.
            ax.pie(values, colors=colors, startangle=90, counterclock=False,
                   wedgeprops={"width": 0.36, "edgecolor": bg, "linewidth": 2})
            ax.legend([f"{STATUS_LABELS[s]} ({counts[s]})" for s in STATUSES], loc="upper center",
                      bbox_to_anchor=(0.5, 0.02), ncol=2, frameon=False, fontsize=9, labelcolor=text)
            share = round(100 * counts[MASTERED] / sum(values))
            ax.text(0, 0, f"{share}%\nmastered", ha="center", va="center", color=text, fontsize=13, weight="bold")
        else:
            ax.text(0.5, 0.5, "No cards yet", ha="center", va="center", color=muted, transform=ax.transAxes)
            ax.axis("off")
        ax.set_title("Deck mastery", color=text, fontsize=12, weight="bold", pad=10)

        # 2. Reviews per day (all decks), the study streak at a glance.
        ax = axes[1]
        # Label every other day so the dates don't overlap; today's bar is green.
        labels = [d.strftime("%d %b") if i % 2 == 0 else "" for i, (d, _) in enumerate(per_day)]
        heights = [n for _, n in per_day]
        bars = ax.bar(range(len(per_day)), heights, color=accent, width=0.65)
        if heights:
            bars[-1].set_color(theme.pick(theme.GREEN))
        ax.set_xticks(range(len(per_day)), labels, rotation=45, ha="right")
        ax.yaxis.get_major_locator().set_params(integer=True)
        ax.grid(axis="y", color=grid, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_title("Cards reviewed per day (last 14 days)", color=text, fontsize=12, weight="bold", pad=10)

        # 3. Quiz scores over time for this deck.
        ax = axes[2]
        if history:
            percents = [round(100 * h["score"] / h["total"]) for h in history]
            xs = range(1, len(percents) + 1)
            ax.plot(xs, percents, color=accent, linewidth=2.4, marker="o", markersize=6)
            ax.fill_between(xs, percents, color=accent, alpha=0.28)
            ax.set_xticks(list(xs))
            ax.set_xlabel("Quiz attempt", color=muted, fontsize=9)
        else:
            ax.text(0.5, 0.5, "Take a quiz to see your scores", ha="center", va="center", color=muted,
                    transform=ax.transAxes)
        ax.set_ylim(0, 105)
        ax.grid(axis="y", color=grid, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_title("Quiz accuracy (%)", color=text, fontsize=12, weight="bold", pad=10)

        # Tighten the margins, then redraw when Tkinter is next idle.
        fig.subplots_adjust(left=0.03, right=0.98, top=0.88, bottom=0.22, wspace=0.28)
        self.canvas.draw_idle()
