"""RL-предпочтения Soar: обучение на эпизодах и сравнение с NeedPolicy.

Модуль не принимает игровых решений сам по себе. Он обучает
RL-шаблон Soar на записанных эпизодах ``(контекст, кандидаты, выбор,
награда)``, строит таблицу «контекст → действие» и сравнивает её с
выбором, который записан в эпизодах (решение ``NeedPolicy``). Только
после прохождения порогов сравнения таблицу можно включить в игру.

Почему эпизоды, а не живой цикл: награда в кампании — это изменение
удовлетворённости нужд за ход, а оно известно только после хода.
Soar RL обновляет значения при остановке агента, поэтому один эпизод —
это один ход: ``init-soar`` → выбор → награда → ``halt``.

Детерминизм: порядок эпизодов фиксирован, ``srand`` выставляется от
seed кампании и номера эпизода, проверка идёт с ``epsilon=0``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .errors import BackendError, SoarError
from .rl_compiler import (
    DEFAULT_SOAR_DIR,
    MODEL_NAME,
    RlModel,
    load_model,
)
from .soar_runtime import (
    _kernel,
    _new_agent,
    _prepare_agent,
    soar_available,
)

RL_VERSION = 1
CHOSEN_PATTERN = re.compile(r"\^chosen\s+([^\s)]+)")
DEFAULT_TRAIN_EPSILON = 0.1
DEFAULT_TRAIN_RATIO = 0.7
PROBE_SEED_OFFSET = 100000


def _text(value: Any, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BackendError("%s не может быть пустым" % name)
    return result


def _reward(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BackendError("reward должен быть числом") from exc
    if not math.isfinite(result):
        raise BackendError("reward должен быть конечным числом")
    return result


@dataclass(frozen=True)
class RlEpisode:
    """Один записанный выбор: состояние, кандидаты, действие, награда."""

    context: str
    candidates: tuple
    chosen: str
    reward: float

    def __post_init__(self):
        context = _text(self.context, "context")
        candidates = tuple(
            _text(item, "candidate") for item in self.candidates
        )
        if not candidates:
            raise BackendError("у эпизода нет кандидатов")
        if len(set(candidates)) != len(candidates):
            raise BackendError("кандидаты эпизода повторяются")
        chosen = _text(self.chosen, "chosen")
        if chosen not in candidates:
            raise BackendError(
                "chosen=%r отсутствует среди кандидатов" % chosen
            )
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "chosen", chosen)
        object.__setattr__(self, "reward", _reward(self.reward))

    def as_dict(self) -> dict:
        return {
            "context": self.context,
            "candidates": list(self.candidates),
            "chosen": self.chosen,
            "reward": round(self.reward, 6),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RlEpisode":
        if not isinstance(data, Mapping):
            raise BackendError("эпизод RL должен быть объектом")
        return cls(
            context=data.get("context"),
            candidates=data.get("candidates") or (),
            chosen=data.get("chosen"),
            reward=data.get("reward", 0.0),
        )


def normalise_episodes(
    items: Iterable[Any],
) -> List[RlEpisode]:
    """Привести словари и ``RlEpisode`` к одному списку."""

    result: List[RlEpisode] = []
    for item in items or ():
        if isinstance(item, RlEpisode):
            result.append(item)
        else:
            result.append(RlEpisode.from_dict(item))
    return result


class SoarRlTrainer:
    """Эпизодическое обучение RL-шаблона Soar."""

    def __init__(
        self,
        *,
        model: Optional[RlModel] = None,
        source_dir: Path = DEFAULT_SOAR_DIR,
        policy_path: Optional[Path] = None,
        seed: int = 0,
        epsilon: float = DEFAULT_TRAIN_EPSILON,
        max_candidates: Optional[int] = None,
    ):
        self.model = model or load_model(
            Path(source_dir) / MODEL_NAME
        )
        self.path = Path(policy_path) if policy_path else (
            Path(source_dir) / "rl.soar"
        )
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "нет сгенерированной RL-политики: %s. "
                "Запустите python -m campaign.cognition."
                "rl_compiler --write" % self.path
            ) from exc
        self.seed = int(seed)
        self.epsilon = min(1.0, max(0.0, float(epsilon)))
        self.max_candidates = int(
            max_candidates or self.model.max_candidates
        )
        self.queries = 0
        self.errors = 0
        self.trained = 0
        self.elapsed_ms = 0.0
        self._agent: Any = None

    def _agent_for(self) -> Any:
        if self._agent is None:
            agent = _new_agent()
            try:
                _prepare_agent(agent, self.model, self.text)
            except Exception:
                _kernel().DestroyAgent(agent)
                raise
            self._agent = agent
        return self._agent

    def close(self) -> None:
        if self._agent is not None:
            _kernel().DestroyAgent(self._agent)
            self._agent = None

    def _run(
        self,
        context: str,
        candidates: Sequence[str],
        *,
        reward: float = 0.0,
        chosen: Optional[str] = None,
        seed: int = 0,
    ) -> str:
        """Один эпизод; возвращает действие, выбранное Soar."""

        names = [str(item) for item in candidates]
        if not names:
            raise BackendError("эпизод RL без кандидатов")
        if len(names) > self.max_candidates:
            raise BackendError(
                "кандидатов %d больше предела %d"
                % (len(names), self.max_candidates)
            )
        learning = chosen is not None
        started = time.perf_counter()
        agent = self._agent_for()
        self.queries += 1
        try:
            agent.ExecuteCommandLine("init-soar")
            epsilon = self.epsilon if learning else 0.0
            for command in self.model.commands(
                epsilon=epsilon, seed=seed
            ):
                agent.ExecuteCommandLine(command)
            link = agent.GetInputLink()
            agent.CreateStringWME(link, "context", str(context))
            agent.CreateFloatWME(link, "reward", float(reward))
            if learning:
                agent.CreateStringWME(link, "chosen", str(chosen))
            for name in names:
                node = agent.CreateIdWME(link, "candidate")
                agent.CreateStringWME(node, "name", name)
            agent.SynchronizeInputLink()
            agent.RunSelf(self.model.decision_cycles)
            text = agent.ExecuteCommandLine("print S1 --depth 2")
        except SoarError:
            self.errors += 1
            raise
        except Exception as exc:
            self.errors += 1
            raise SoarError(
                "RL-эпизод Soar завершился ошибкой: %s" % exc
            ) from exc
        finally:
            self.elapsed_ms += (
                time.perf_counter() - started
            ) * 1000.0
        match = CHOSEN_PATTERN.search(text or "")
        if match is None:
            self.errors += 1
            raise SoarError(
                "Soar не зафиксировал выбор RL-эпизода: %s"
                % (text or "")[:200]
            )
        result = match.group(1)
        if result not in names:
            self.errors += 1
            raise SoarError(
                "Soar выбрал неизвестное действие %r" % result
            )
        return result

    def train(self, episodes: Iterable[RlEpisode]) -> int:
        """Обучить шаблон; возвращает число эпизодов."""

        items = list(episodes)
        for index, episode in enumerate(items):
            self._run(
                episode.context,
                episode.candidates,
                reward=episode.reward,
                chosen=episode.chosen,
                seed=self.seed + index,
            )
        self.trained += len(items)
        return len(items)

    def probe(
        self,
        context: str,
        candidates: Sequence[str],
        *,
        seed: int = 0,
    ) -> Optional[str]:
        """Проверить выученную таблицу без обновления значений."""

        try:
            return self._run(context, candidates, seed=seed)
        except SoarError:
            return None

    def learn_policy(
        self, episodes: Iterable[RlEpisode]
    ) -> Dict[str, str]:
        """Построить таблицу «контекст → лучшее из опробованных действий»."""

        items = list(episodes)
        contexts: Dict[str, List[str]] = {}
        for episode in items:
            actions = contexts.setdefault(episode.context, [])
            if episode.chosen not in actions:
                actions.append(episode.chosen)
        table: Dict[str, str] = {}
        for index, context in enumerate(sorted(contexts)):
            actions = sorted(contexts[context])
            action = self.probe(
                context,
                actions,
                seed=self.seed + PROBE_SEED_OFFSET + index,
            )
            if action in actions:
                table[context] = action
        return table

    def report(self) -> Dict[str, Any]:
        return {
            "trained": self.trained,
            "queries": self.queries,
            "errors": self.errors,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "seed": self.seed,
            "epsilon": self.epsilon,
        }


class SoarRlPolicy:
    """Таблица выученных предпочтений: контекст → действие."""

    def __init__(
        self,
        policy: Optional[Mapping[str, Any]] = None,
        *,
        version: int = RL_VERSION,
    ):
        self.version = int(version)
        if self.version != RL_VERSION:
            raise BackendError(
                "версия RL-политики %r не поддерживается"
                % (self.version,)
            )
        self.policy = {
            str(key): str(value)
            for key, value in dict(policy or {}).items()
        }

    def choose(
        self, context: Any, candidates: Iterable[Any]
    ) -> Optional[str]:
        action = self.policy.get(str(context))
        if action is None:
            return None
        names = {str(item) for item in candidates or ()}
        return action if action in names else None

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "policy": dict(sorted(self.policy.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SoarRlPolicy":
        if not isinstance(data, Mapping):
            raise BackendError("RL-политика должна быть объектом")
        return cls(
            data.get("policy") or {},
            version=int(data.get("version", RL_VERSION)),
        )

    @classmethod
    def from_report(cls, report: Mapping[str, Any]) -> "SoarRlPolicy":
        return cls((report or {}).get("policy") or {})


def _config_number(
    config: Mapping[str, Any], key: str, default: Any
) -> float:
    value = (config or {}).get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BackendError("rl.%s должен быть числом" % key) from exc


def _config_integer(
    config: Mapping[str, Any], key: str, default: int
) -> int:
    value = (config or {}).get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BackendError("rl.%s должен быть целым" % key) from exc


def compare_episodes(
    episodes: Iterable[Any],
    *,
    model: Optional[RlModel] = None,
    config: Optional[Mapping[str, Any]] = None,
    seed: Optional[int] = None,
    train_ratio: float = DEFAULT_TRAIN_RATIO,
) -> Dict[str, Any]:
    """Обучить RL на первых эпизодах и сравнить с записанным выбором.

    Проверка идёт на хвосте хронологии: обучение — первые
    ``train_ratio`` эпизодов, проверка — остальные. Это честный
    временной holdout, а не случайное перемешивание.
    """

    items = normalise_episodes(episodes)
    settings = dict(config or {})
    model = model or load_model()
    max_episodes = _config_integer(
        settings, "max_episodes", model.max_episodes
    )
    if len(items) > max_episodes:
        items = items[-max_episodes:]
    min_episodes = _config_integer(
        settings, "min_episodes", model.min_episodes
    )
    coverage_threshold = _config_number(
        settings, "coverage_threshold", model.coverage_threshold
    )
    reward_tolerance = _config_number(
        settings, "reward_tolerance", model.reward_tolerance
    )
    train_epsilon = _config_number(
        settings, "train_epsilon", DEFAULT_TRAIN_EPSILON
    )
    base_seed = (
        _config_integer(settings, "seed", model.random_seed)
        if seed is None
        else int(seed)
    )
    report: Dict[str, Any] = {
        "version": RL_VERSION,
        "available": bool(soar_available()),
        "unavailable": False,
        "episodes": len(items),
        "min_episodes": min_episodes,
        "coverage_threshold": coverage_threshold,
        "reward_tolerance": reward_tolerance,
        "train_ratio": train_ratio,
        "seed": base_seed,
        "policy": {},
        "train": 0,
        "eval": 0,
        "contexts": 0,
        "covered": 0,
        "agreements": 0,
        "coverage": 0.0,
        "agreement": 0.0,
        "mean_reward": 0.0,
        "legacy_value": 0.0,
        "learned_value": 0.0,
        "lift": 0.0,
        "trainer": {},
        "passed": False,
        "reason": "",
    }
    if not report["available"]:
        report["unavailable"] = True
        report["reason"] = "пакет soar-sml недоступен"
        report["ok"] = False
        return report
    if len(items) < 2:
        report["reason"] = "нужно хотя бы два эпизода"
        report["ok"] = False
        return report
    ratio = min(0.9, max(0.1, float(train_ratio)))
    n_train = int(len(items) * ratio)
    n_train = max(1, min(len(items) - 1, n_train))
    train = items[:n_train]
    evaluation = items[n_train:]
    trainer = SoarRlTrainer(
        model=model,
        seed=base_seed,
        epsilon=train_epsilon,
    )
    try:
        trainer.train(train)
        table = trainer.learn_policy(train)
        covered = 0
        agreements = 0
        for episode in evaluation:
            action = table.get(episode.context)
            if action is None or action not in episode.candidates:
                continue
            covered += 1
            if action == episode.chosen:
                agreements += 1
    finally:
        trainer.close()
    coverage = covered / float(len(evaluation)) if evaluation else 0.0
    agreement = agreements / float(covered) if covered else 0.0
    mean_reward = (
        sum(episode.reward for episode in evaluation)
        / float(len(evaluation))
        if evaluation
        else 0.0
    )
    reward_table = _reward_table(train)
    legacy_values: List[float] = []
    learned_values: List[float] = []
    for episode in evaluation:
        per_action = reward_table.get(episode.context) or {}
        legacy_value = per_action.get(episode.chosen)
        action = table.get(episode.context)
        learned_value = (
            per_action.get(action)
            if action in episode.candidates
            else None
        )
        if legacy_value is None or learned_value is None:
            continue
        legacy_values.append(legacy_value)
        learned_values.append(learned_value)
    legacy_mean = (
        sum(legacy_values) / float(len(legacy_values))
        if legacy_values
        else 0.0
    )
    learned_mean = (
        sum(learned_values) / float(len(learned_values))
        if learned_values
        else 0.0
    )
    lift = learned_mean - legacy_mean
    passed = bool(
        len(items) >= min_episodes
        and coverage >= coverage_threshold
        and lift >= -reward_tolerance
    )
    report.update(
        {
            "train": len(train),
            "eval": len(evaluation),
            "contexts": len(table),
            "policy": dict(sorted(table.items())),
            "covered": covered,
            "agreements": agreements,
            "coverage": round(coverage, 6),
            "agreement": round(agreement, 6),
            "mean_reward": round(mean_reward, 6),
            "legacy_value": round(legacy_mean, 6),
            "learned_value": round(learned_mean, 6),
            "lift": round(lift, 6),
            "reward_tolerance": reward_tolerance,
            "trainer": trainer.report(),
            "passed": passed,
            "ok": passed,
            "reason": "" if passed else _reason(
                len(items),
                min_episodes,
                coverage,
                coverage_threshold,
                lift,
                reward_tolerance,
            ),
        }
    )
    return report


def _reward_table(
    episodes: Iterable[RlEpisode],
) -> Dict[str, Dict[str, float]]:
    """Средняя награда по (контекст, действие) на обучающих эпизодах."""

    totals: Dict[str, Dict[str, List[float]]] = {}
    for episode in episodes:
        actions = totals.setdefault(episode.context, {})
        actions.setdefault(episode.chosen, []).append(episode.reward)
    return {
        context: {
            action: sum(values) / float(len(values))
            for action, values in actions.items()
        }
        for context, actions in totals.items()
    }


def _reason(
    episodes: int,
    min_episodes: int,
    coverage: float,
    coverage_threshold: float,
    lift: float,
    reward_tolerance: float,
) -> str:
    if episodes < min_episodes:
        return "эпизодов %d меньше порога %d" % (
            episodes,
            min_episodes,
        )
    if coverage < coverage_threshold:
        return "покрытие контекстов %.3f ниже порога %.3f" % (
            coverage,
            coverage_threshold,
        )
    if lift < -reward_tolerance:
        return "выигрыш RL %.3f ниже допуска %.3f" % (
            lift,
            -reward_tolerance,
        )
    return ""


def episodes_from_json(path: Path) -> List[RlEpisode]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise BackendError("не удалось прочитать %s" % path) from exc
    except ValueError as exc:
        raise BackendError("%s не является JSON" % path) from exc
    if isinstance(data, Mapping):
        data = data.get("episodes") or []
    return normalise_episodes(data)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Обучение RL-предпочтений Soar и сравнение",
    )
    parser.add_argument("episodes", help="JSON со списком эпизодов")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        items = episodes_from_json(Path(args.episodes))
        report = compare_episodes(items, seed=args.seed)
    except BackendError as exc:
        print("ошибка: %s" % exc)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "эпизодов %d, обучение %d, проверка %d"
            % (report["episodes"], report["train"], report["eval"])
        )
        print(
            "контекстов %d, покрытие %.3f, согласие %.3f"
            % (
                report["contexts"],
                report["coverage"],
                report["agreement"],
            )
        )
        print("порог пройден: %s" % ("да" if report["passed"] else "нет"))
        if report["reason"]:
            print("  причина: %s" % report["reason"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_TRAIN_EPSILON",
    "RL_VERSION",
    "RlEpisode",
    "SoarRlPolicy",
    "SoarRlTrainer",
    "compare_episodes",
    "episodes_from_json",
    "main",
    "normalise_episodes",
]
