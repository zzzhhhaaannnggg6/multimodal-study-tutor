"""Multimodal Study Tutor public API.

The package deliberately keeps the core dependency-free. Optional model and
web integrations live behind small adapters so a project can be inspected and
validated offline.
"""

from .models import LessonMap
from .profiles import StudyProfile, get_profile, list_profiles
from .validation import Diagnostic, ValidationReport, validate_lesson_map

__all__ = [
    "Diagnostic",
    "LessonMap",
    "StudyProfile",
    "ValidationReport",
    "get_profile",
    "list_profiles",
    "validate_lesson_map",
]

__version__ = "0.1.0"
