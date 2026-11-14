"""Диалоговый слой: данные в JSON, код — интерпретатор."""

from .answers import Answer, AnswerPlanner
from .bridge import ActionBridge, ActionResult
from .console import ConsoleEntry, TextGame
from .engine import DialogueSession, Turn
from .errors import DialogueError
from .inference import InferenceEngine, ProofStep, Solution
from .knowledge import AgentKnowledge, Fact, build_knowledge
from .loader import (
    DEFAULT_DIR,
    load_actions,
    load_console,
    load_dialogue,
    load_goals,
    load_styles,
    load_synthesis,
)
from .morph import Morphology
from .model import (
    DialogueCatalog,
    Grammar,
    LexEntry,
    Ontology,
    Parse,
    Persona,
    StyleCatalog,
    StyleSpec,
)
from .morphology import normalize_text, tokenize
from .parser import ChartParser, features_match, merge_features
from .planner import GoalPlan, GoalPlanner, GoalStep, Intent
from .realize import Realizer
from .semantics import entity_id, flatten, predicate_id, substitute
from .state import (
    ConversationState,
    DialogueMemory,
    DialogueMemoryStore,
    EntityIndex,
    build_state,
)
from .style import StyleEngine

__all__ = [
    "ActionBridge",
    "ActionResult",
    "AgentKnowledge",
    "Answer",
    "AnswerPlanner",
    "ChartParser",
    "ConversationState",
    "ConsoleEntry",
    "DEFAULT_DIR",
    "DialogueCatalog",
    "DialogueError",
    "DialogueMemory",
    "DialogueMemoryStore",
    "DialogueSession",
    "EntityIndex",
    "Fact",
    "GoalPlan",
    "GoalPlanner",
    "GoalStep",
    "Grammar",
    "InferenceEngine",
    "Intent",
    "LexEntry",
    "Morphology",
    "Ontology",
    "Parse",
    "Persona",
    "ProofStep",
    "Realizer",
    "Solution",
    "StyleCatalog",
    "StyleEngine",
    "StyleSpec",
    "TextGame",
    "Turn",
    "build_knowledge",
    "build_state",
    "entity_id",
    "features_match",
    "flatten",
    "load_actions",
    "load_console",
    "load_dialogue",
    "load_goals",
    "load_styles",
    "load_synthesis",
    "merge_features",
    "normalize_text",
    "predicate_id",
    "substitute",
    "tokenize",
]
