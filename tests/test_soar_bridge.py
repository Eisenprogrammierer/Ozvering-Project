"""Контракт моста ``soar_bridge.v1``."""

from __future__ import annotations

import pytest

from campaign.cognition import (
    BRIDGE_VERSION,
    BridgeError,
    BridgeRequest,
    BridgeResponse,
    command_digest,
    request_digest,
    validate_command,
    validate_request,
    validate_response,
)


def _request():
    return BridgeRequest(
        agent_id="npc:irina",
        tick=142,
        snapshot_version=3,
        input={
            "utterance": {"text": "Обними его.", "frame": {}},
            "world": {"location": "agora", "time": "day"},
            "self": {"needs": {"fear": 0.2}},
        },
    )


def test_request_roundtrip_and_digest():
    request = _request()
    data = request.to_dict()
    assert data["version"] == BRIDGE_VERSION
    assert validate_request(data) == request
    assert request_digest(request) == request_digest(
        validate_request(data)
    )


def test_request_rejects_bad_fields():
    with pytest.raises(BridgeError):
        BridgeRequest(agent_id="", tick=0, snapshot_version=0)
    with pytest.raises(BridgeError):
        BridgeRequest(agent_id="npc", tick=-1, snapshot_version=0)
    with pytest.raises(BridgeError):
        BridgeRequest(agent_id="npc", tick=0, snapshot_version=-1)
    with pytest.raises(BridgeError):
        validate_request(
            {
                "agent_id": "npc",
                "tick": 0,
                "snapshot_version": 0,
                "input": {},
                "extra": 1,
            }
        )
    with pytest.raises(BridgeError):
        validate_request(
            {
                "version": "soar_bridge.v0",
                "agent_id": "npc",
                "tick": 0,
                "snapshot_version": 0,
                "input": {},
            }
        )


def test_response_accepts_supported_commands():
    response = BridgeResponse(
        commands=(
            {
                "kind": "say",
                "id": "c1",
                "origin": "nlu-interpret-select-frame",
                "act": "answer",
                "content": {"text": "Я рядом."},
            },
            {
                "kind": "act",
                "id": "c2",
                "origin": "npc-propose-work-comfort",
                "action_id": "comfort_person",
                "target": "character:irina",
            },
            {
                "kind": "clarify",
                "id": "c3",
                "origin": "nlu-clarify",
                "options": ["faction:red", "faction:blue"],
            },
        ),
        trace={"operators": ["nlu-interpret-select-frame"]},
        timing_ms=3.2,
    )
    data = response.to_dict()
    assert validate_response(data) == response
    assert command_digest(response) == command_digest(
        validate_response(data)
    )


@pytest.mark.parametrize(
    "command",
    [
        {"kind": "shout", "id": "c", "origin": "x"},
        {"kind": "say", "id": "", "origin": "x", "act": "answer"},
        {"kind": "say", "id": "c", "origin": "", "act": "answer"},
        {"kind": "say", "id": "c", "origin": "x"},
        {"kind": "act", "id": "c", "origin": "x"},
        {"kind": "clarify", "id": "c", "origin": "x"},
        {"kind": "remember", "id": "c", "origin": "x", "key": "k"},
        {"kind": "order", "id": "c", "origin": "x"},
        {"kind": "move", "id": "c", "origin": "x"},
        {"kind": "wait", "id": "c", "origin": "x", "ticks": -1},
    ],
)
def test_invalid_commands_are_rejected(command):
    with pytest.raises(BridgeError):
        validate_command(command)


def test_response_rejects_negative_timing():
    with pytest.raises(BridgeError):
        BridgeResponse(commands=(), trace={}, timing_ms=-1)
