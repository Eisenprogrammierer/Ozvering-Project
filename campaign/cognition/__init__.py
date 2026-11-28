"""Когнитивный фасад: понимание фразы и решения агентов.

Границы слоя:

* ``campaign/cognition`` — единственное место, где импортируются Soar и
  RiveScript;
* остальной код вызывает ``understand()`` / ``decide()`` и работает с
  JSON-контрактами;
* JSON остаётся источником истины, ``.soar`` и ``.rive`` — артефакты.

NLU: ``legacy`` (ChartParser), ``shadow`` (RiveScript рядом) и ``rive``.
Решения: ``legacy`` (NeedPolicy и рулетка), ``shadow`` (Soar рядом) и
``soar``.
"""

from __future__ import annotations

from .backends import (
    AI_BACKENDS,
    DIALOGUE_BACKENDS,
    INFERENCE_BACKENDS,
    NLU_BACKENDS,
    CognitionFlags,
    default_config_path,
    load_flags,
)
from .corpus import CORPUS_VERSION, CorpusEntry, GoldenCorpus, record_corpus
from .errors import (
    BackendError,
    BridgeError,
    CognitionError,
    CorpusError,
    FrameError,
    RiveError,
    SnapshotError,
    SoarError,
)
from .frame import (
    CORE_FIELDS,
    FRAME_VERSION,
    Clarification,
    Rejection,
    UtteranceFrame,
    frame_confidence,
)
from .nlu import (
    LegacyNlu,
    available_nlu_backends,
    decide,
    register_nlu_backend,
    understand,
)
from .parity import (
    DecisionReport,
    ParityReport,
    compare,
    compare_choices,
    result_core,
)
from .soar_bridge import (
    BRIDGE_VERSION,
    COMMAND_KINDS,
    BridgeRequest,
    BridgeResponse,
    command_digest,
    request_digest,
    validate_command,
    validate_request,
    validate_response,
)
from .soar_snapshot import (
    SNAPSHOT_SCHEMA,
    SNAPSHOT_VERSION,
    STORE_SCHEMA,
    STORE_VERSION,
    SoarSnapshotStore,
    build_snapshot,
    create_wm,
    load_wm,
    validate_snapshot,
)

