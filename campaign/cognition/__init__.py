"""Когнитивный фасад: понимание фразы и решения агентов.

Границы слоя:

* ``campaign/cognition`` — единственное место, где импортируются Soar и
  RiveScript;
* остальной код вызывает ``understand()`` / ``decide()`` и работает с
  JSON-контрактами;
* JSON остаётся источником истины, ``.soar`` и ``.rive`` — артефакты.

NLU: ``legacy`` (ChartParser), ``shadow`` (RiveScript рядом) и ``rive``.
Решения: ``legacy`` (NeedPolicy), ``shadow`` (Soar рядом) и ``soar``.
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

# Компилятор и рантайм вывода грузятся лениво: иначе запуск
# ``python -m campaign.cognition.inference_compiler`` (и соседних
# компиляторов) предупреждал бы о повторном импорте модуля.
_LAZY = {
    "InferenceModel": (".inference_compiler", "InferenceModel"),
    "ProofNode": (".inference_runtime", "ProofNode"),
    "SoarInference": (".inference_runtime", "SoarInference"),
    "check_inference": (".inference_compiler", "check_policy"),
    "compile_inference": (".inference_compiler", "compile_policy"),
    "load_inference_model": (".inference_compiler", "load_model"),
    "write_inference": (".inference_compiler", "write_policy"),
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
    "FrameError",
    "GoldenCorpus",
    "INFERENCE_BACKENDS",
    "InferenceModel",
    "LegacyNlu",
    "NLU_BACKENDS",
    "ParityReport",
    "ProofNode",
    "Rejection",
    "RiveError",
    "SoarError",
    "SoarInference",
    "UtteranceFrame",
    "available_nlu_backends",
    "check_inference",
    "command_digest",
    "compare",
    "compare_choices",
    "compile_inference",
    "decide",
    "default_config_path",
    "frame_confidence",
    "load_flags",
    "load_inference_model",
    "register_nlu_backend",
    "record_corpus",
    "request_digest",
    "result_core",
    "understand",
    "validate_command",
    "validate_request",
    "validate_response",
    "write_inference",
]
