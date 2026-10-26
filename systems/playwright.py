"""Драматург — системный автомат, который искушает акторов.

Драматург не управляет персонажами напрямую. Он периодически (эпизодически)
оценивает доступные драматические действия и стохастически выбирает одно,
подталкивая актора к поступку. Оценка складывается из четырёх компонентов:

* **неопределённость** — насколько исход непредсказуем;
* **связность** — насколько поступок вытекает из характера и контекста;
* **новизна** — насколько поступок отличается от недавних толчков;
* **ставки** — насколько высока цена ошибки.

Чем выше итоговая оценка, тем охотнее драматург выбирает действие. Выбор идёт
через softmax-температуру, поэтому это именно соблазн, а не жёсткий диктат.

Слой чистый: он не импортирует pygame, ``simulation`` или ``warfare``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import random
from typing import Dict, List, Mapping, Optional, Tuple

from automata.model import Automaton, State, Transition

from .core import SystemAutomaton, SystemError, as_float, as_int, clamp

try:  # импорт типа не обязателен для расчёта, но нужен для текста
    from .events import EventError, EventTextGenerator
except Exception:  # pragma: no cover - защита от частичной установки
    EventError = Exception
    EventTextGenerator = None


WEIGHT_KEYS = ("uncertainty", "coherence", "novelty", "stakes")


class PlaywrightError(SystemError):
    """Ошибка конфигурации или работы драматурга."""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise PlaywrightError("конфиг не найден: %s" % path)
    except Exception as exc:
        raise PlaywrightError("не удалось прочитать %s: %s" % (path, exc))


def _tags(value):
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        value = [value]
    return tuple(str(item).strip() for item in value if str(item).strip())


def _relationship_items(value):
    if value is None:
        return ()
    if isinstance(value, Mapping):
        items = value.items()
    else:
        items = value
    result = []
    for item in items:
        if isinstance(item, Mapping):
            target = item.get("target") or item.get("id")
            weight = item.get("weight", item.get("stake", 0.5))
        else:
            try:
                target, weight = item
            except (TypeError, ValueError):
                continue
        target = str(target or "").strip()
        if target:
            result.append((target, clamp(weight, 0.0, 1.0)))
    return tuple(result)


@dataclass(frozen=True)
class DramaActor:
    """Актор, которого драматург может подтолкнуть к поступку."""

    id: str
    name: str
    organization: str = ""
    tags: Tuple[str, ...] = ()
    stakes: float = 0.5
    traits: Tuple[str, ...] = ()
    relationships: Tuple[Tuple[str, float], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "id", str(self.id or "").strip())
        object.__setattr__(self, "name", str(self.name or self.id).strip())
        object.__setattr__(self, "organization",
                           str(self.organization or "").strip())
        object.__setattr__(self, "tags", _tags(self.tags))
        object.__setattr__(self, "traits", _tags(self.traits))
        object.__setattr__(self, "relationships",
                           _relationship_items(self.relationships))
        object.__setattr__(self, "stakes", clamp(self.stakes, 0.0, 1.0))
        if not self.id:
            raise PlaywrightError("у актора должен быть id")

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, Mapping):
            raise PlaywrightError("актор должен быть объектом")
        return cls(
            id=data.get("id"),
            name=data.get("name") or data.get("id"),
            organization=data.get("organization") or "",
            tags=_tags(data.get("tags")),
            stakes=data.get("stakes", 0.5),
            traits=_tags(data.get("traits")),
            relationships=data.get("relationships") or (),
        )

    @classmethod
    def from_character(cls, character, organization="", stakes=None):
        """Адаптер для ``warfare.Character`` без импорта warfare."""
        name = str(getattr(character, "name", "") or
                   getattr(character, "id", "") or "безымянный")
        actor_id = str(getattr(character, "id", "") or name)
        role = str(getattr(character, "role", "") or "")
        side = str(getattr(character, "side", "") or "")
        tags = [item for item in (role, side) if item]
        if stakes is None:
            needs = getattr(character, "needs", {}) or {}
            if isinstance(needs, Mapping) and needs:
                try:
                    stakes = max(float(value) for value in needs.values())
                except (TypeError, ValueError):
                    stakes = 0.5
            else:
                stakes = 0.5
        return cls(
            id=actor_id,
            name=name,
            organization=organization or side,
            tags=tags,
            stakes=stakes,
        )

    @property
    def label(self):
        return self.name or self.id

    def relationship(self, actor_id):
        for target, weight in self.relationships:
            if target == actor_id:
                return weight
        return 0.0

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "organization": self.organization,
            "tags": list(self.tags),
            "stakes": self.stakes,
            "traits": list(self.traits),
            "relationships": [{"target": key, "weight": value}
                              for key, value in self.relationships],
        }

    def __str__(self):
        return self.label


@dataclass(frozen=True)
class DramaticAction:
    """Кандидат на драматический поступок."""

    id: str
    actor_id: str
    target_id: str
    action: str
    description: str = ""
    tags: Tuple[str, ...] = ()
    event_id: str = ""
    uncertainty: float = 0.5
    coherence: float = 0.5
    novelty: float = 0.5
    stakes: float = 0.5

    def __post_init__(self):
        object.__setattr__(self, "id", str(self.id or "").strip())
        object.__setattr__(self, "actor_id", str(self.actor_id or "").strip())
        object.__setattr__(self, "target_id", str(self.target_id or "").strip())
        object.__setattr__(self, "action", str(self.action or self.id).strip())
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "tags", _tags(self.tags))
        object.__setattr__(self, "event_id", str(self.event_id or "").strip())
        object.__setattr__(self, "uncertainty",
                           clamp(self.uncertainty, 0.0, 1.0))
        object.__setattr__(self, "coherence", clamp(self.coherence, 0.0, 1.0))
        object.__setattr__(self, "novelty", clamp(self.novelty, 0.0, 1.0))
        object.__setattr__(self, "stakes", clamp(self.stakes, 0.0, 1.0))
        if not self.id:
            raise PlaywrightError("у драматического действия должен быть id")
        if not self.actor_id:
            raise PlaywrightError("%s: нет actor_id" % self.id)

    @property
    def involved(self):
        return (self.actor_id, self.target_id)

    def as_dict(self):
        return {
            "id": self.id,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "action": self.action,
            "description": self.description,
            "tags": list(self.tags),
            "event_id": self.event_id,
            "uncertainty": self.uncertainty,
            "coherence": self.coherence,
            "novelty": self.novelty,
            "stakes": self.stakes,
        }


@dataclass(frozen=True)
class DramaticTemplate:
    """Шаблон действия, из которого рождаются кандидаты."""

    id: str
    label: str
    action: str
    description: str = ""
    tags: Tuple[str, ...] = ()
    event_id: str = ""
    uncertainty: float = 0.5
    coherence: float = 0.5
    novelty: float = 0.5
    stakes: float = 0.5

    @classmethod
    def from_data(cls, data, index=0):
        if not isinstance(data, Mapping):
            raise PlaywrightError("template[%d] должен быть объектом" % index)
        template_id = str(data.get("id") or "").strip()
        if not template_id:
            raise PlaywrightError("template[%d]: пустой id" % index)
        return cls(
            id=template_id,
            label=str(data.get("label") or template_id),
            action=str(data.get("action") or data.get("label") or template_id),
            description=str(data.get("description") or ""),
            tags=_tags(data.get("tags")),
            event_id=str(data.get("event_id") or "").strip(),
            uncertainty=clamp(data.get("uncertainty", 0.5), 0.0, 1.0),
            coherence=clamp(data.get("coherence", 0.5), 0.0, 1.0),
            novelty=clamp(data.get("novelty", 0.5), 0.0, 1.0),
            stakes=clamp(data.get("stakes", 0.5), 0.0, 1.0),
        )

    def candidate(self, actor, target, suffix=None):
        actor_id = actor.id if isinstance(actor, DramaActor) else str(actor)
        target_id = target.id if isinstance(target, DramaActor) else str(target)
        return DramaticAction(
            id="%s:%s:%s" % (self.id, actor_id, target_id) if suffix is None
            else str(suffix),
            actor_id=actor_id,
            target_id=target_id,
            action=self.action,
            description=self.description,
            tags=self.tags,
            event_id=self.event_id,
            uncertainty=self.uncertainty,
            coherence=self.coherence,
            novelty=self.novelty,
            stakes=self.stakes,
        )

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "action": self.action,
            "description": self.description,
            "tags": list(self.tags),
            "event_id": self.event_id,
            "uncertainty": self.uncertainty,
            "coherence": self.coherence,
            "novelty": self.novelty,
            "stakes": self.stakes,
        }


@dataclass(frozen=True)
class DramaScore:
    """Разложенная по компонентам оценка соблазна."""

    uncertainty: float
    coherence: float
    novelty: float
    stakes: float
    total: float
    weights: Dict[str, float] = field(default_factory=dict)

    @property
    def components(self):
        return {
            "uncertainty": self.uncertainty,
            "coherence": self.coherence,
            "novelty": self.novelty,
            "stakes": self.stakes,
        }

    def as_dict(self):
        result = dict(self.components)
        result["total"] = self.total
        result["weights"] = dict(self.weights)
        return result


@dataclass
class DramaPush:
    """Свершившийся толчок драматурга."""

    turn: int
    candidate: DramaticAction
    score: DramaScore
    state_before: str
    state_after: str
    event: Optional[object] = None
    reason: str = ""

    @property
    def text(self):
        if self.event is not None:
            return str(getattr(self.event, "text", self.event))
        return "%s: %s" % (self.candidate.actor_id, self.candidate.action)

    def as_dict(self):
        return {
            "turn": self.turn,
            "candidate": self.candidate.as_dict(),
            "score": self.score.as_dict(),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "text": self.text,
            "event": (self.event.as_dict()
                      if hasattr(self.event, "as_dict") else None),
            "reason": self.reason,
        }


@dataclass
class PlaywrightConfig:
    """Веса, ритм эпизодов и шаблоны соблазна."""

    weights: Dict[str, float] = field(default_factory=lambda: {
        "uncertainty": 0.28,
        "coherence": 0.24,
        "novelty": 0.26,
        "stakes": 0.22,
    })
    episode_chance: float = 0.35
    cooldown: int = 3
    temperature: float = 0.35
    novelty_decay: float = 0.55
    repetition_penalty: float = 0.60
    min_score: float = 0.15
    exploration: float = 0.05
    max_candidates: int = 32
    templates: Tuple[DramaticTemplate, ...] = ()

    @classmethod
    def load(cls, root=None):
        root = Path(root) if root is not None else default_root()
        return cls.from_data(_read_json(root / "playwright.json"))

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, Mapping):
            raise PlaywrightError("playwright.json должен быть объектом")
        raw_weights = data.get("weights") or {}
        if not isinstance(raw_weights, Mapping):
            raise PlaywrightError("weights должен быть объектом")
        weights = {}
        for key in WEIGHT_KEYS:
            weights[key] = max(0.0, as_float(raw_weights.get(key, 0.0), 0.0))
        if sum(weights.values()) <= 0.0:
            raise PlaywrightError("сумма weights должна быть больше нуля")
        total = sum(weights.values())
        weights = {key: value / total for key, value in weights.items()}
        templates = tuple(
            DramaticTemplate.from_data(item, number)
            for number, item in enumerate(data.get("templates") or ())
        )
        if len({item.id for item in templates}) != len(templates):
            raise PlaywrightError("повторяются id шаблонов драматурга")
        return cls(
            weights=weights,
            episode_chance=clamp(data.get("episode_chance", 0.35), 0.0, 1.0),
            cooldown=max(0, as_int(data.get("cooldown", 3), 3)),
            temperature=max(0.01, as_float(data.get("temperature", 0.35),
                                          0.35)),
            novelty_decay=clamp(data.get("novelty_decay", 0.55), 0.0, 1.0),
            repetition_penalty=clamp(
                data.get("repetition_penalty", 0.60), 0.0, 1.0),
            min_score=clamp(data.get("min_score", 0.15), 0.0, 1.0),
            exploration=clamp(data.get("exploration", 0.05), 0.0, 1.0),
            max_candidates=max(1, as_int(data.get("max_candidates", 32), 32)),
            templates=templates,
        )

    def as_dict(self):
        return {
            "weights": dict(self.weights),
            "episode_chance": self.episode_chance,
            "cooldown": self.cooldown,
            "temperature": self.temperature,
            "novelty_decay": self.novelty_decay,
            "repetition_penalty": self.repetition_penalty,
            "min_score": self.min_score,
            "exploration": self.exploration,
            "max_candidates": self.max_candidates,
            "templates": [item.as_dict() for item in self.templates],
        }


def _actor_map(actors):
    if actors is None:
        return {}
    if isinstance(actors, Mapping):
        items = actors.items()
    else:
        items = ((item.id if isinstance(item, DramaActor)
                  else getattr(item, "id", item), item) for item in actors)
    result = {}
    for key, item in items:
        if isinstance(item, DramaActor):
            result[item.id] = item
        else:
            result[str(key)] = item
    return result


def _actor_name(actor, fallback):
    if actor is None:
        return fallback
    return str(getattr(actor, "name", None) or
               getattr(actor, "label", None) or fallback)


def _actor_organization(actor):
    if actor is None:
        return ""
    return str(getattr(actor, "organization", "") or "")


class Playwright:
    """Системный автомат-драматург."""

    def __init__(self, config: Optional[PlaywrightConfig] = None, seed=0,
                 event_generator=None):
        self.config = config or PlaywrightConfig.load()
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.event_generator = event_generator
        self.cooldown = 0
        self.history: List[tuple] = []
        self.pushes: List[DramaPush] = []
        self.machine = SystemAutomaton(
            "playwright", "Драматург", _build_automaton())

    # --- оценка ---------------------------------------------------------
    def _similarity(self, candidate: DramaticAction):
        recent = self.history[-8:]
        if not recent:
            return 0.0
        exact = 1.0 if any(item[0].id == candidate.id for item in recent) \
            else 0.0
        tag_scores = []
        actor_reuse = 0.0
        target_reuse = 0.0
        for item, _ in recent:
            old = item
            old_tags = set(old.tags)
            new_tags = set(candidate.tags)
            if old_tags or new_tags:
                union = old_tags | new_tags
                tag_scores.append(len(old_tags & new_tags) / len(union)
                                  if union else 0.0)
            if old.actor_id == candidate.actor_id:
                actor_reuse += 1.0
            if old.target_id and old.target_id == candidate.target_id:
                target_reuse += 1.0
        tag_score = max(tag_scores) if tag_scores else 0.0
        actor_reuse /= len(recent)
        target_reuse /= len(recent)
        return clamp(max(exact, 0.75 * tag_score +
                         0.15 * actor_reuse + 0.10 * target_reuse))

    def score(self, candidate: DramaticAction, actors=None):
        actor_map = _actor_map(actors)
        actor = actor_map.get(candidate.actor_id)
        target = actor_map.get(candidate.target_id)

        uncertainty = clamp(candidate.uncertainty, 0.0, 1.0)
        coherence = clamp(candidate.coherence, 0.0, 1.0)
        novelty_base = clamp(candidate.novelty, 0.0, 1.0)
        stakes_base = clamp(candidate.stakes, 0.0, 1.0)

        if actor is not None or target is not None:
            actor_stake = float(getattr(actor, "stakes", 0.5)) \
                if actor is not None else 0.5
            target_stake = float(getattr(target, "stakes", 0.5)) \
                if target is not None else 0.5
            stakes = clamp(0.55 * stakes_base +
                           0.45 * max(actor_stake, target_stake), 0.0, 1.0)
        else:
            stakes = stakes_base

        similarity = self._similarity(candidate)
        exact = 1.0 if any(item[0].id == candidate.id
                           for item in self.history[-8:]) else 0.0
        novelty = clamp(
            novelty_base *
            (1.0 - self.config.novelty_decay * similarity) *
            (1.0 - self.config.repetition_penalty * exact),
            0.0, 1.0,
        )
        components = {
            "uncertainty": uncertainty,
            "coherence": coherence,
            "novelty": novelty,
            "stakes": stakes,
        }
        total = sum(self.config.weights[key] * components[key]
                    for key in WEIGHT_KEYS)
        return DramaScore(
            uncertainty=uncertainty,
            coherence=coherence,
            novelty=novelty,
            stakes=stakes,
            total=clamp(total, 0.0, 1.0),
            weights=dict(self.config.weights),
        )

    def score_candidates(self, candidates, actors=None):
        scored = [(candidate, self.score(candidate, actors))
                  for candidate in candidates]
        return sorted(scored, key=lambda item: item[1].total, reverse=True)

    def choose(self, candidates, actors=None, rng=None):
        scored = self.score_candidates(candidates, actors)
        scored = [item for item in scored
                  if item[1].total >= self.config.min_score]
        if not scored:
            return None, None
        rng = rng or self.rng
        if self.config.exploration > 0.0 and rng.random() < \
                self.config.exploration:
            candidate, score = rng.choice(scored)
            return candidate, score
        best = max(item[1].total for item in scored)
        temperature = max(0.01, self.config.temperature)
        weights = [
            math.exp((score.total - best) / temperature)
            for _, score in scored
        ]
        total = sum(weights)
        if total <= 0.0:
            candidate, score = scored[0]
            return candidate, score
        roll = rng.random() * total
        cursor = 0.0
        for (candidate, score), weight in zip(scored, weights):
            cursor += weight
            if roll <= cursor:
                return candidate, score
        candidate, score = scored[-1]
        return candidate, score

    # --- ритм и толчок --------------------------------------------------
    def tick(self, turn, actors=None, candidates=None, seed=None):
        """Сделать один такт. Возвращает ``DramaPush`` или ``None``."""
        rng = self.rng if seed is None else random.Random(int(seed))
        if self.machine.current == "withdrawing":
            self.machine.fire("затишье")
        if self.cooldown > 0:
            self.cooldown -= 1
            return None

        if not candidates:
            return None
        if rng.random() >= self.config.episode_chance:
            return None

        state_before = self.machine.current
        self.machine.fire("эпизод")
        candidate, score = self.choose(candidates, actors=actors, rng=rng)
        if candidate is None or score is None:
            self.machine.fire("нет кандидата")
            return None
        self.machine.fire("кандидат найден")
        self.machine.fire("толчок")
        self.machine.fire("последствие")
        self.cooldown = self.config.cooldown
        state_after = self.machine.current
        event = None
        if self.event_generator is not None:
            event = self._render_event(candidate, actors, rng)
        push = DramaPush(
            turn=int(turn),
            candidate=candidate,
            score=score,
            state_before=state_before,
            state_after=state_after,
            event=event,
            reason=_score_reason(score),
        )
        actor_map = _actor_map(actors)
        self.history.append((candidate, score))
        self.history = self.history[-100:]
        self.pushes.append(push)
        self.pushes = self.pushes[-200:]
        return push

    def _render_event(self, candidate, actors, rng):
        generator = self.event_generator
        if generator is None or EventTextGenerator is None:
            return None
        actor_map = _actor_map(actors)
        actor = actor_map.get(candidate.actor_id)
        target = actor_map.get(candidate.target_id)
        actor_name = _actor_name(actor, candidate.actor_id)
        target_name = _actor_name(target, candidate.target_id)
        actor_org = _actor_organization(actor)
        target_org = _actor_organization(target)
        context = {
            "actor": actor_name,
            "target": target_name,
            "rival": target_name,
            "organization": actor_org or "безымянная организация",
            "rival_organization": target_org or "соперники",
            "action": candidate.action,
        }
        seed = rng.randrange(2 ** 31)
        try:
            if candidate.event_id:
                return generator.render(candidate.event_id,
                                        context=context, seed=seed)
            return generator.generate(tags=candidate.tags,
                                      context=context, seed=seed)
        except EventError:
            return None
        except Exception:
            return None

    # --- кандидаты из шаблонов -----------------------------------------
    def spawn_candidates(self, actors, templates=None):
        """Построить кандидатов из шаблонов и списка акторов."""
        actor_map = _actor_map(actors)
        ordered = [actor_map[key] for key in sorted(actor_map)]
        templates = tuple(templates or self.config.templates)
        if len(ordered) < 2 or not templates:
            return []
        result = []
        for index, actor in enumerate(ordered):
            others = [item for item in ordered if item.id != actor.id]
            if not others:
                continue
            for number, template in enumerate(templates):
                target = others[(index + number) % len(others)]
                result.append(template.candidate(actor, target))
                if len(result) >= self.config.max_candidates:
                    return result
        return result

    def available_templates(self):
        return tuple(self.config.templates)

    def reset(self):
        self.rng = random.Random(self.seed)
        self.cooldown = 0
        self.history = []
        self.pushes = []
        initial = self.machine.automaton.initial_states
        if initial:
            self.machine.set_state(initial[0].id)

    def snapshot(self):
        return {
            "seed": self.seed,
            "state": self.machine.current,
            "state_name": self.machine.state_name(),
            "cooldown": self.cooldown,
            "config": self.config.as_dict(),
            "history": [
                {"candidate": candidate.as_dict(),
                 "score": score.as_dict()}
                for candidate, score in self.history
            ],
            "pushes": [push.as_dict() for push in self.pushes],
        }


def _score_reason(score):
    parts = sorted(score.components.items(),
                   key=lambda item: item[1], reverse=True)
    names = {
        "uncertainty": "неопределённость",
        "coherence": "связность",
        "novelty": "новизна",
        "stakes": "ставки",
    }
    leading = ", ".join("%s %.2f" % (names[key], value)
                        for key, value in parts[:2])
    return "ведущие мотивы: %s" % leading


def _build_automaton():
    states = [
        State("dormant", "Спит", x=80, y=100, initial=True),
        State("watching", "Наблюдает", x=280, y=100),
        State("tempting", "Искушает", x=480, y=100),
        State("pushing", "Толкает", x=680, y=100),
        State("withdrawing", "Отступает", x=680, y=260),
    ]
    transitions = [
        Transition("t_episode", "dormant", "watching", "эпизод"),
        Transition("t_candidate", "watching", "tempting", "кандидат найден"),
        Transition("t_push", "tempting", "pushing", "толчок"),
        Transition("t_aftermath", "pushing", "withdrawing", "последствие"),
        Transition("t_sleep", "withdrawing", "dormant", "затишье"),
        Transition("t_skip_candidate", "watching", "dormant", "нет кандидата"),
    ]
    return Automaton("Драматург", "Эпизодический соблазнитель акторов",
                     states=states, transitions=transitions)


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "systems"


_DEFAULT_CONFIG = None


def default_config():
    global _DEFAULT_CONFIG
    if _DEFAULT_CONFIG is None:
        _DEFAULT_CONFIG = PlaywrightConfig.load()
    return _DEFAULT_CONFIG


__all__ = [
    "PlaywrightError", "DramaActor", "DramaticAction", "DramaticTemplate",
    "DramaScore", "DramaPush", "PlaywrightConfig", "Playwright",
    "default_config", "default_root",
]
