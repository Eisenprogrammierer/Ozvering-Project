"""Точка входа игры (B2: единый запуск, `python3 main.py`).

Режимы (флаги взаимозаменяемы со сценой/приложением):
  (без флага) / --view  сюжетная кампания «Операция Озверин» (`view/`,
                         современный клиент — режим по умолчанию);
  --campaign            то же, что `--view`;
  --arena / --engine    дуэль напрямую (`game_engine`);
  --classic / --ui      классическое меню `ui/` (легаси-клиент): «Поле боя
                         (RTS)», «Взаимодействие», «Кампания» (запускает
                         view-клиент), «Как играть»;
  --automata / --editor редактор автоматов;
  --interaction         сцена взаимодействия (`ui`, scene=interaction).

Прочие флаги (--scene NAME, --checkpoint PATH, --fullscreen/-f,
--speed, --sickness, --health-factors, --no-auto-checkpoint,
--checkpoints-dir, --list-checkpoints) пробрасываются выбранному приложению.

`--list-checkpoints` обрабатывается здесь, до импорта pygame: список
печатается и без открытия окна, независимо от выбранного клиента.
"""

import sys


USAGE = (
    "usage: main.py [--view|--campaign] [--arena|--engine] "
    "[--automata|--editor]\n"
    "               [--classic|--ui] [--interaction] [--scene NAME]\n"
    "               [--checkpoint PATH] [--checkpoints-dir DIR]\n"
    "               [--list-checkpoints] [--fullscreen|-f] [--speed S]\n"
    "               [--sickness X] [--health-factors ...] [--help|-h]\n"
    "\n"
    "  (без флага)  кампания (view/), режим по умолчанию\n"
    "  --classic    классическое меню ui/ (легаси)\n"
)


def _arg_value(argv, name, default=""):
    """Значение флага `name` (через пробел или `=`) или `default`."""
    prefix = name + "="
    for index, arg in enumerate(argv):
        if arg == name:
            if index + 1 >= len(argv):
                return default
            return argv[index + 1]
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return default


def _list_checkpoints(argv):
    """Напечатать автопоиск чекпойнтов без создания окна."""
    from agents import list_checkpoints

    directory = _arg_value(argv, "--checkpoints-dir")
    rows = list_checkpoints(directory=directory or None)
    if not rows:
        print("Чекпойнтов не найдено.")
    for row in rows:
        print("%-8s %s" % (row["kind"], row["path"]))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    if "--list-checkpoints" in argv:
        return _list_checkpoints(argv)
    automata = ("--automata" in argv) or ("--editor" in argv)
    view = ("--view" in argv) or ("--campaign" in argv)
    arena = ("--arena" in argv) or ("--engine" in argv)
    classic = ("--classic" in argv) or ("--ui" in argv)
    interaction = "--interaction" in argv
    # `--scene` понимает только легаси `ui/`: без этого старые команды
    # (`main.py --scene battlefield`) молча открывали бы меню view.
    scene = "--scene" in argv
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
            "--classic",
            "--ui",
            "--interaction",
        )
    ]
    if interaction and "--scene" not in argv:
        argv.extend(["--scene", "interaction"])
    sys.argv = [sys.argv[0]] + argv
    if arena:
        import game_engine

        return game_engine.main()
    if automata:
        from automata.app import main as automata_main

        return automata_main(argv)
    if classic or interaction or (scene and not view):
        from ui.app import main as ui_main

        return ui_main(argv)
    # Современный клиент — путь по умолчанию (единая точка входа B2).
    from view.app import main as view_main

    return view_main(argv)


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
