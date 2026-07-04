"""Enable `python -m contextrot` as a PATH-independent entry point.

Users whose pip scripts directory is not on PATH (common with the stock
macOS python3 and `pip install --user`) can still run the tool this way.
"""

from contextrot.cli import app

if __name__ == "__main__":
    app()
