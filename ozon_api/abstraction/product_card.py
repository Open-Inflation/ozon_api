from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import textwrap
from functools import lru_cache
from io import BytesIO
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - optional dependency for nicer previews
    Image = None
    ImageOps = None


def _supports_unicode() -> bool:
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in encoding


USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
USE_UNICODE = _supports_unicode()
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

RESET = "\033[0m" if USE_COLOR else ""

if Image is not None:
    RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
else:
    RESAMPLE = None

BOX_TOP_LEFT = "┏" if USE_UNICODE else "+"
BOX_TOP_RIGHT = "┓" if USE_UNICODE else "+"
BOX_HORIZONTAL = "━" if USE_UNICODE else "-"
BOX_VERTICAL = "┃" if USE_UNICODE else "|"
BOX_JOIN_LEFT = "┣" if USE_UNICODE else "+"
BOX_JOIN_RIGHT = "┫" if USE_UNICODE else "+"
BOX_BOTTOM_LEFT = "┗" if USE_UNICODE else "+"
BOX_BOTTOM_RIGHT = "┛" if USE_UNICODE else "+"
PREVIEW_ON = "█" if USE_UNICODE else "#"
PREVIEW_OFF = "▓" if USE_UNICODE else "."
PREVIEW_TOP = "▀" if USE_UNICODE else "#"
STAR_FILLED = "★" if USE_UNICODE else "*"
STAR_EMPTY = "☆" if USE_UNICODE else "."
METER_FILLED = "█" if USE_UNICODE else "#"
METER_EMPTY = "░" if USE_UNICODE else "-"
ELLIPSIS = "…" if USE_UNICODE else "..."
ARROW = "↗" if USE_UNICODE else "->"


class RenderableProduct(Protocol):
    sku: int | None
    title: str | None
    url: str | None
    image_url: str | None
    price: Any | None
    original_price: Any | None
    discount: str | None
    rating: float | None
    reviews: int | None
    badges: list[str]
    labels: list[str]


def colorize(
    text: str,
    *,
    fg: tuple[int, int, int] | None = None,
    bg: tuple[int, int, int] | None = None,
    bold: bool = False,
    dim: bool = False,
    underline: bool = False,
    strike: bool = False,
) -> str:
    if not USE_COLOR:
        return text

    codes: list[str] = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    if underline:
        codes.append("4")
    if strike:
        codes.append("9")
    if fg is not None:
        codes.append(f"38;2;{fg[0]};{fg[1]};{fg[2]}")
    if bg is not None:
        codes.append(f"48;2;{bg[0]};{bg[1]};{bg[2]}")

    if not codes:
        return text

    return f"\033[{';'.join(codes)}m{text}{RESET}"


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def pad_visible(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_len(text))


def format_number(value: int | float | None) -> str:
    if value is None:
        return "—"

    if isinstance(value, float):
        if value.is_integer():
            value = int(value)
        else:
            return f"{value:,.2f}".replace(",", " ").rstrip("0").rstrip(".")

    return f"{value:,}".replace(",", " ")


def format_money(price: object | None) -> str:
    if price is None:
        return "—"

    value = getattr(price, "value", None)
    currency = getattr(price, "currency", None) or ("₽" if USE_UNICODE else "RUB")
    if value is None:
        return "—"

    if not USE_UNICODE and isinstance(currency, str) and not currency.isascii():
        currency = "RUB"

    return f"{format_number(value)} {currency}".strip()


def wrap_text(text: str, width: int) -> list[str]:
    wrapped = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [""]


def shorten_url(url: str, width: int) -> str:
    if not url:
        return "—"

    parsed = urlparse(url)
    display = f"{parsed.netloc}{parsed.path}"
    if parsed.query:
        display = f"{display}?{parsed.query}"

    if len(display) <= width:
        return display

    ellipsis_width = len(ELLIPSIS)
    if width <= ellipsis_width:
        return display[:width]

    return ELLIPSIS + display[-(width - ellipsis_width) :]


def parse_discount_percent(discount: str | None) -> int | None:
    if not discount:
        return None

    match = re.search(r"(\d+)", discount.replace("−", "-"))
    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def build_meter(percent: float, width: int = 12) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = max(0, min(width, round(width * percent / 100.0)))
    return METER_FILLED * filled + METER_EMPTY * (width - filled)


def stars(rating: float) -> str:
    filled = max(0, min(5, int(round(rating))))
    return STAR_FILLED * filled + STAR_EMPTY * (5 - filled)


def chip(text: str, *, bg: tuple[int, int, int], fg: tuple[int, int, int]) -> str:
    return colorize(f" {text} ", fg=fg, bg=bg, bold=True)


