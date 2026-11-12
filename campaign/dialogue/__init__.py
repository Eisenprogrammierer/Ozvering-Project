"""Диалоговый слой: данные в JSON, код — интерпретатор."""

from .errors import DialogueError
from .loader import DEFAULT_DIR, load_dialogue
from .model import DialogueCatalog, Grammar, LexEntry, Ontology, Parse
from .morphology import normalize_text, tokenize
from .parser import ChartParser, features_match, merge_features
from .semantics import entity_id, flatten, predicate_id, substitute

__all__ = [
    "ChartParser",
    "DEFAULT_DIR",
    "DialogueCatalog",
    "DialogueError",
    "Grammar",
    "LexEntry",
    "Ontology",
    "Parse",
    "entity_id",
    "features_match",
    "flatten",
    "load_dialogue",
    "merge_features",
    "normalize_text",
    "predicate_id",
    "substitute",
    "tokenize",
]
