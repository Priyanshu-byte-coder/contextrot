"""contextrot — personal context-rot analytics for coding agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("contextrot")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0.dev0"
