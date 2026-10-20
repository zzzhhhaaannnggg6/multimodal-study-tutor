"""Multimodal Study Tutor public API.

The package deliberately keeps the core dependency-free. Optional model and
web integrations live behind small adapters so a project can be inspected and
validated offline.
"""

from .models import LessonMap
from .profiles import StudyProfile, get_profile, list_profiles
from .validation import Diagnostic, ValidationReport, validate_lesson_map
from .guide import SourceRef, StudyGuide, generate_study_guide, validate_study_guide
from .providers import SpeechProvider, TextModelProvider, VisionProvider

__all__ = [
    "Diagnostic",
    "LessonMap",
    "StudyGuide",
    "SpeechProvider",
    "SourceRef",
    "TextModelProvider",
    "VisionProvider",
    "StudyProfile",
    "ValidationReport",
    "get_profile",
    "list_profiles",
    "generate_study_guide",
    "validate_study_guide",
    "validate_lesson_map",
]

__version__ = "0.2.0"
