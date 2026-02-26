"""Chat message preprocessing — shared between CLI and Web."""

from agenticops.chat.preprocessor import preprocess_message, resolve_references
from agenticops.chat.file_reader import read_file_as_text

__all__ = ["preprocess_message", "resolve_references", "read_file_as_text"]
