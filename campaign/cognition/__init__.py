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
    "DecisionReport",
    "FRAME_VERSION",
    "FrameError",
    "GoldenCorpus",
    "LegacyNlu",
    "NLU_BACKENDS",
    "ParityReport",
    "Rejection",
    "RiveError",
    "SoarError",
    "UtteranceFrame",
    "available_nlu_backends",
    "command_digest",
    "compare",
    "compare_choices",
    "decide",
    "default_config_path",
    "frame_confidence",
    "load_flags",
    "register_nlu_backend",
    "record_corpus",
    "request_digest",
    "result_core",
    "understand",
    "validate_command",
    "validate_request",
    "validate_response",
]
