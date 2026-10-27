import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
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