def build_chip_lines(
    items: list[str],
    width: int,
    *,
    bg: tuple[int, int, int],
    fg: tuple[int, int, int],
    limit: int,
) -> list[str]:
    if not items:
        return []

    lines: list[str] = []
    current = ""
    current_width = 0

    visible_items = items[:limit]
    for item in visible_items:
        piece = chip(item, bg=bg, fg=fg)
        piece_width = visible_len(piece)

        if current and current_width + 1 + piece_width > width:
            lines.append(current)
            current = piece
            current_width = piece_width
            continue

        if current:
            current += " "
            current_width += 1

        current += piece
        current_width += piece_width

    remainder = len(items) - len(visible_items)
    if remainder > 0:
        extra = colorize(f" +{remainder}", dim=True, fg=(170, 170, 170))
        extra_width = visible_len(extra)
        if current and current_width + 1 + extra_width > width:
            lines.append(current)
            current = extra
            current_width = extra_width
        else:
            if current:
                current += " "
                current_width += 1
            current += extra
            current_width += extra_width

    if current:
        lines.append(current)

    return lines


@lru_cache(maxsize=64)
def download_image_bytes(url: str, timeout: float = 5.0) -> bytes | None:
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception:
        return None


def grayscale_char(value: int) -> str:
    ramp = "@%#*+=-:. "
    index = round((len(ramp) - 1) * value / 255)
    return ramp[max(0, min(len(ramp) - 1, index))]


