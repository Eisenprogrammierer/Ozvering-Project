import sys

from .app import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        import traceback

        sys.stderr.write("ui: фатальная ошибка: %s\n" % exc)
        traceback.print_exc()
        sys.exit(1)
