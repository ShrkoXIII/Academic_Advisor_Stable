"""Compatibility imports; snapshot construction lives in adapters.student."""
from .adapters.student import (
    COUNTS, DIRECT, SOURCED_FIELDS, _official_gpa_credits, adapt_student,
    add_history_features as _history,
)
