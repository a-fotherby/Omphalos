"""PFLOTRAN keyword block object classes.

This module re-exports from core.keyword_block for backward compatibility.
New code should import directly from core.keyword_block.
"""

# Re-export all classes and exceptions from core module for backward compatibility
from core.keyword_block import (
    KeywordBlockModificationError,
    ConditionBlockModificationError,
    KeywordBlock,
    ConditionBlock,
)

__all__ = [
    'KeywordBlockModificationError',
    'ConditionBlockModificationError',
    'KeywordBlock',
    'ConditionBlock',
]
