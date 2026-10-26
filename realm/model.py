"""Чистая логика игры «Престол».

Игрок — номинальный лидер единственной фракции. Фракций-соперников пока нет,
поэтому модель описывает только внутренний контур: совет, прошения, казна,
запасы, признание и смуту. Никакой карты и никакой системы приказов здесь нет.

Ключевая механика — голосование совета. Каждое прошение содержит варианты с
политическими осями (порядок, достаток, традиция, свобода). Советник голосует
за вариант, если его интересы и доверие к лидеру дают неотрицательную оценку.
Решение можно провести только при поддержке не ниже порога; иначе остаётся
«настоять» (формальная власть, но потеря признания) или «отложить» (смута и
слабость). Это и есть номинальная власть: подпись есть, согласия нет.

Модуль не импортирует pygame и не зависит от UI.
"""

from __future__ import annotations

import random

STAT_KEYS = ("authority", "legitimacy", "unrest", "unity", "treasury", "stores")
VITAL_KEYS = ("authority", "legitimacy", "unity")
BOUNDED_KEYS = ("authority", "legitimacy", "unrest", "unity")
MODES = ("decree", "force", "defer")


class RealmError(RuntimeError):
    """Некорректное действие в модели игры."""


def _clamp(value, low, high):
    return max(low, min(high, value))


