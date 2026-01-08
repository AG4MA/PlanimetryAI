"""
Text Utilities
==============
Shared text processing functions.
Single source of truth for text normalization.
"""

import unicodedata


def normalize_text(s: str) -> str:
    """
    Normalize text for comparison: lowercase, remove accents, clean spaces.
    
    This is the canonical normalization used throughout PlanParser.
    
    Args:
        s: Input text string
        
    Returns:
        Normalized, cleaned text
    """
    if not s:
        return ""
    
    # NFD decomposition to separate accents
    s = unicodedata.normalize("NFD", s)
    
    # Remove combining characters (accents)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    
    s = s.lower()
    s = s.replace("-", " ")
    
    # Keep only alphanumeric and basic punctuation
    s = "".join(ch for ch in s if ch.isalnum() or ch in " ._/")
    
    # Normalize whitespace
    s = " ".join(s.split())
    
    # Remove trailing periods from abbreviations
    if s.endswith(".") and len(s) <= 5:
        s = s[:-1]
    
    return s.strip()


def clean_ocr_text(s: str) -> str:
    """
    Clean OCR text by removing common artifacts.
    
    Args:
        s: Raw OCR text
        
    Returns:
        Cleaned text
    """
    if not s:
        return ""
    
    # Future: add OCR artifact corrections
    # For now, just strip whitespace
    return s.strip()
