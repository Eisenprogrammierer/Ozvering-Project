"""Канон: устойчивый исход пакета партий и воспроизводимость (пункт B3 ревью).

Исход ``run_batch(10)`` — зафиксированная базовая линия (docs/BASELINE.md):
RL 1 / UtilityAI 9 / без захвата 0. Тест ловит регрессию механики, а также
недетерминизм в пределах одного процесса. Независимость от рандомизации хэшей
(``PYTHONHASHSEED``) проверяется в ``test_checks.py`` подпроцессом — хэш-сид
фиксируется при старте интерпретатора и в процессе не меняется.
"""

import simulation as S

# docs/BASELINE.md: канонический прогон пакета из 10 партий.
EXPECTED = {"RL": 1, "UtilityAI": 9, None: 0}


def test_canon_batch_outcome():
    """Пакет из 10 партий даёт ожидаемый исход (RL 1 / UtilityAI 9 / нет 0)."""
    assert S.run_batch(10, quiet=True)[2] == EXPECTED


def test_canon_repeatable_in_process():
    """Повторный прогон в том же процессе воспроизводим такт в такт."""
    assert S.run_batch(10, quiet=True)[2] == S.run_batch(10, quiet=True)[2]
