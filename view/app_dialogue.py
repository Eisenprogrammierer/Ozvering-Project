"""Каталог, хранилище и сессия диалога."""

from __future__ import annotations


class AppDialogueMixin:

    def _dialogue_catalog(self):
        catalog = getattr(self, "_dialogue_catalog_cache", None)
        if catalog is None:
            from campaign.dialogue import load_dialogue

            catalog = load_dialogue()
            self._dialogue_catalog_cache = catalog
        return catalog

    def _dialogue_store(self):
        store = getattr(self, "dialogue_memory", None)
        if store is None:
            from campaign.dialogue import DialogueMemoryStore

            store = DialogueMemoryStore(self._dialogue_catalog().state)
            self.dialogue_memory = store
        return store

    def _restore_dialogue_memory(self, snapshot):
        from campaign.dialogue import DialogueMemoryStore

        self.dialogue_memory = DialogueMemoryStore.from_dict(
            self._dialogue_catalog().state, snapshot or {}
        )

    def dialogue_session(self, side, character_id=None):
        """Создать сессию диалога с агентом стороны, помня прошлые беседы.

        Приказы и речевые акты исполняются только для своей стороны:
        чужой агент остаётся собеседником, но не отдаёт приказы за свою
        фракцию. Обычный вопрос в любом случае не меняет мир.
        """

        campaign = getattr(self, "automata_campaign", None)
        if campaign is None:
            return None
        from campaign.dialogue import DialogueSession, build_knowledge
        from campaign.perception import campaign_view

        catalog = self._dialogue_catalog()
        view = campaign_view(
            campaign, character_id, world=catalog.world
        )
        knowledge = build_knowledge(
            catalog, campaign, side, character_id, view=view
        )
        memory = self._dialogue_store().memory(
            knowledge.speaker_id,
            knowledge.run_id,
            knowledge.clock,
        )
        listen_only = str(side) != str(campaign.player_side)
        return DialogueSession(
            catalog,
            knowledge,
            memory=memory,
            allow_actions=not listen_only,
            campaign=campaign,
        )
