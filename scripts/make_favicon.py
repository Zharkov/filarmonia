"""Генерирует favicon.svg и PNG/ICO-иконки из favicon.png (800x800).

Запуск из корня проекта:  python scripts/make_favicon.py
"""
import base64
import io
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "filarmonia", "static")


def main() -> None:
    im = Image.open(os.path.join(STATIC, "favicon.png"))

    # SVG со встроенным base64 PNG — работает как самостоятельный файл
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" '
        'width="32" height="32">'
        f'<image href="data:image/png;base64,{b64}" width="800" height="800"/>'
        "</svg>"
    )
    with open(os.path.join(STATIC, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write(svg)

    # Растровые варианты для браузеров и iOS
    im.resize((32, 32), Image.LANCZOS).save(os.path.join(STATIC, "favicon-32.png"), "png")
    im.resize((120, 120), Image.LANCZOS).save(os.path.join(STATIC, "favicon-120.png"), "png")
    im.resize((180, 180), Image.LANCZOS).save(os.path.join(STATIC, "apple-touch-icon.png"), "png")
    im.resize((64, 64), Image.LANCZOS).save(os.path.join(STATIC, "favicon.ico"), "ico")

    print("Готово: favicon.svg, favicon-32.png, favicon-120.png, "
          "apple-touch-icon.png, favicon.ico")


if __name__ == "__main__":
    main()
