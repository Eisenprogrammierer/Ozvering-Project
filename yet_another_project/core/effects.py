"""
core/effects.py

Интерпретатор декларативных эффектов.

Применяет эффект к состоянию мира: разрешает строковые цели в индексы
сущностей, изменяет каналы напряжений, устанавливает сегменты битовой
маски и записывает события в лог мира.

Формат эффекта — словарь с ключами targets, add_voltages,
set_segments, log; отсутствующие ключи считаются пустыми.

События модуля записываются в файл-журнал operation_ozverin.log в
корне проекта и дублируются в консоль.
"""

import logging
import os

LOG_FILENAME = "operation_ozverin.log"


def _build_logger(name):
    """
    Создаёт и возвращает журнал с файловым и консольным обработчиками.

    Файловый обработчик пишет в operation_ozverin.log в корне проекта
    с уровнем DEBUG, консольный — с уровнем INFO. Обработчики
    навешиваются один раз на имя журнала; повторный вызов возвращает
    уже настроенный журнал без дублирования.

    Args:
        name (str): Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    log_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        LOG_FILENAME,
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


logger = _build_logger("core.effects")


class EffectInterpreter:
    """
    Интерпретатор декларативных эффектов.

    Применяет эффекты к состоянию мира: разрешает цели, изменяет
    напряжения, устанавливает сегменты и пишет в лог. Все методы
    статические, экземпляр класса не требуется.
    """

    @staticmethod
    def resolve_targets(state, targets):
        """
        Разрешает строковые цели в список индексов сущностей.

        Поддерживаемые форматы целей:
        - "player": индекс игрока (state.player_idx);
        - "class:<имя>": все сущности указанного класса;
        - "<entity_id>": конкретная сущность по ID.

        Несуществующие цели пропускаются с debug-логом.
        Если player_idx вне диапазона [0, count), выдаётся warning.

        Args:
            state: Состояние игрового мира (WorldState).
            targets (list[str]): Список строковых целей.

        Returns:
            list[int]: Список индексов разрешённых сущностей.
        """
        idxs = []
        for t in targets:
            if t == "player":
                if 0 <= state.player_idx < state.count:
                    idxs.append(state.player_idx)
                else:
                    logger.warning(
                        "resolve_targets: player_idx=%d вне диапазона [0, %d). "
                        "Проверьте, что сценарий содержит сущности.",
                        state.player_idx,
                        state.count,
                    )
            elif t.startswith("class:"):
                cls = t[6:]
                idxs += [
                    i
                    for i in range(state.count)
                    if state.class_configs[state.class_ids[i]].class_name
                    == cls
                ]
            elif t in state.entity_ids:
                idxs.append(state.entity_ids.index(t))
            else:
                logger.debug("resolve_targets: цель '%s' не найдена", t)
        logger.debug(
            "resolve_targets: цели %s -> индексы %s", targets, idxs
        )
        return idxs

    @staticmethod
    def _state_index(state, idx, seg, label):
        """
        Возвращает числовой индекс состояния сегмента по метке.

        Ищет label в списке состояний сегмента. Если сегмент
        отсутствует у сущности или метка не найдена в списке
        состояний, возвращает 0.

        Args:
            state: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.
            seg (str): Имя сегмента.
            label (str): Текстовая метка состояния.

        Returns:
            int: Числовой индекс состояния или 0 при ошибке.
        """
        config = state.class_configs[state.class_ids[idx]]
        entry = config.segment_layout.segments.get(seg)
        if not entry:
            logger.debug(
                "_state_index: сегмент %s отсутствует у сущности %s, индекс 0",
                seg,
                idx,
            )
            return 0
        states = entry[2]
        if label in states:
            return states.index(label)
        logger.debug(
            "_state_index: метка %s не найдена в сегменте %s, индекс 0",
            label,
            seg,
        )
        return 0

    @staticmethod
    def apply(state, effect):
        """
        Применяет декларативный эффект к состоянию мира.

        Последовательность применения:
        1. Разрешение целей через resolve_targets.
        2. Для каждой цели: добавление дельт к каналам напряжений
           (add_voltages), установка сегментов (set_segments).
        3. Запись сообщения в лог мира (log), если задан и есть цели.

        Для set_segments: числовое значение записывается как есть;
        строковое значение для сегмента "order" ищется в
        state.order_ids; для остальных сегментов строка ищется
        как метка состояния через _state_index; неизвестное
        значение приводит к 0.

        Args:
            state: Состояние игрового мира (WorldState).
            effect (dict): Словарь эффекта с ключами targets,
                add_voltages, set_segments, log.
        """
        if not effect:
            logger.debug("apply: пустой эффект пропущен")
            return
        idxs = EffectInterpreter.resolve_targets(
            state,
            effect.get("targets", ["player"]),
        )
        for idx in idxs:
            for ch, delta in effect.get("add_voltages", {}).items():
                state.add_voltage(idx, ch, float(delta))
                logger.debug(
                    "apply: сущность %s канал %s дельта %s",
                    idx,
                    ch,
                    delta,
                )
            for seg, val in effect.get("set_segments", {}).items():
                if isinstance(val, str):
                    if seg == "order":
                        val = state.order_ids.get(val, 0)
                    else:
                        val = EffectInterpreter._state_index(
                            state, idx, seg, val
                        )
                state.write_segment(idx, seg, int(val))
                logger.debug(
                    "apply: сущность %s сегмент %s значение %s",
                    idx,
                    seg,
                    val,
                )
        if effect.get("log") and idxs:
            state.log_event(idxs[0], effect["log"])
            logger.info("apply: событие лога %s", effect["log"])