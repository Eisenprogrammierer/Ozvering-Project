"""Хранилища диалогового состояния: память и снимки по собеседникам.

Модуль отделён от ``state.py``, чтобы активные модули оставались в
бюджете строк. Зависимость односторонняя: ``stores`` импортирует
``DialogueMemory`` и вспомогательные функции из ``state``, обратного
импорта нет.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping

from .errors import DialogueError
from .state import (
    STATE_SCHEMA,
    DialogueMemory,
    _integer,
    _mapping,
    _text,
)


class DialogueMemoryStore:
    """Память по агентам в рамках одной партии.

    Каждый собеседник имеет собственный след разговора: один агент не
    должен помнить то, что игрок сказал другому. Хранилище целиком лежит
    в сейве партии, поэтому новая игра начинается с пустой памяти.
    """

    SCHEMA = 1

    def __init__(
        self,
        policy: Mapping[str, Any],
        data: Any = None,
    ):
        self.policy = policy
        self.agents: Dict[str, DialogueMemory] = {}
        raw = _mapping(data)
        for agent_id, item in _mapping(raw.get("agents")).items():
            self.agents[str(agent_id)] = DialogueMemory.from_dict(policy, item)

    @classmethod
    def from_dict(
        cls, policy: Mapping[str, Any], data: Any
    ) -> "DialogueMemoryStore":
        return cls(policy, data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "agents": {
                key: memory.to_dict()
                for key, memory in sorted(self.agents.items())
            },
        }

    def memory(
        self,
        agent_id: str,
        run_id: str = "",
        clock: int = 0,
    ) -> DialogueMemory:
        key = _text(agent_id) or "agent"
        memory = self.agents.get(key)
        if memory is None or (run_id and memory.run_id != run_id):
            memory = DialogueMemory(self.policy, run_id=run_id, clock=clock)
            self.agents[key] = memory
        memory.observe_clock(clock)
        return memory


class DialogueStateStore:
    """Снимки текущего разговора по собеседникам.

    Память (``DialogueMemoryStore``) хранит долговременный след, а это
    хранилище — QUD, референты, обязательства и последний смысл каждого
    собеседника. Оба попадают в сейв партии под ключом ``dialogue``.
    """

    SCHEMA = STATE_SCHEMA

    def __init__(self, data: Any = None):
        raw = _mapping(data)
        schema = _integer(raw.get("schema"), self.SCHEMA)
        if schema > self.SCHEMA:
            raise DialogueError(
                "снимок состояний диалога новее этой сборки: %d > %d"
                % (schema, self.SCHEMA)
            )
        if schema < 1:
            raise DialogueError(
                "неизвестная версия снимка состояний диалога: %r" % schema
            )
        self.states: Dict[str, Dict[str, Any]] = {}
        for agent_id, item in _mapping(raw.get("agents")).items():
            if isinstance(item, Mapping) and item:
                self.states[str(agent_id)] = dict(item)

    @classmethod
    def from_dict(cls, data: Any) -> "DialogueStateStore":
        return cls(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "agents": {
                key: dict(self.states[key]) for key in sorted(self.states)
            },
        }

    def save(self, agent_id: str, state: Any) -> None:
        key = _text(agent_id) or "agent"
        data = (
            state.to_dict()
            if hasattr(state, "to_dict")
            else dict(_mapping(state))
        )
        if data:
            self.states[key] = data

    def load(self, agent_id: str) -> Dict[str, Any]:
        key = _text(agent_id) or "agent"
        return copy.deepcopy(self.states.get(key) or {})

    def clear(self) -> None:
        self.states.clear()


__all__ = [
    "DialogueMemoryStore",
    "DialogueStateStore",
]
