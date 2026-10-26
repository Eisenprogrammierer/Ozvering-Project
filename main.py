"""Единая точка запуска Ozvering-Project.

    python3 main.py              # ИГРА: сценный слой ui (меню -> нарратив -> партия)
    python3 main.py --view       # КАМПАНИЯ: интерфейс view (лагерь + RTS-карта)
    python3 main.py --automata   # РЕДАКТОР: графовый редактор автоматов (JSON)
    python3 main.py --arena      # только АРЕНА: автономный game_engine (HUD партии)

Флаги передаются выбранному режиму:
    --fullscreen / -f   полноэкранный режим (все режимы);
    --scene NAME        сразу открыть экран игры (только режим игры),
                        напр. --scene game, --scene settings (см. docs/UI.md);
    --open SLUG         редактор: сразу открыть configs/automata/SLUG.json;
    --new               редактор: начать новый автомат.

Отдельные точки входа сохраняются: ``python3 -m ui`` (игра),
``python3 -m automata`` (редактор автоматов) и ``python3 game_engine.py``
(арена).
"""

import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    automata = ("--automata" in argv) or ("--editor" in argv)
    view = ("--view" in argv) or ("--campaign" in argv)
    arena = ("--arena" in argv) or ("--engine" in argv)
    argv = [a for a in argv if a not in (
        "--automata", "--editor", "--view", "--campaign",
        "--arena", "--engine")]
    sys.argv = [sys.argv[0]] + argv
    if arena:
        import game_engine
        return game_engine.main()
    if view:
        from view.app import main as view_main
        return view_main(argv)
    if automata:
        from automata.app import main as automata_main
        return automata_main(argv)
    from ui.app import main as ui_main
    return ui_main(argv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:                      # noqa: BLE001
        import traceback
        sys.stderr.write("main: фатальная ошибка: %s\n" % exc)
        traceback.print_exc()
        sys.exit(1)