def placeholder_preview(seed: str, width: int, height: int) -> list[str]:
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    palette = [
        (digest[0], digest[1], digest[2]),
        (digest[3], digest[4], digest[5]),
        (digest[6], digest[7], digest[8]),
        (digest[9], digest[10], digest[11]),
    ]
    words = re.findall(r"\w+", seed, flags=re.UNICODE)
    initials = "".join(word[0] for word in words[:2]).upper() or "OZ"
    label_row = height // 2
    label_col = max(0, (width - len(initials)) // 2)

    lines: list[str] = []
    for y in range(height):
        parts: list[str] = []
        for x in range(width):
            if y == label_row and label_col <= x < label_col + len(initials):
                parts.append(colorize(initials[x - label_col], fg=(255, 255, 255), bold=True))
                continue

            r, g, b = palette[(x + y) % len(palette)]
            if USE_COLOR:
                shade = PREVIEW_ON if (x + y) % 2 == 0 else PREVIEW_OFF
                parts.append(colorize(shade, fg=(r, g, b), bold=True))
            else:
                shade = PREVIEW_ON if (x + y) % 2 == 0 else PREVIEW_OFF
                parts.append(shade)
        lines.append("".join(parts))

    return lines


def image_preview(image_url: str, seed: str, width: int, height: int) -> list[str]:
    if not image_url or Image is None:
        return placeholder_preview(seed, width, height)

    raw = download_image_bytes(image_url)
    if not raw:
        return placeholder_preview(seed, width, height)

    try:
        image = Image.open(BytesIO(raw)).convert("RGB")
        if ImageOps is not None:
            try:
                image = ImageOps.fit(image, (width, height * 2), method=RESAMPLE)
            except TypeError:
                image = ImageOps.fit(image, (width, height * 2))
        else:
            image = image.resize((width, height * 2), RESAMPLE)
    except Exception:
        return placeholder_preview(seed, width, height)

    lines: list[str] = []
    for y in range(0, height * 2, 2):
        parts: list[str] = []
        for x in range(width):
            top = image.getpixel((x, y))
            bottom = image.getpixel((x, y + 1))
            if USE_COLOR:
                if USE_UNICODE:
                    parts.append(colorize(PREVIEW_TOP, fg=top, bg=bottom))
                else:
                    parts.append(colorize("#", fg=top))
            else:
                top_value = sum(top) // 3
                bottom_value = sum(bottom) // 3
                parts.append(grayscale_char((top_value + bottom_value) // 2))
        if USE_COLOR:
            parts.append(RESET)
        lines.append("".join(parts))

    return lines


def build_detail_lines(product: RenderableProduct, width: int) -> list[str]:
    lines: list[str] = []

    sku_text = f"SKU {product.sku or '—'}"
    header = colorize(sku_text, fg=(170, 170, 170), dim=True)
    if product.discount:
        header += "  " + colorize(product.discount, fg=(255, 92, 138), bold=True)
    lines.append(header)

    title = product.title or "Без названия"
    for line in wrap_text(title, width):
        lines.append(colorize(line, fg=(245, 245, 245), bold=True))

    price_parts = [
        colorize("Цена", fg=(170, 170, 170), dim=True),
        " ",
        colorize(format_money(product.price), fg=(0, 216, 140), bold=True),
    ]
    if product.original_price and getattr(product.original_price, "value", None) is not None:
        price_parts.extend(
            [
                "  ",
                colorize(format_money(product.original_price), fg=(170, 170, 170), strike=True),
            ]
        )

    discount_percent = parse_discount_percent(product.discount)
    if discount_percent is not None:
        price_parts.extend(
            [
                "  ",
                colorize(build_meter(discount_percent, width=12), fg=(255, 92, 138), bold=True),
                " ",
                colorize(f"{discount_percent}%", fg=(255, 92, 138), bold=True),
            ]
        )
    lines.append("".join(price_parts))

    if product.rating is not None:
        rating_parts = [
            colorize("Рейтинг", fg=(170, 170, 170), dim=True),
            " ",
            colorize(stars(product.rating), fg=(255, 196, 61), bold=True),
            " ",
            colorize(f"{product.rating:.1f}", fg=(255, 196, 61), bold=True),
            " ",
            colorize(build_meter(product.rating / 5 * 100, width=10), fg=(255, 196, 61), bold=True),
        ]
        if product.reviews is not None:
            rating_parts.extend(
                [
                    "  ",
                    colorize(f"{format_number(product.reviews)} отзывов", fg=(170, 170, 170), dim=True),
                ]
            )
        lines.append("".join(rating_parts))

    badge_lines = build_chip_lines(
        product.badges,
        width,
        bg=(255, 92, 138),
        fg=(255, 255, 255),
        limit=4,
    )
    if badge_lines:
        lines.append(colorize("Бейджи", fg=(170, 170, 170), dim=True))
        lines.extend(badge_lines)

    label_lines = build_chip_lines(
        product.labels,
        width,
        bg=(232, 236, 240),
        fg=(28, 28, 28),
        limit=6,
    )
    if label_lines:
        lines.append(colorize("Метки", fg=(170, 170, 170), dim=True))
        lines.extend(label_lines)

    if product.url:
        lines.append(
            colorize(
                f"{ARROW} {shorten_url(product.url, width - 2)}",
                fg=(100, 160, 255),
                underline=True,
            )
        )

    return lines


def render_product_card(
    product: RenderableProduct,
    *,
    index: int | None = None,
    card_width: int | None = None,
) -> str:
    terminal_width = shutil.get_terminal_size(fallback=(120, 40)).columns
    width = card_width or max(80, min(100, terminal_width - 2))
    preview_width = 16 if width <= 88 else 20
    detail_width = width - preview_width - 8

    preview = image_preview(
        product.image_url,
        product.title or product.url or "OZON",
        preview_width,
        10,
    )
    details = build_detail_lines(product, detail_width)
    body_height = max(len(preview), len(details))

    border_color = (255, 92, 138) if product.discount else (0, 188, 212)
    top_border = colorize(
        f"{BOX_TOP_LEFT}{BOX_HORIZONTAL * (width - 2)}{BOX_TOP_RIGHT}",
        fg=border_color,
        bold=True,
    )
    middle_border = colorize(
        f"{BOX_JOIN_LEFT}{BOX_HORIZONTAL * (width - 2)}{BOX_JOIN_RIGHT}",
        fg=(110, 110, 110),
        bold=True,
    )
    bottom_border = colorize(
        f"{BOX_BOTTOM_LEFT}{BOX_HORIZONTAL * (width - 2)}{BOX_BOTTOM_RIGHT}",
        fg=border_color,
        bold=True,
    )

    if index is not None:
        header_text = colorize(f"#{index}", fg=(245, 245, 245), bold=True)
        header_text += "  " + colorize(f"SKU {product.sku or '—'}", fg=(185, 185, 185), dim=True)
    else:
        header_text = colorize(f"SKU {product.sku or '—'}", fg=(245, 245, 245), bold=True)

    if product.discount:
        header_text += "  " + colorize(product.discount, fg=(255, 92, 138), bold=True)

    header_line = f"{BOX_VERTICAL} {pad_visible(header_text, width - 4)} {BOX_VERTICAL}"

    rows = [top_border, header_line, middle_border]

    for i in range(body_height):
        left = preview[i] if i < len(preview) else ""
        right = details[i] if i < len(details) else ""
        row = f"{BOX_VERTICAL} {pad_visible(left, preview_width)} {BOX_VERTICAL} {pad_visible(right, detail_width)} {BOX_VERTICAL}"
        rows.append(row)

    rows.append(bottom_border)
    return "\n".join(rows)


__all__ = ["render_product_card"]
