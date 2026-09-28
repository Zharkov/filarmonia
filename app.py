"""Сайт Смоленской областной филармонии — единственная точка входа.

    python app.py                  запустить сайт: http://127.0.0.1:8000
    python app.py --port 5000      на другом порту
    python app.py seed             создать таблицы и наполнить демо-контентом
    python app.py seed --reset     очистить базу и наполнить заново
    python app.py test             прогнать проверку основных сценариев

На боевом сервере приложение поднимает gunicorn:

    gunicorn -w 3 -b 127.0.0.1:8001 "app:app"
"""
import argparse
import sys

from filarmonia import create_app

# Готовое приложение для gunicorn и `flask --app app`
app = create_app()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="Сайт Смоленской областной филармонии",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command")

    run_cmd = commands.add_parser("run", help="запустить сайт (по умолчанию)")
    run_cmd.add_argument("--host", default="0.0.0.0", help="адрес, по умолчанию 0.0.0.0")
    run_cmd.add_argument("--port", type=int, default=8000, help="порт, по умолчанию 8000")
    run_cmd.add_argument("--no-debug", action="store_true",
                         help="без режима отладки и перезагрузки")

    seed_cmd = commands.add_parser("seed", help="наполнить базу демо-контентом")
    seed_cmd.add_argument("--reset", action="store_true",
                          help="удалить прежние данные перед наполнением")

    commands.add_parser("test", help="проверка основных сценариев админки")

    # Без команды работает как `run`, чтобы хватало просто `python app.py`
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "run")
    args = parser.parse_args(argv)

    if args.command == "seed":
        from filarmonia import seed

        seed.run(app, reset=args.reset)
        return 0

    if args.command == "test":
        from filarmonia import selftest

        failed = selftest.run()
        if failed:
            print(f"\nне прошло проверок: {failed}")
        return 1 if failed else 0

    print(f"Сайт: http://127.0.0.1:{args.port}   Админка: /admin")
    app.run(host=args.host, port=args.port, debug=not args.no_debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
