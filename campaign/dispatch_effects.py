"""Применение последствий доклада к BDI источника и лидера."""

from __future__ import annotations

from .dispatch_support import (
    _as_list,
    _as_mapping,
    _clamp,
    _number,
)
from .relations import RELATION_AXES


class EffectsMixin:

    def _character(self, character_id):
        key = str(character_id or "")
        if not key:
            return None
        for faction in self.campaign.factions.values():
            for character in getattr(faction, "characters", ()) or ():
                if str(getattr(character, "campaign_id", "")) == key:
                    return character
        return None

    def _apply_effects(
        self,
        faction,
        source,
        report,
        effect,
        effect_key,
        belief_target=None,
        motive=None,
    ):
        changes = {}
        leader = self._leader_for(faction)
        leader_key = self._leader_key(faction, leader)
        if source is not None:
            morale_before = _number(getattr(source, "morale", 0.0))
            morale = _number(effect.get("morale"))
            if morale:
                source.morale = max(
                    0.0,
                    min(100.0, morale_before + morale),
                )
                changes["morale"] = round(
                    source.morale - morale_before, 6
                )
            needs = _as_mapping(effect.get("needs"))
            for need, delta in needs.items():
                if need not in getattr(source, "needs", {}):
                    continue
                before = _number(source.needs.get(need))
                source.needs[need] = _clamp(before + _number(delta))
                changes.setdefault("needs", {})[str(need)] = round(
                    source.needs[need] - before, 6
                )
            predicate = {
                "trust": "trusts",
                "ignore": "ignored",
                "verify_right": "verified",
                "verify_wrong": "doubts",
                "verify_lie": "suspects",
                "rumor_trust": "trusts",
                "rumor_ignore": "ignored",
                "rumor_verify": "doubts",
                "contradiction_trust": "distrusted",
                "contradiction_ignore": "ignored",
                "contradiction_verify_right": "verified",
                "contradiction_verify_wrong": "doubts",
            }.get(effect_key)
            if predicate:
                if belief_target is not None:
                    target = belief_target
                elif effect_key in (
                    "verify_right",
                    "verify_wrong",
                    "verify_lie",
                    "rumor_verify",
                ):
                    target = report.get("asset")
                else:
                    target = report.get("source_id")
                try:
                    source.believe(
                        leader_key, predicate, str(target or "")
                    )
                except Exception:
                    pass
                changes["belief"] = {
                    "subject": leader_key,
                    "predicate": predicate,
                    "object": str(target or ""),
                }
        if leader is not None and leader is not source:
            changes["leader"] = self._apply_leader_effects(
                faction,
                leader,
                leader_key,
                report,
                effect,
                effect_key,
                motive=motive,
            )
        relations = getattr(self.campaign, "relations", None)
        if relations is not None and faction is not None:
            player = str(getattr(faction, "id", "") or "")
            other = str(report.get("source_id") or "")
            for prefix, start, end in (
                ("player_", player, other),
                ("source_", other, player),
            ):
                axes = {}
                for axis in RELATION_AXES:
                    key = prefix + axis
                    if key in effect:
                        axes[axis] = _number(effect.get(key))
                if axes:
                    applied = relations.add(start, end, axes, 1.0)
                    changes.setdefault("relations", []).append(
                        {
                            "source": start,
                            "target": end,
                            "axes": applied,
                        }
                    )
        return changes

    def _apply_leader_effects(
        self,
        faction,
        leader,
        leader_key,
        report,
        effect,
        effect_key,
        motive=None,
    ):
        """Последствия доклада для того, кто принимает решение.

        Это и есть связь событий с действиями фракции: лидер получает
        потребности, мораль и убеждение об источнике или угрозе, а
        ``ai_model.beliefs.rules`` уже взвешивает по ним работы.
        """
        config = _as_mapping(effect.get("leader"))
        changes = {}
        morale_before = _number(getattr(leader, "morale", 0.0))
        morale = _number(config.get("morale"))
        if morale:
            leader.morale = max(
                0.0, min(100.0, morale_before + morale)
            )
            changes["morale"] = round(
                leader.morale - morale_before, 6
            )
        for need, delta in _as_mapping(config.get("needs")).items():
            if need not in getattr(leader, "needs", {}):
                continue
            before = _number(leader.needs.get(need))
            leader.needs[need] = _clamp(before + _number(delta))
            changes.setdefault("needs", {})[str(need)] = round(
                leader.needs[need] - before, 6
            )
        predicate = str(config.get("predicate") or "")
        if predicate:
            target_mode = str(config.get("target") or "source")
            if target_mode == "asset":
                target = report.get("asset")
            elif target_mode == "self":
                target = str(getattr(faction, "id", "") or "")
            else:
                target = report.get("source_id")
            try:
                self._believe(
                    leader,
                    leader_key,
                    predicate,
                    str(target or ""),
                    _number(config.get("value"), 1.0),
                    _number(config.get("confidence"), 0.8),
                )
                changes["belief"] = {
                    "subject": leader_key,
                    "predicate": predicate,
                    "object": str(target or ""),
                }
            except Exception:
                pass
        if motive:
            changes["motive"] = motive
        threat = self.threat_config
        if (
            self.threat_enabled
            and str(report.get("band") or "")
            in {
                str(item)
                for item in _as_list(threat.get("bands"))
            }
            and effect_key not in ("ignore", "rumor_ignore")
        ):
            target = self._rival_faction_id(faction)
            if target:
                try:
                    self._believe(
                        leader,
                        leader_key,
                        str(
                            threat.get("predicate") or "sees_as_threat"
                        ),
                        target,
                        _number(threat.get("strength"), 0.8),
                        _number(threat.get("confidence"), 0.7),
                    )
                    changes["threat"] = target
                except Exception:
                    pass
        return changes

    @staticmethod
    def _believe(
        character, subject, predicate, target, value=1.0, confidence=0.8
    ):
        """Записать убеждение в BDI персонажа.

        ``Character.believe`` принимает только триплет; уверенность и
        значение живут в ``BDIState.believe``. Обёртка держит оба пути
        совместимыми.
        """
        bdi = getattr(character, "bdi", None)
        if bdi is not None:
            belief = bdi.believe(
                subject,
                predicate,
                str(target or ""),
                value=value,
                confidence=confidence,
                source="report",
            )
            character.beliefs = bdi.beliefs
            return belief
        return character.believe(subject, predicate, str(target or ""))
