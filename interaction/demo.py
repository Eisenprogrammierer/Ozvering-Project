from __future__ import annotations

from .model import ActionSpec, InteractionModel, OutcomeSpec, Target


def _standard_outcomes():
    return (
        OutcomeSpec(
            "accept",
            "Согласие",
            "Контакт принимает предложение или идёт на контакт.",
            probability=0.48,
            uncertainty=0.08,
            tone="positive",
        ),
        OutcomeSpec(
            "refuse",
            "Отказ",
            "Контакт не готов продолжать взаимодействие.",
            probability=0.32,
            uncertainty=0.12,
            tone="negative",
        ),
        OutcomeSpec(
            "strain",
            "Напряжение",
            "Контакт становится осторожнее; отношения слегка ухудшаются.",
            probability=0.14,
            uncertainty=0.18,
            tone="warning",
        ),
        OutcomeSpec(
            "unexpected",
            "Неожиданная реакция",
            "Эффект проявится позже и пока не наблюдается.",
            probability=0.06,
            uncertainty=0.20,
            hidden=True,
            tone="unknown",
        ),
    )


def _offer_outcomes():
    return (
        OutcomeSpec(
            "accept",
            "Согласие",
            "Контакт принимает обмен на предложенных условиях.",
            probability=0.42,
            uncertainty=0.12,
            tone="positive",
        ),
        OutcomeSpec(
            "counter",
            "Встречное предложение",
            "Контакт готов говорить, но хочет изменить условия.",
            probability=0.22,
            uncertainty=0.18,
            tone="neutral",
        ),
        OutcomeSpec(
            "refuse",
            "Отказ",
            "Контакт отклоняет обмен.",
            probability=0.24,
            uncertainty=0.15,
            tone="negative",
        ),
        OutcomeSpec(
            "strain",
            "Напряжение",
            "Предложение воспринято как неуместное.",
            probability=0.08,
            uncertainty=0.22,
            tone="warning",
        ),
        OutcomeSpec(
            "secret",
            "Скрытый интерес",
            "Контакт что-то скрывает; это может проявиться позже.",
            probability=0.04,
            uncertainty=0.25,
            hidden=True,
            tone="unknown",
        ),
    )


def _observe_outcomes():
    return (
        OutcomeSpec(
            "nothing",
            "Ничего не происходит",
            "Наблюдение не даёт заметного результата.",
            probability=0.50,
            uncertainty=0.06,
            tone="neutral",
        ),
        OutcomeSpec(
            "notice",
            "Вас замечают",
            "Контакт фиксирует наблюдение и меняет поведение.",
            probability=0.28,
            uncertainty=0.12,
            tone="warning",
        ),
        OutcomeSpec(
            "insight",
            "Новая информация",
            "Удаётся заметить полезную деталь.",
            probability=0.17,
            uncertainty=0.16,
            tone="positive",
        ),
        OutcomeSpec(
            "hidden",
            "Неизвестный сигнал",
            "Смысл увиденного пока не ясен.",
            probability=0.05,
            uncertainty=0.20,
            hidden=True,
            tone="unknown",
        ),
    )


def _press_outcomes():
    return (
        OutcomeSpec(
            "submit",
            "Подчинение",
            "Контакт уступает давлению.",
            probability=0.30,
            uncertainty=0.22,
            tone="positive",
        ),
        OutcomeSpec(
            "resist",
            "Сопротивление",
            "Контакт отвечает отказом или противодействием.",
            probability=0.35,
            uncertainty=0.24,
            tone="negative",
        ),
        OutcomeSpec(
            "escalate",
            "Эскалация",
            "Напряжение растёт; последствия могут быть шире ожидаемых.",
            probability=0.20,
            uncertainty=0.30,
            tone="danger",
        ),
        OutcomeSpec(
            "unpredictable",
            "Непредсказуемый эффект",
            "Реакция выходит за рамки известной модели.",
            probability=0.15,
            uncertainty=0.40,
            hidden=True,
            tone="unknown",
        ),
    )


TALK = ActionSpec(
    "talk",
    "Обратиться",
    "Прямой разговор без обязательств.",
    outcomes=_standard_outcomes(),
    uncertainty=0.18,
)

OFFER = ActionSpec(
    "offer",
    "Предложить обмен",
    "Обмен без гарантий; условия известны лишь приблизительно.",
    outcomes=_offer_outcomes(),
    uncertainty=0.25,
)

OBSERVE = ActionSpec(
    "observe",
    "Наблюдать",
    "Не вмешиваться и собрать то, что видно.",
    outcomes=_observe_outcomes(),
    uncertainty=0.10,
)

PRESS = ActionSpec(
    "press",
    "Оказать давление",
    "Принуждение; прогноз особенно ненадёжен.",
    outcomes=_press_outcomes(),
    uncertainty=0.45,
    unknown_share=0.05,
    unknown_description="Возможен эффект, который не описан известной "
    "моделью.",
)


def demo_targets():
    return [
        Target(
            "alpha",
            "Субъект «Альфа»",
            "Нейтральный контакт. О прошлом почти ничего не известно.",
            tags=("нейтральный", "открыт"),
            actions=(TALK, OFFER, PRESS),
        ),
        Target(
            "beta",
            "Субъект «Бета»",
            "Занят своим делом; реакция на вмешательство неясна.",
            tags=("занят",),
            actions=(TALK, OBSERVE),
        ),
        Target(
            "gamma",
            "Неизвестный контакт",
            "Почти не наблюдается. Любое действие рискованно.",
            tags=("неизвестно",),
            actions=(TALK, OBSERVE),
        ),
    ]


def demo_model(seed=0):
    return InteractionModel(demo_targets(), seed=seed)


__all__ = [
    "OFFER",
    "OBSERVE",
    "PRESS",
    "TALK",
    "demo_model",
    "demo_targets",
]
