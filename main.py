"""Точка входа игры (B2: единый запуск, `python3 main.py`).

Режимы (флаги взаимозаменяемы со сценой/приложением):
  (без флага)            главное меню дуэльного клиента `ui/` — из него
                         доступны «Поле боя (RTS)», «Взаимодействие»,
                         «Кампания» (запускает view-клиент), «Как играть».
  --arena / --engine     дуэль напрямую (game_engine).
  --view / --campaign    сюжетная кампания «Операция Озверин» (view/).
  --automata / --editor  редактор автоматов.
  --interaction          сцена взаимодействия (ui, scene=interaction).

Прочие флаги (--scene NAME, --checkpoint PATH, --fullscreen/-f,
--speed, --sickness, --health-factors, --no-auto-checkpoint,
--list-checkpoints) пробрасываются выбранному приложению.
"""

import sys


USAGE = (
    "usage: main.py [--arena|--engine] [--view|--campaign] "
    "[--automata|--editor]\n"
    "               [--interaction] [--scene NAME] [--checkpoint PATH]\n"
    "               [--fullscreen|-f] [--speed S] [--sickness X] "
    "[--health-factors ...]\n"
    "               [--help|-h]"
)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    automata = ("--automata" in argv) or ("--editor" in argv)
    view = ("--view" in argv) or ("--campaign" in argv)
    arena = ("--arena" in argv) or ("--engine" in argv)
    interaction = "--interaction" in argv
    argv = [
        a
        for a in argv
        if a
        not in (
            "--automata",
            "--editor",
            "--view",
            "--campaign",
            "--arena",
            "--engine",
            "--interaction",
        )
    ]
    if interaction and "--scene" not in argv:
        argv.extend(["--scene", "interaction"])
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
    except BaseException as exc:
        import traceback

        sys.stderr.write("main: фатальная ошибка: %s\n" % exc)
        traceback.print_exc()
        sys.exit(1)
