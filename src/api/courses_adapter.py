"""Compatibility imports for the canonical course adapter and validators."""
from .adapters.courses import _course, adapt_courses, group_identity
from .validators.courses import _check_source_duplicates, _rules

__all__ = ["adapt_courses", "group_identity", "_check_source_duplicates", "_course", "_rules"]