# Компилятор и рантайм вывода грузятся лениво: иначе запуск
# ``python -m campaign.cognition.inference_compiler`` (и соседних
# компиляторов) предупреждал бы о повторном импорте модуля.
_LAZY = {
    "FactionDecisionMonitor": (
        ".faction_runtime",
        "FactionDecisionMonitor",
    ),
    "FactionModel": (".faction_compiler", "FactionModel"),
    "InferenceModel": (".inference_compiler", "InferenceModel"),
    "IntentionModel": (".intention_compiler", "IntentionModel"),
    "IntentionMonitor": (".intention_runtime", "IntentionMonitor"),
    "NluBackend": (".nlu_backend", "NluBackend"),
    "NluReport": (".nlu_backend", "NluReport"),
    "load_nlu": (".nlu_backend", "load_nlu"),
    "ProofNode": (".inference_runtime", "ProofNode"),
    "ReactionDecisionMonitor": (
        ".reaction_runtime",
        "ReactionDecisionMonitor",
    ),
    "ReactionModel": (".reaction_compiler", "ReactionModel"),
    "SoarAgent": (".soar_runtime", "SoarAgent"),
    "SoarNpcAgent": (".soar_npc", "SoarNpcAgent"),
    "SoarNpcPool": (".soar_npc", "SoarNpcPool"),
    "bdi_memory": (".soar_npc", "bdi_memory"),
    "SoarFactionPolicy": (".faction_runtime", "SoarFactionPolicy"),
    "SoarInference": (".inference_runtime", "SoarInference"),
    "SoarIntention": (".intention_runtime", "SoarIntention"),
    "SoarIntentionPool": (".intention_runtime", "SoarIntentionPool"),
    "SoarReactionPolicy": (".reaction_runtime", "SoarReactionPolicy"),
    "check_faction": (".faction_compiler", "check_policy"),
    "check_inference": (".inference_compiler", "check_policy"),
    "check_intention": (".intention_compiler", "check_policy"),
    "check_reaction": (".reaction_compiler", "check_policy"),
    "compile_faction": (".faction_compiler", "compile_policy"),
    "compile_inference": (".inference_compiler", "compile_policy"),
    "compile_intention": (".intention_compiler", "compile_policy"),
    "compile_reaction": (".reaction_compiler", "compile_policy"),
    "faction_available": (".faction_runtime", "faction_available"),
    "intention_available": (".intention_runtime", "intention_available"),
    "intention_pool_report": (
        ".intention_runtime",
        "intention_pool_report",
    ),
    "load_faction_model": (".faction_compiler", "load_model"),
    "load_inference_model": (".inference_compiler", "load_model"),
    "load_intention_model": (".intention_compiler", "load_model"),
    "load_reaction_model": (".reaction_compiler", "load_model"),
    "reaction_available": (".reaction_runtime", "reaction_available"),
    "reaction_choice": (".reaction_runtime", "reaction_choice"),
    "roulette_choice": (".faction_runtime", "roulette_choice"),
    "shared_intention": (".intention_runtime", "shared_intention"),
    "write_faction": (".faction_compiler", "write_policy"),
    "write_inference": (".inference_compiler", "write_policy"),
    "write_intention": (".intention_compiler", "write_policy"),
    "write_reaction": (".reaction_compiler", "write_policy"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(name)
    from importlib import import_module

    value = getattr(import_module(target[0], __name__), target[1])
    globals()[name] = value
    return value


__all__ = [
    "AI_BACKENDS",
    "BRIDGE_VERSION",
    "BackendError",
    "BridgeError",
    "BridgeRequest",
    "BridgeResponse",
    "CORE_FIELDS",
    "COMMAND_KINDS",
    "CORPUS_VERSION",
    "Clarification",
    "CognitionError",
    "CognitionFlags",
    "CorpusEntry",
    "CorpusError",
    "DIALOGUE_BACKENDS",
    "DecisionReport",
    "FRAME_VERSION",
    "FactionDecisionMonitor",
    "FactionModel",
    "FrameError",
    "GoldenCorpus",
    "INFERENCE_BACKENDS",
    "InferenceModel",
    "IntentionModel",
    "IntentionMonitor",
    "LegacyNlu",
    "NLU_BACKENDS",
    "NluBackend",
    "NluReport",
    "ParityReport",
    "ProofNode",
    "ReactionDecisionMonitor",
    "ReactionModel",
    "Rejection",
    "RiveError",
    "SNAPSHOT_SCHEMA",
    "SNAPSHOT_VERSION",
    "STORE_SCHEMA",
    "STORE_VERSION",
    "SnapshotError",
    "SoarAgent",
    "SoarError",
    "SoarFactionPolicy",
    "SoarInference",
    "SoarIntention",
    "SoarIntentionPool",
    "SoarNpcAgent",
    "SoarNpcPool",
    "SoarReactionPolicy",
    "SoarSnapshotStore",
    "UtteranceFrame",
    "available_nlu_backends",
    "bdi_memory",
    "build_snapshot",
    "check_faction",
    "check_inference",
    "check_intention",
    "check_reaction",
    "command_digest",
    "compare",
    "compare_choices",
    "compile_faction",
    "compile_inference",
    "compile_intention",
    "compile_reaction",
    "create_wm",
    "decide",
    "default_config_path",
    "faction_available",
    "frame_confidence",
    "intention_available",
    "intention_pool_report",
    "load_faction_model",
    "load_flags",
    "load_inference_model",
    "load_intention_model",
    "load_nlu",
    "load_reaction_model",
    "load_wm",
    "reaction_available",
    "reaction_choice",
    "register_nlu_backend",
    "record_corpus",
    "request_digest",
    "result_core",
    "roulette_choice",
    "shared_intention",
    "understand",
    "validate_command",
    "validate_request",
    "validate_response",
    "validate_snapshot",
    "write_faction",
    "write_inference",
    "write_intention",
    "write_reaction",
]
