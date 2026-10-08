"""Сайт Смоленской областной филармонии — единственная точка входа.

    python app.py                  запустить сайт: http://127.0.0.1:8000
    python app.py --port 5000      на другом порту
    python app.py --debug          с отладкой и перезагрузкой при правке кода
    python app.py seed             создать таблицы и наполнить демо-контентом
    python app.py seed --reset     очистить базу и наполнить заново
    python app.py seed --menu      пересобрать главное меню по образцу
    python app.py test             прогнать проверки (pytest)
    python app.py db upgrade       обновить схему базы миграциями
    python app.py thumbs           уменьшенные копии для всех фото
    python app.py cleanup          удалить файлы, которые нигде не используются

На боевом сервере приложение поднимает gunicorn:

    gunicorn -w 3 -b 127.0.0.1:8001 "app:app"
"""
import argparse
import os
import sys

from filarmonia import create_app

# Готовое приложение для gunicorn и `flask --app app`
app = create_app()


def tolerant_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def main(argv=None) -> int:
    tolerant_output()
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="Сайт Смоленской областной филармонии",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command")

    run_cmd = commands.add_parser("run", help="запустить сайт (по умолчанию)")
    # Только этот компьютер: отладчик Werkzeug позволяет выполнять код,
    # и открывать его в сеть по умолчанию нельзя
    run_cmd.add_argument("--host", default="127.0.0.1",
                         help="адрес, по умолчанию 127.0.0.1 (только этот компьютер)")
    run_cmd.add_argument("--port", type=int, default=8000, help="порт, по умолчанию 8000")
    run_cmd.add_argument("--debug", action="store_true",
                         help="режим отладки: перезагрузка при правке и отладчик в браузере")

    seed_cmd = commands.add_parser("seed", help="наполнить базу демо-контентом")
    seed_cmd.add_argument("--reset", action="store_true",
                          help="удалить прежние данные перед наполнением")
    seed_cmd.add_argument("--menu", action="store_true",
                          help="пересобрать главное меню, не трогая остальное")

    commands.add_parser("test", help="прогнать проверки (pytest); остальное передаётся pytest, "
                                     "например: test -k admin")

    db_cmd = commands.add_parser("db", help="миграции базы")
    db_cmd.add_argument("action", choices=["upgrade", "revision", "downgrade", "current"])
    db_cmd.add_argument("message", nargs="?", default="", help="описание шага для revision")

    commands.add_parser("thumbs", help="сделать уменьшенные копии для всех фото")
    cleanup_cmd = commands.add_parser("cleanup", help="удалить загруженные файлы, которые нигде не используются")
    cleanup_cmd.add_argument("--dry-run", action="store_true", help="только показать, ничего не удалять")

    # Без команды работает как `run`, чтобы хватало просто `python app.py`
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "run")
    # Всё после `test` уходит в pytest как есть: argparse не пропускает
    # флаги вида `-k` или `-x` сквозь подкоманду
    pytest_args = argv[1:] if argv[0] == "test" else []
    args = parser.parse_args(argv[:1] if argv[0] == "test" else argv)

    if args.command == "seed":
        from filarmonia import seed

        seed.run(app, reset=args.reset, rebuild_menu=args.menu)
        return 0

    if args.command == "test":
        try:
            import pytest
        except ImportError:
            print("Для проверок нужен pytest: pip install -r requirements-dev.txt")
            return 1
        return pytest.main(["-q", "tests", *pytest_args])

    if args.command == "db":
        from filarmonia import migrate

        if args.action == "revision":
            if not args.message:
                print('Опишите изменение: python app.py db revision "добавлено поле ..."')
                return 1
            migrate.revision(app, args.message)
        else:
            getattr(migrate, args.action)(app)
        return 0

    if args.command == "thumbs":
        from filarmonia import maintenance

        print(f"Создано уменьшенных копий: {maintenance.make_all_variants(app)}")
        return 0

    if args.command == "cleanup":
        from filarmonia import maintenance

        names = maintenance.cleanup(app, dry_run=args.dry_run)
        for name in names:
            print(("  будет удалён: " if args.dry_run else "  удалён: ") + name)
        print(f"{'Найдено' if args.dry_run else 'Удалено'} неиспользуемых файлов: {len(names)}")
        return 0

    # Локальный запуск сам доводит базу до последней версии: иначе после
    # обновления кода сайт падал бы на старой схеме («no such table»).
    # Перезапуск отладчика при правке файлов повторно миграции не гоняет.
    # На боевом сервере (gunicorn) это делается явно: python app.py db upgrade.
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        from filarmonia import migrate

        migrate.upgrade(app)
    print(f"Сайт: http://127.0.0.1:{args.port}   Панель администратора: /admin")
    debug = args.debug
    if debug and (app.config["SESSION_COOKIE_SECURE"] or app.config["TRUST_PROXY"]):
        print("Режим отладки на боевых настройках отключён: отладчик позволяет выполнять код на сервере.")
        debug = False
    if debug and args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"ВНИМАНИЕ: отладчик доступен по адресу {args.host} — любой, кто видит этот адрес, "
              "может выполнить код на компьютере.")
    app.run(host=args.host, port=args.port, debug=debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
