"""Transcript-free temporal text checks for caption conversions."""

__version__ = "0.1.0"

from .core import CaptionError, compare_files

__all__ = ["CaptionError", "compare_files", "__version__"]