class CouncilGame:
    """Состояние одной партии и все переходы между неделями."""

    def __init__(self, content, seed=0, mandate_id=None):
        self.content = content
        self.seed = int(seed)
        self.max_weeks = int(content.game.get("max_weeks", 8))
        self.caps = dict(content.game.get("stat_caps", {}))
        self.threshold = float(content.game.get("council_threshold", 0.5))
        self.stats = {
            key: int(value)
            for key, value in content.game.get("start_stats", {}).items()
        }
        for key in STAT_KEYS:
            self.stats.setdefault(key, 0)

        self.mandate_id = (mandate_id or content.default_mandate_id())
        self.mandate = content.mandate(self.mandate_id)
        if self.mandate is None:
            raise RealmError("неизвестный мандат: %r" % (mandate_id,))

        self.advisors = {}
        for spec in content.advisors:
            advisor = dict(spec)
            advisor["trust"] = int(advisor.get("trust", 50))
            self.advisors[advisor["id"]] = advisor

        self._apply_mandate(self.mandate)

        rng = random.Random(self.seed)
        petition_ids = [p["id"] for p in content.petitions]
        rng.shuffle(petition_ids)
        self.deck = [petition_ids[i % len(petition_ids)]
                     for i in range(self.max_weeks)]
        event_ids = [e["id"] for e in content.events]
        rng.shuffle(event_ids)
        self.event_deck = [event_ids[i % len(event_ids)]
                           for i in range(len(event_ids))] if event_ids else []

        self.week = 1
        self.petition_index = 0
        self.phase = "audience"
        self.status = "active"
        self.ending = None
        self.last_result = None
        self.history = []
        if not self.current_petition:
            self.phase = "ended"
            self.status = "lost"
            self.ending = self._loss_ending("authority")

    # ------------------------------------------------------------------
    # Инициализация и служебные операции
    # ------------------------------------------------------------------
    def _apply_mandate(self, mandate):
        self._apply_stats(mandate.get("effects", {}))
        trust = int(mandate.get("trust", 0) or 0)
        if trust:
            self._apply_trust({key: trust for key in self.advisors})
        for key, delta in (mandate.get("trust_by_advisor") or {}).items():
            if key in self.advisors:
                before = self.advisors[key]["trust"]
                self.advisors[key]["trust"] = _clamp(
                    before + int(delta), 0, 100
                )

    def _cap(self, key):
        return int(self.caps.get(key, 100))

    def _apply_raw(self, effects):
        """Применить эффекты и вернуть фактические дельты."""
        actual = {}
        for key, delta in (effects or {}).items():
            if key not in self.stats:
                continue
            before = self.stats[key]
            value = before + int(delta)
            if key in BOUNDED_KEYS:
                value = _clamp(value, 0, self._cap(key))
            else:
                value = max(0, value)
            self.stats[key] = value
            if value != before:
                actual[key] = value - before
        return actual

    def _apply_stats(self, effects):
        """Эффекты с штрафами за нехватку казны/запасов.

        Отрицательный остаток не уходит в долг: ресурс обнуляется, а партия
        получает смуту/потерю признания. Так выбор всегда остаётся возможным,
        но бедность имеет политическую цену.
        """
        adjusted = dict(effects or {})
        notes = []
        for key, penalty_key, label in (
            ("treasury", "debt_penalty", "казна пуста"),
            ("stores", "shortage_penalty", "запасы истощены"),
        ):
            delta = int(adjusted.get(key, 0))
            if delta < 0 and self.stats[key] + delta < 0:
                shortfall = -(self.stats[key] + delta)
                adjusted[key] = -self.stats[key]
                notes.append("%s: не хватило %d" % (label, shortfall))
                for pkey, pdelta in (
                    self.content.game.get(penalty_key, {}) or {}
                ).items():
                    adjusted[pkey] = int(adjusted.get(pkey, 0)) + int(pdelta)
        actual = self._apply_raw(adjusted)
        return actual, notes

    def _apply_trust(self, effects):
        actual = {}
        for key, delta in (effects or {}).items():
            advisor = self.advisors.get(key)
            if advisor is None:
                continue
            before = advisor["trust"]
            advisor["trust"] = _clamp(before + int(delta), 0, 100)
            if advisor["trust"] != before:
                actual[key] = advisor["trust"] - before
        return actual

    # ------------------------------------------------------------------
    # Совет
    # ------------------------------------------------------------------
    def stance(self, advisor_id, option):
        advisor = self.advisors[advisor_id]
        preferences = advisor.get("preferences", {})
        axes = option.get("axes", {})
        score = 0.0
        for key in set(preferences) | set(axes):
            score += float(preferences.get(key, 0.0)) * float(
                axes.get(key, 0.0)
            )
        score += 0.4 * (float(advisor["trust"]) - 50.0) / 50.0
        return score

    def council_vote(self, option):
        votes = {}
        stances = {}
        support_weight = 0.0
        total_weight = 0.0
        for advisor_id, advisor in self.advisors.items():
            score = self.stance(advisor_id, option)
            votes[advisor_id] = score >= 0.0
            stances[advisor_id] = score
            weight = float(advisor.get("influence", 1.0))
            total_weight += weight
            if votes[advisor_id]:
                support_weight += weight
        support = support_weight / total_weight if total_weight else 0.0
        return {
            "votes": votes,
            "stances": stances,
            "support": support,
            "support_weight": support_weight,
            "total_weight": total_weight,
        }

    def option_support(self, option):
        return self.council_vote(option)["support"]

    def can_decree(self, option):
        return self.option_support(option) >= self.threshold

    # ------------------------------------------------------------------
    # Прошения и недельный цикл
    # ------------------------------------------------------------------
    @property
    def current_petition(self):
        if 0 <= self.petition_index < len(self.deck):
            return self.content.petition(self.deck[self.petition_index])
        return None

    def option(self, option_id):
        petition = self.current_petition
        if petition is None:
            return None
        for item in petition.get("options", []):
            if item.get("id") == option_id:
                return item
        return None

    def _event_for_week(self):
        if not self.event_deck:
            return None
        event_id = self.event_deck[self.petition_index % len(self.event_deck)]
        return self.content.event(event_id)

    def _drift(self):
        drift = dict(self.content.game.get("weekly_drift", {}) or {})
        notes = []
        if self.stats["stores"] < 60:
            drift["unrest"] = int(drift.get("unrest", 0)) + 3
            drift["unity"] = int(drift.get("unity", 0)) - 2
            notes.append("запасы ниже нормы: смута растёт")
        if self.stats["treasury"] < 20:
            drift["unrest"] = int(drift.get("unrest", 0)) + 2
            notes.append("казна почти пуста: улица нервничает")
        if self.stats["unity"] >= 60:
            drift["authority"] = int(drift.get("authority", 0)) + 1
        elif self.stats["unity"] < 30:
            drift["authority"] = int(drift.get("authority", 0)) - 2
            notes.append("раскол в совете подтачивает власть")
        if self.stats["unrest"] >= 60:
            drift["legitimacy"] = int(drift.get("legitimacy", 0)) - 2
            notes.append("смута подрывает признание")
        elif self.stats["unrest"] <= 30:
            drift["legitimacy"] = int(drift.get("legitimacy", 0)) + 1
        return drift, notes

    def _loss_key(self):
        loss = self.content.game.get("loss", {}) or {}
        for key in VITAL_KEYS:
            if key in loss and self.stats[key] <= int(loss[key]):
                return key
        if "unrest" in loss and self.stats["unrest"] >= int(loss["unrest"]):
            return "unrest"
        return None

    def _loss_ending(self, key):
        data = dict(
            (self.content.game.get("loss_endings", {}) or {}).get(key, {})
        )
        data.setdefault("title", "Партия окончена")
        data.setdefault("body", "Фракция не пережила эту неделю.")
        data["id"] = key
        data["win"] = False
        return data

    def _win_ending(self):
        if self.stats["authority"] < 30:
            key = "puppet"
        elif self.stats["legitimacy"] >= 60 and self.stats["unity"] >= 60:
            key = "recognized"
        else:
            key = "fragile"
        data = dict(
            (self.content.game.get("endings", {}) or {}).get(key, {})
        )
        data.setdefault("title", "Устав запечатан")
        data.setdefault("body", "Фракция дожила до конца срока.")
        data["id"] = key
        data["win"] = True
        return data

    def resolve(self, option_id, mode="decree"):
        """Разрешить текущее прошение и завершить неделю.

        Возвращает отчёт, который UI показывает до следующей аудиенции.
        Фаза становится ``report``; ``continue_after_report`` переводит её в
        ``audience`` или ``ended``.
        """
        if self.phase != "audience":
            raise RealmError("сейчас нет открытой аудиенции")
        petition = self.current_petition
        option = self.option(option_id)
        if petition is None or option is None:
            raise RealmError("вариант не найден в текущем прошении")
        if mode not in MODES:
            raise RealmError("неизвестный способ решения: %r" % (mode,))

        vote = self.council_vote(option)
        support = vote["support"]
        if mode == "decree" and support < self.threshold:
            raise RealmError("совет не поддерживает решение")

        before_stats = dict(self.stats)
        notes = []

        if mode == "defer":
            effect_delta, effect_notes = self._apply_stats(
                self.content.game.get("defer_penalty", {})
            )
            trust_delta = {}
            for key in self.advisors:
                if vote["votes"].get(key):
                    trust_delta[key] = -4
                else:
                    trust_delta[key] = -1
            actual_trust = self._apply_trust(trust_delta)
            notes.append("Прошение отложено: совет не получил решения.")
            notes.extend(effect_notes)
            decision_effects = effect_delta
        else:
            effect_delta, effect_notes = self._apply_stats(
                option.get("effects", {})
            )
            notes.extend(effect_notes)
            trust_delta = dict(option.get("trust", {}) or {})
            if mode == "decree":
                extra, extra_notes = self._apply_stats(
                    self.content.game.get("decree_bonus", {})
                )
                for key, value in extra.items():
                    effect_delta[key] = effect_delta.get(key, 0) + value
                notes.extend(extra_notes)
                for key in self.advisors:
                    trust_delta[key] = int(trust_delta.get(key, 0)) + (
                        1 if vote["votes"].get(key) else -1
                    )
                notes.append("Решение проведено голосованием совета.")
            else:
                extra, extra_notes = self._apply_stats(
                    self.content.game.get("force_penalty", {})
                )
                for key, value in extra.items():
                    effect_delta[key] = effect_delta.get(key, 0) + value
                notes.extend(extra_notes)
                for key in self.advisors:
                    trust_delta[key] = int(trust_delta.get(key, 0)) + (
                        1 if vote["votes"].get(key) else -5
                    )
                notes.append(
                    "Вы настояли на решении. Формальная власть сработала, "
                    "но признание пострадало."
                )
            actual_trust = self._apply_trust(trust_delta)
            decision_effects = {
                key: self.stats[key] - before_stats[key]
                for key in self.stats
                if self.stats[key] != before_stats[key]
            }

        report = {
            "week": self.week,
            "petition_id": petition["id"],
            "petition_title": petition["title"],
            "option_id": option["id"],
            "option_label": option["label"],
            "mode": mode,
            "support": support,
            "votes": vote["votes"],
            "stances": vote["stances"],
            "decision_effects": decision_effects,
            "trust_effects": actual_trust,
            "notes": notes,
            "status": "active",
            "ending": None,
            "event": None,
            "upkeep_effects": {},
            "drift_effects": {},
            "event_effects": {},
            "stats_after": dict(self.stats),
        }

        loss_key = self._loss_key()
        if loss_key is not None:
            self.status = "lost"
            self.ending = self._loss_ending(loss_key)
            report["status"] = "lost"
            report["ending"] = self.ending
            report["notes"].append(self.ending["body"])
            self._finish_report(report)
            return report

        # Неделя заканчивается: содержание, дрейф и событие.
        upkeep_raw = self.content.game.get("weekly_upkeep", {}) or {}
        upkeep, upkeep_notes = self._apply_stats(upkeep_raw)
        drift_raw, drift_notes = self._drift()
        drift, drift_notes2 = self._apply_stats(drift_raw)
        event = self._event_for_week()
        event_effects = {}
        if event:
            event_effects, event_notes = self._apply_stats(
                event.get("effects", {})
            )
            trust_all = int(event.get("trust_all", 0) or 0)
            if trust_all:
                event_trust = self._apply_trust(
                    {key: trust_all for key in self.advisors}
                )
                for key, delta in event_trust.items():
                    report["trust_effects"][key] = (
                        report["trust_effects"].get(key, 0) + delta
                    )
            notes.extend(event_notes)
        report["upkeep_effects"] = upkeep
        report["drift_effects"] = drift
        report["event"] = event
        report["event_effects"] = event_effects
        notes.extend(upkeep_notes)
        notes.extend(drift_notes)
        notes.extend(drift_notes2)

        self.week += 1
        self.petition_index += 1
        loss_key = self._loss_key()
        if loss_key is not None:
            self.status = "lost"
            self.ending = self._loss_ending(loss_key)
        elif self.week > self.max_weeks:
            self.status = "won"
            self.ending = self._win_ending()
        report["status"] = self.status
        report["ending"] = self.ending
        report["stats_after"] = dict(self.stats)
        if self.ending:
            notes.append(self.ending["body"])
        self._finish_report(report)
        return report

    def _finish_report(self, report):
        self.phase = "report"
        self.last_result = report
        entry = {
            "week": report["week"],
            "petition_id": report["petition_id"],
            "petition_title": report["petition_title"],
            "option_id": report["option_id"],
            "option_label": report["option_label"],
            "mode": report["mode"],
            "support": report["support"],
            "decision_effects": report["decision_effects"],
            "trust_effects": report["trust_effects"],
            "event": report.get("event"),
            "event_effects": report.get("event_effects", {}),
            "upkeep_effects": report.get("upkeep_effects", {}),
            "drift_effects": report.get("drift_effects", {}),
            "status": report["status"],
            "stats_after": report["stats_after"],
        }
        self.history.append(entry)
        if self.status != "active":
            # Финальный экран показывается после того, как игрок закроет отчёт.
            self.phase = "report"

    def continue_after_report(self):
        """Закрыть отчёт: вернуться к аудиенции или к финалу."""
        if self.phase != "report":
            return self.phase
        self.phase = "audience" if self.status == "active" else "ended"
        return self.phase

    # ------------------------------------------------------------------
    # Сводки и сериализация
    # ------------------------------------------------------------------
    def mandate_title(self):
        return (self.mandate or {}).get("title", "Без мандата")

    def support_percent(self, option):
        return int(round(self.option_support(option) * 100))

    def snapshot(self):
        return {
            "seed": self.seed,
            "mandate_id": self.mandate_id,
            "week": self.week,
            "max_weeks": self.max_weeks,
            "stats": dict(self.stats),
            "advisors": {
                key: int(item["trust"])
                for key, item in self.advisors.items()
            },
            "deck": list(self.deck),
            "event_deck": list(self.event_deck),
            "petition_index": self.petition_index,
            "phase": self.phase,
            "status": self.status,
            "ending": self.ending,
            "last_result": self.last_result,
            "history": list(self.history),
            "content_version": int(
                self.content.game.get("content_version", 1)
            ),
        }

    @classmethod
    def from_snapshot(cls, content, data):
        if not isinstance(data, dict):
            raise RealmError("снимок партии должен быть словарём")
        game = cls(
            content,
            seed=int(data.get("seed", 0)),
            mandate_id=data.get("mandate_id"),
        )
        game.max_weeks = int(data.get("max_weeks", game.max_weeks))
        for key, value in (data.get("stats") or {}).items():
            if key in game.stats:
                game.stats[key] = int(value)
        for key, value in (data.get("advisors") or {}).items():
            if key in game.advisors:
                game.advisors[key]["trust"] = _clamp(int(value), 0, 100)
        deck = [pid for pid in (data.get("deck") or [])
                if content.petition(pid) is not None]
        if deck:
            game.deck = deck
        event_deck = [eid for eid in (data.get("event_deck") or [])
                      if content.event(eid) is not None]
        if event_deck:
            game.event_deck = event_deck
        game.petition_index = int(data.get("petition_index", 0))
        game.week = int(data.get("week", 1))
        game.phase = data.get("phase", "audience")
        game.status = data.get("status", "active")
        game.ending = data.get("ending")
        game.last_result = data.get("last_result")
        game.history = list(data.get("history") or [])
        if game.phase == "audience" and game.current_petition is None:
            game.phase = "ended"
            if game.status == "active":
                game.status = "lost"
                game.ending = game._loss_ending("authority")
        return game
