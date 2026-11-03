"""Start CogniDeck:  python main.py"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def use_project_python():
    """Restart under the project's .venv Python if a different Python launched this file.

    The Python that comes with macOS (3.9) ships Tk 8.5, which shows CogniDeck as an
    empty grey window on current macOS, and it doesn't have the app's packages. So if
    VS Code's Run button, a double-click or plain `python3 main.py` picked that Python,
    switch to the project's own one instead of opening a broken window.
    """
    in_project_venv = Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    if in_project_venv:
        return
    if VENV_PYTHON.exists() and os.environ.get("COGNIDECK_RELAUNCHED") != "1":
        os.environ["COGNIDECK_RELAUNCHED"] = "1"  # guard against relaunching forever
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(ROOT / "main.py"), *sys.argv[1:]])
    if sys.version_info < (3, 11):
        sys.exit(
            f"CogniDeck needs Python 3.11 or newer, but this is Python {sys.version.split()[0]}.\n"
            "Set up the project environment first (see README.md), then run: .venv/bin/python main.py"
        )


def main():
    use_project_python()
    from cognideck.ui.app import CogniDeckApp

    # Build the window, then hand control to Tkinter's event loop until the window closes.
    app = CogniDeckApp()
    app.mainloop()


# Only start the app when this file is run directly (not when it's imported, e.g. by tests).
if __name__ == "__main__":
    main()
