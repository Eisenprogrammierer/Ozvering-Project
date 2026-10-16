"""Единая точка запуска Ozvering-Project.

    python3 main.py              # ИГРА: сценный слой ui (меню -> нарратив -> партия)
    python3 main.py --arena      # только АРЕНА: автономный game_engine (HUD партии)

Флаги передаются выбранному режиму:
    --fullscreen / -f   полноэкранный режим (оба режима);
    --scene NAME        сразу открыть экран игры (только режим игры),
                        напр. --scene game, --scene settings (см. docs/UI.md).

Отдельные точки входа сохраняются: ``python3 -m ui`` (игра) и
``python3 game_engine.py`` (арена).
"""

import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    arena = ("--arena" in argv) or ("--engine" in argv)
    argv = [a for a in argv if a not in ("--arena", "--engine")]
    sys.argv = [sys.argv[0]] + argv
    if arena:
        import game_engine
        return game_engine.main()
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
