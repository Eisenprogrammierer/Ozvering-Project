"""Состояние экрана, выбор целей, действия, время и вкладки."""

from __future__ import annotations

from .world_screen_support import (
    ACTION_ROW_H,
    LEFT_RECT,
    LIST_ROW_H,
    MID_RECT,
    SUB_TABS,
    background_pause_reason,
    logger,
    world_text,
)


class WorldScreenCoreMixin:

    @staticmethod
    def _initial_target_id(engine):
        if not engine.attached:
            return engine.player_node_id or (
                engine.node_order[0] if engine.node_order else ""
            )
        for node in engine.organization_groups().get("allied", ()):
            if node["id"] == engine.player_node_id:
                continue
            options = engine.action_options(node["id"])
            if any(
                option.get("enabled")
                and not (option.get("action") or {}).get("career")
                for option in options
            ):
                return node["id"]
        return engine.player_node_id or (
            engine.node_order[0] if engine.node_order else ""
        )

    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        interp.state["world"] = self.engine.to_dict()
        interp.set_variable("world_day", self.engine.day)
        interp.set_variable("world_days", self.engine.days)
        interp.set_variable("world_actions_left", self.engine.actions_left)
        interp.set_variable("world_outcome", self.engine.outcome or "")
        interp.set_variable("world_ending", self.engine.ending or "")
        interp.set_variable("world_infinite", self.engine.infinite)
        interp.set_variable("world_dismissed", self.engine.dismissed)
        for key, value in self.engine.player_resources.items():
            interp.set_variable("world_%s" % key, value)

    def _active_group_id(self, tab=None):
        tab = tab or self.main_tab
        index = self.subtab_index.get(tab, 0)
        options = SUB_TABS.get(tab) or ()
        if not options:
            return ""
        return options[min(index, len(options) - 1)][0]

    def _active_organizations(self):
        category = self._active_group_id("organizations")
        return self.engine.organization_groups().get(category, [])

    def _active_characters(self):
        circle = self._active_group_id("characters")
        return self.engine.characters_by_circle(circle)

    def _active_norms(self):
        return self.engine.norm_entries()

    def _visible_entity_rows(self):
        return max(1, (LEFT_RECT.height - 56) // LIST_ROW_H)

    def _visible_action_rows(self):
        return max(1, (MID_RECT.height - 220) // ACTION_ROW_H)

    def _max_entity_scroll(self, rows=None):
        if rows is None:
            rows = self._entity_rows()
        return max(0, len(rows) - self._visible_entity_rows())

    def _max_action_scroll(self):
        return max(
            0,
            len(self._action_options()) - self._visible_action_rows(),
        )

    def _entity_rows(self):
        if self.main_tab == "characters":
            return self._active_characters()
        if self.main_tab == "organizations":
            return self._active_organizations()
        if self.main_tab == "norms":
            return self._active_norms()
        return []

    def _action_options(self):
        if self.action_context == "character":
            if not self.selected_character_id:
                return []
            options = [
                dict(option, context="character")
                for option in self.engine.character_action_options(
                    self.selected_character_id
                )
            ]
            options.extend(
                self._world_options(
                    {"kind": "character", "id": self.selected_character_id},
                    "character",
                )
            )
        elif self.action_context == "item":
            if not self.selected_item_id:
                return []
            options = self._world_options(
                {"kind": "item", "id": self.selected_item_id}, "item"
            )
        elif self.action_context == "norm":
            if not self.selected_norm_id:
                return []
            options = self._world_options(
                {"kind": "norm", "id": self.selected_norm_id}, "norm"
            )
        elif self.action_context == "organization":
            if not self.selected_target_id:
                return []
            options = list(self.engine.action_options(self.selected_target_id))
        else:
            return []
        return sorted(
            options, key=lambda option: 0 if option.get("enabled") else 1
        )

    def _world_options(self, ref, context):
        """Объявленные действия, чей адресат совпадает с сущностью."""

        kind = str((ref or {}).get("kind") or "")
        if not kind:
            return []
        result = []
        for option in self.engine.action_options(target_ref=ref):
            action = option.get("action") or {}
            kinds = (action.get("target") or {}).get("kinds") or ()
            if kind not in kinds:
                continue
            result.append(
                dict(option, context="world", action_context=context)
            )
        return result

    def _option_chance(self, option):
        action = option.get("action") or {}
        success = action.get("success") or {}
        return float(
            option.get("chance")
            or success.get("chance")
            or action.get("success_chance", 0.6)
        )

    def _select_target(self, node_id):
        if (
            node_id == self.selected_target_id
            and self.action_context == "organization"
        ):
            return
        self.main_tab = "organizations"
        self.action_context = "organization"
        self.selected_target_id = node_id
        self.selected_character_id = None
        self.selected_action_id = None
        self.action_scroll = 0
        self.last_result = None
        self.message = ""
        logger.debug("Цель мира выбрана: %s", node_id)

    def _select_character(self, character_id):
        if (
            character_id == self.selected_character_id
            and self.action_context == "character"
        ):
            return
        self.main_tab = "characters"
        self.action_context = "character"
        self.selected_character_id = character_id
        self.selected_action_id = None
        self.action_scroll = 0
        self.last_result = None
        self.message = ""
        logger.debug("Собеседник выбран: %s", character_id)

    def _select_norm(self, norm_id):
        if norm_id == self.selected_norm_id and self.action_context == "norm":
            return
        self.main_tab = "norms"
        self.action_context = "norm"
        self.selected_norm_id = norm_id
        self.selected_character_id = None
        self.selected_action_id = None
        self.action_scroll = 0
        self.last_result = None
        self.message = ""
        logger.debug("Норма выбрана: %s", norm_id)

    def _select_skill(self, skill_id):
        self.main_tab = "personality"
        self.subtab_index["personality"] = 1
        self.action_context = "personality"
        self.selected_skill_id = skill_id
        self.selected_item_id = None
        self.selected_action_id = None
        self.last_result = None
        self.message = ""

    def _select_item(self, item_id):
        self.main_tab = "personality"
        self.subtab_index["personality"] = 2
        self.action_context = "item"
        self.selected_item_id = item_id
        self.selected_skill_id = None
        self.selected_action_id = None
        self.last_result = None
        self.message = ""

    def _select_action(self, option):
        if not option.get("enabled"):
            self.message = str(
                world_text.reason_text(option.get("reason"))
                or "Действие недоступно"
            )
            return
        self.selected_action_id = option["id"]
        self.selected_action_context = str(
            option.get("context") or self.action_context
        )
        self.selected_action_option = option
        self.last_result = None
        self.message = ""
        logger.debug("Действие мира выбрано: %s", option["id"])

    def _execute_selected(self):
        if not self.selected_action_id:
            return
        action_id = self.selected_action_id
        option = self.selected_action_option or {}
        selected_context = str(
            self.selected_action_context or self.action_context
        )
        if selected_context == "world":
            result = self.engine.execute(
                action_id, target_ref=option.get("target_ref") or {}
            )
        elif selected_context == "character":
            result = self.engine.execute_character_action(
                action_id, self.selected_character_id
            )
        else:
            previous_node = self.engine.player_node_id
            result = self.engine.execute(action_id, self.selected_target_id)
        if not result.get("ok"):
            self.message = str(result.get("reason") or "Действие недоступно")
            return
        self.last_result = result
        self.selected_action_id = None
        self.selected_action_option = None
        self.message = ""
        if selected_context == "organization":
            action = self.engine.actions.get(action_id) or {}
            if (
                action.get("career") in ("promote", "transfer")
                and self.engine.player_node_id != previous_node
            ):
                self.selected_target_id = self.engine.player_node_id
                self.action_scroll = 0
        self._sync_storyline()
        logger.info(
            "Действие мира: %s; итог=%s",
            result.get("action"),
            result.get("outcome"),
        )

    def _end_day(self):
        result = self.engine.end_day()
        if not result.get("ok"):
            self.message = str(result.get("reason") or "")
            return
        self.last_result = self.engine.last_result
        self.selected_action_id = None
        self.message = ""
        self._sync_storyline()
        logger.info("Мир завершил день: %d", self.engine.day)

    def _autopilot_env(self):
        """Лениво подключить `CampaignEnv` к живому движку экрана."""
        from campaign.env import CampaignEnv

        if self.campaign_env is None:
            self.campaign_env = CampaignEnv(engine=self.engine)
        elif self.campaign_env.engine is not self.engine:
            self.campaign_env.attach(self.engine)
        return self.campaign_env

    def _autopilot_policy_instance(self):
        if self.autopilot_policy is None:
            self.autopilot_note = ""
            checkpoint = str(getattr(self.app, "checkpoint", "") or "")
            if checkpoint:
                from agents import load_policy, supports_campaign

                try:
                    policy = load_policy(
                        checkpoint, seed=int(self.engine.seed)
                    )
                except Exception as error:  # noqa: BLE001 — игра не падает
                    logger.warning(
                        "Автопилот: чекпойнт %s не загружен (%r); "
                        "используется новая BDI",
                        checkpoint,
                        error,
                    )
                else:
                    if supports_campaign(policy):
                        self.autopilot_policy = policy
                        logger.info(
                            "Автопилот: чекпойнт загружен (%s, %s)",
                            checkpoint,
                            type(policy).__name__,
                        )
                    else:
                        self.autopilot_note = (
                            "чекпойнт %s — аренный (%s), для кампании "
                            "используется BDI" % (
                                checkpoint,
                                type(policy).__name__,
                            )
                        )
                        logger.warning(
                            "Автопилот: %s", self.autopilot_note
                        )
            if self.autopilot_policy is None:
                from agents import BDIPolicy

                self.autopilot_policy = BDIPolicy(
                    seed=int(self.engine.seed)
                )
        return self.autopilot_policy

    def _toggle_autopilot(self):
        if self.engine.finished or not self.engine.attached:
            self.autopilot = False
            self.message = "Автопилот недоступен: кампания не активна."
            return
        self.autopilot = not self.autopilot
        self.autopilot_timer = 0.0
        self.selected_action_id = None
        if self.autopilot:
            self._autopilot_env()
            policy = self._autopilot_policy_instance()
            self.message = "Автопилот включён: политика %s." % (
                type(policy).__name__
            )
            if self.autopilot_note:
                self.message += " " + self.autopilot_note
        else:
            self.message = "Автопилот выключен."
        logger.info("Автопилот кампании: %s", self.autopilot)

    def _autopilot_step(self):
        """Один шаг политики на живом движке; возвращает info или None."""
        if not self.autopilot:
            return None
        engine = self.engine
        if engine.finished or not engine.attached:
            self.autopilot = False
            return None
        env = self._autopilot_env()
        try:
            _obs, _reward, done, truncated, info = env.advance(
                self._autopilot_policy_instance(), explore=False
            )
        except Exception as error:  # noqa: BLE001 — живой UI не падает
            self.autopilot = False
            self.message = "Автопилот остановлен: %s" % error
            logger.warning(
                "Автопилот кампании остановлен: %r", error, exc_info=True
            )
            return None
        result = info.get("result") or {}
        if result.get("ok"):
            self.last_result = engine.last_result
            self.selected_action_id = None
        self._sync_storyline()
        if done or truncated:
            self.autopilot = False
            if done:
                self.message = "Автопилот: кампания завершена."
            else:
                self.message = "Автопилот: достигнут горизонт дней."
        return info

    def update(self, dt):
        """Фоновая симуляция при свёрнутом/неактивном окне (§7 №31).

        Пока окно активно, дни идут только по кнопке «Завершить день».
        В фоне реальные секунды копятся в `CampaignClock` и переводятся в
        ограниченный догон `WorldEngine.advance_days()`. Критическое
        состояние (смерть, болезнь, завершённый сюжет, отсутствие
        должности) ставит часы на паузу.
        """
        engine = self.engine
        if engine.finished or not engine.attached:
            self.autopilot = False
            self.clock.reset_accumulator()
            self.clock.pause()
            self.clock.pause_reason = (
                "finished" if engine.finished else "unattached"
            )
            return
        if self.autopilot:
            self.autopilot_timer += max(0.0, float(dt))
            if self.autopilot_timer >= self.autopilot_interval:
                self.autopilot_timer = 0.0
                self._autopilot_step()
            if engine.finished or not engine.attached:
                return
        if self.free_mode:
            self._update_free_time(dt)
            return
        if getattr(self.app, "active", True):
            self.clock.reset_accumulator()
            self.clock.resume()
            self.clock.pause_reason = ""
            return
        reason = background_pause_reason(engine)
        if reason:
            self.clock.reset_accumulator()
            self.clock.pause()
            self.clock.pause_reason = reason
            return
        self.clock.resume()
        self.clock.pause_reason = ""
        days = self.clock.advance(dt)
        slot_events = engine.tick(max_slot=self.clock.slot)
        if days <= 0:
            if slot_events:
                self.message = "Внутри дня: событий — %d." % len(slot_events)
            return
        results = engine.advance_days(
            days, max_days=self.clock.max_catchup_days
        )
        if not results:
            return
        self.last_result = engine.last_result
        self.selected_action_id = None
        self.message = "Фон: прошло дней — %d." % len(results)
        self._sync_storyline()
        logger.info(
            "Фоновый догон: %d дн.; день=%d, завершено=%s",
            len(results),
            engine.day,
            engine.finished,
        )

    def _update_free_time(self, dt):
        """RTS-время свободного режима: физические секунды без rewind."""
        try:
            seconds = float(dt)
        except (TypeError, ValueError):
            seconds = 0.0
        seconds = max(0.0, seconds)
        if seconds <= 0.0:
            return
        days = self.clock.advance(seconds)
        slot_events = self.engine.tick(max_slot=self.clock.slot)
        if days <= 0:
            if slot_events:
                self.message = "Внутри дня: событий — %d." % len(slot_events)
                self._sync_storyline()
            return
        results = self.engine.advance_days(
            days, max_days=self.clock.max_catchup_days
        )
        if not results:
            return
        self.last_result = self.engine.last_result
        self.selected_action_id = None
        self.message = "Время: прошло дней — %d." % len(results)
        self._sync_storyline()
        logger.info(
            "RTS-время: %d дн.; день=%d, скорость=%s, завершено=%s",
            len(results),
            self.engine.day,
            self.clock.speed_label(),
            self.engine.finished,
        )

    def _choose_office(self):
        open_selection = getattr(self.app, "open_office_selection", None)
        if open_selection is None:
            self.message = "Выбор должности недоступен."
            return
        open_selection(self.engine)
        logger.info("Открыт выбор новой должности после смены роли")

    def _accept_outcome(self):
        if self.engine.outcome in ("win", "lose"):
            self.app.finish_storyline_outcome(self.engine.outcome)
            logger.info("Принят исход мира: %s", self.engine.outcome)
            return
        if self.engine.ending == "neutral":
            self.message = "Глава завершена: история продолжается в мире."
            logger.info("Принят нейтральный финал мира")

    def _set_main_tab(self, tab):
        if tab not in SUB_TABS:
            return
        self.main_tab = tab
        self.list_scroll = 0
        self.action_scroll = 0
        self.selected_action_id = None
        self.last_result = None
        self.message = ""
        if tab == "personality":
            self.action_context = "personality"
            self.selected_skill_id = None
            self.selected_item_id = None
            return
        self._apply_group_selection()

    def _set_subtab(self, index):
        options = SUB_TABS.get(self.main_tab) or ()
        if not (0 <= index < len(options)):
            return
        self.subtab_index[self.main_tab] = index
        self.list_scroll = 0
        self.action_scroll = 0
        self.selected_action_id = None
        self.last_result = None
        self.message = ""
        if self.main_tab == "personality":
            self.action_context = "personality"
            if index == 1:
                self.selected_item_id = None
            elif index == 2:
                self.selected_skill_id = None
                if self.selected_item_id:
                    self.action_context = "item"
            else:
                self.selected_skill_id = None
                self.selected_item_id = None
            return
        self._apply_group_selection()

    def _apply_group_selection(self):
        if self.main_tab == "characters":
            self.action_context = "character"
            rows = self._active_characters()
            ids = {item["id"] for item in rows}
            if rows and self.selected_character_id not in ids:
                self.selected_character_id = rows[0]["id"]
            if not rows:
                self.selected_character_id = None
            return
        if self.main_tab == "norms":
            self.action_context = "norm"
            rows = self._active_norms()
            ids = {item["id"] for item in rows}
            if rows and self.selected_norm_id not in ids:
                self.selected_norm_id = rows[0]["id"]
            if not rows:
                self.selected_norm_id = None
            self.selected_character_id = None
            return
        if self.main_tab == "organizations":
            self.action_context = "organization"
            rows = self._active_organizations()
            ids = {item["id"] for item in rows}
            if rows and self.selected_target_id not in ids:
                self.selected_target_id = rows[0]["id"]
            if not rows:
                self.selected_target_id = None
            self.selected_character_id = None
            self.selected_norm_id = None
