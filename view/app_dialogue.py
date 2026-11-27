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

    def _dialogue_states(self):
        store = getattr(self, "dialogue_states", None)
        if store is None:
            from campaign.dialogue import DialogueStateStore

            store = DialogueStateStore()
            self.dialogue_states = store
        return store

    def _restore_dialogue_states(self, snapshot):
        from campaign.dialogue import DialogueStateStore

        self.dialogue_states = DialogueStateStore.from_dict(snapshot or {})

    def _dialogue_payload(self):
        """Память и состояния разговора одним блоком сейва."""

        if self.dialogue_memory is None and self.dialogue_states is None:
            return None
        payload = (
            self.dialogue_memory.to_dict()
            if self.dialogue_memory is not None
            else {"schema": 1, "agents": {}}
        )
        if self.dialogue_states is not None:
            payload["states"] = self.dialogue_states.to_dict()
        return payload

    def dialogue_session(self, side, character_id=None):
        """Создать сессию диалога с агентом стороны, помня прошлые беседы.

        Приказы и речевые акты исполняются только для своей стороны:
        чужой агент остаётся собеседником, но не отдаёт приказы за свою
        фракцию. Обычный вопрос в любом случае не меняет мир.
        """

        campaign = getattr(self, "automata_campaign", None)
        if campaign is None:
            return None
        from campaign.cognition.nlu_backend import load_nlu
        from campaign.dialogue import (
            DialogueSession,
            build_knowledge,
            load_inference,
        )
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
        session = DialogueSession(
            catalog,
            knowledge,
            memory=memory,
            allow_actions=not listen_only,
            campaign=campaign,
            inference=load_inference(catalog, knowledge),
            state_store=self._dialogue_states(),
        )
        session.nlu = load_nlu(session)
        return session
