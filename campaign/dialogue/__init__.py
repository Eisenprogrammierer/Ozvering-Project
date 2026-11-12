"""Диалоговый слой: данные в JSON, код — интерпретатор."""

from .answers import Answer, AnswerPlanner
from .engine import DialogueSession, Turn
from .errors import DialogueError
from .inference import InferenceEngine, ProofStep, Solution
from .knowledge import AgentKnowledge, Fact, build_knowledge
from .loader import DEFAULT_DIR, load_dialogue, load_synthesis
from .morph import Morphology
from .model import (
    DialogueCatalog,
    Grammar,
    LexEntry,
    Ontology,
    Parse,
    Persona,
)
from .morphology import normalize_text, tokenize
from .parser import ChartParser, features_match, merge_features
from .realize import Realizer
from .semantics import entity_id, flatten, predicate_id, substitute

__all__ = [
    "AgentKnowledge",
    "Answer",
    "AnswerPlanner",
    "ChartParser",
    "DEFAULT_DIR",
    "DialogueCatalog",
    "DialogueError",
    "DialogueSession",
    "Fact",
    "Grammar",
    "InferenceEngine",
    "LexEntry",
    "Morphology",
    "Ontology",
    "Parse",
    "Persona",
    "ProofStep",
    "Realizer",
    "Solution",
    "Turn",
    "build_knowledge",
    "entity_id",
    "features_match",
    "flatten",
    "load_dialogue",
    "load_synthesis",
    "merge_features",
    "normalize_text",
    "predicate_id",
    "substitute",
    "tokenize",
]
