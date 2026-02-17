"""Pipeline stages"""
from .detect import detect_ci
from .migrate import migrate_ci
from .validate import validate_yaml
from .double_check import semantic_double_check
from .pull_request import create_pull_request

__all__ = [
    "detect_ci",
    "migrate_ci", 
    "validate_yaml",
    "semantic_double_check",
    "create_pull_request",
]
