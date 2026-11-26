"""Диалоговый слой: данные в JSON, код — интерпретатор."""

from .answers import Answer, AnswerPlanner, answer_handler_name
from .bridge import ActionBridge, ActionResult
from .console import ConsoleEntry, TextGame
from .engine import DialogueSession, Turn
from .errors import DialogueError
from .inference import InferenceEngine, ProofStep, Solution
from .inference_backend import (
    INFERENCE_BACKENDS,
    InferenceBackend,
    InferenceReport,
    load_inference,
)

from .knowledge import AgentKnowledge, Fact, build_knowledge
from .loader import (
    DEFAULT_DIR,
    load_actions,
    load_answer_kinds,
    load_console,
    load_dialogue,
    load_goals,
    load_narrator,
    load_styles,
    load_synthesis,
    load_time,
)
from .morph import Morphology
from .movement import MovementGuide, MoveResult
from .narrator import Narration, Narrator, NarrationEntry
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
from .projection import (
    ProjectedAction,
    merge_actions,
    project_action,
    project_actions,
    projected_registry,
)
from .realize import Realizer
from .pragmatics import (
    DIALOGUE_BACKENDS,
    DialoguePragmatics,
    PragmaticsReport,
    load_pragmatics,
)
from .semantics import entity_id, flatten, predicate_id, substitute
from .state import (
    ConversationState,
    DialogueMemory,
    DialogueMemoryStore,
    EntityIndex,
    build_state,
)
from .style import StyleEngine
from .timeflow import TimeGuide, TimeResult

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
    "DIALOGUE_BACKENDS",
    "DialogueCatalog",
    "DialogueError",
    "DialogueMemory",
    "DialoguePragmatics",
    "DialogueMemoryStore",
    "DialogueSession",
    "EntityIndex",
    "Fact",
    "GoalPlan",
    "GoalPlanner",
    "GoalStep",
    "Grammar",
    "INFERENCE_BACKENDS",
    "InferenceBackend",
    "InferenceEngine",
    "InferenceReport",
    "Intent",
    "LexEntry",
    "Morphology",
    "MoveResult",
    "MovementGuide",
    "Narration",
    "NarrationEntry",
    "Narrator",
    "NluBackend",
    "NluReport",
    "Ontology",
    "Parse",
    "Persona",
    "PragmaticsReport",
    "ProjectedAction",
    "ProofStep",
    "Realizer",
    "Solution",
    "StyleCatalog",
    "StyleEngine",
    "StyleSpec",
    "TextGame",
    "TimeGuide",
    "TimeResult",
    "Turn",
    "answer_handler_name",
    "build_knowledge",
    "build_state",
    "entity_id",
    "features_match",
    "flatten",
    "load_actions",
    "load_answer_kinds",
    "load_console",
    "load_dialogue",
    "load_goals",
    "load_inference",
    "load_narrator",
    "load_nlu",
    "load_pragmatics",
    "load_styles",
    "load_synthesis",
    "load_time",
    "merge_features",
    "merge_actions",
    "normalize_text",
    "predicate_id",
    "project_action",
    "project_actions",
    "projected_registry",
    "substitute",
    "tokenize",
]


def __getattr__(name: str):
    # Живой NLU импортируется лениво: ``campaign.cognition`` тянет
    # ``campaign.dialogue.morphology``, и ранний импорт дал бы цикл.
    if name in ("NluBackend", "NluReport", "load_nlu"):
        from ..cognition import nlu_backend

        value = getattr(nlu_backend, name)
        globals()[name] = value
        return value
    raise AttributeError(name)
