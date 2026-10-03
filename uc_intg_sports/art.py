"""
Artwork for the Remote's media player tiles.

Images are 480x420 JPEGs, the size of the Remote 3 artwork box. The Remote
Two shows a square box and crops the sides, so content stays at least 40 px
from the left and right edges. Rendering is pure: a frozen spec plus already
downloaded logos go in, JPEG bytes come out. Equal specs give equal images.

Layouts are computed, not fixed: every element is measured at the chosen
text size and stacked to fit. When space runs out, the least important
elements are dropped first (venue/TV line, records, extra scorers), so any
text size and any combination of content stays readable.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH = 480
HEIGHT = 420
SAFE_X = 40
TOP = 14
BOTTOM = HEIGHT - 12
JPEG_QUALITY = 86

TEXT_NORMAL = "normal"
TEXT_LARGE = "large"
TEXT_XLARGE = "xlarge"
TEXT_SIZES = (TEXT_NORMAL, TEXT_LARGE, TEXT_XLARGE)
_SCALE = {TEXT_NORMAL: 1.0, TEXT_LARGE: 1.2, TEXT_XLARGE: 1.4}

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_REGULAR = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
_BOLD = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

_BASE = (14, 16, 24)
_WHITE = (255, 255, 255)
_SOFT = (214, 220, 232)
_DIM = (150, 158, 176)
_LIVE_RED = (226, 38, 54)
_GOLD = (255, 205, 80)

Logos = dict  # url -> RGBA image


def _scale(text_size: str) -> float:
    return _SCALE.get(text_size, 1.0)


def _px(size: float, text_size: str) -> int:
    return max(8, round(size * _scale(text_size)))


# ----------------------------------------------------------------------
# Specs
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class SideView:
    name: str
    abbr: str
    color: str = ""
    logo: str = ""  # logo URL, looked up in the logos dict
    score: str = ""
    shootout: str = ""
    winner: bool | None = None
    detail: str = ""  # record or standing shown under the name
    plays: tuple[str, ...] = ()  # "67' Saka", "45+2' Rice (P)"
    red_cards: int = 0
    possession: bool = False


@dataclass(frozen=True)
class MatchCard:
    kind: str  # "pre", "live", "final", "off"
    league: str
    first: SideView
    second: SideView
    joiner: str = "v"
    status: str = ""  # live clock, "FT", "Final/OT", "Postponed"
    big_time: str = ""  # "12:30", "7:30 PM"
    day: str = ""  # "Sat 10 Oct"
    countdown: str = ""  # "in 6 days"
    footer: str = ""  # venue / TV / date line
    situation: str = ""  # "1st & 10 at NO 10"
    outs: int | None = None
    bases: tuple[bool, bool, bool] | None = None
    count: str = ""
    stale: bool = False  # data could not be refreshed
    text_size: str = TEXT_NORMAL


@dataclass(frozen=True)
class ScoreRow:
    first: str
    first_logo: str
    first_score: str
    second: str
    second_logo: str
    second_score: str
    status: str  # "67'", "FT", "19:30"
    live: bool = False
    final: bool = False
    highlight: bool = False


@dataclass(frozen=True)
class ScoresCard:
    title: str
    subtitle: str
    rows: tuple[ScoreRow, ...]
    page: str = ""  # "1/3"
    league_logo: str = ""
    stale: bool = False
    text_size: str = TEXT_NORMAL


@dataclass(frozen=True)
class TableLine:
    rank: str
    name: str
    logo: str
    values: tuple[str, ...]
    highlight: bool = False
    note_color: str = ""


@dataclass(frozen=True)
class TableCard:
    title: str
    subtitle: str
    columns: tuple[str, ...]
    lines: tuple[TableLine, ...]
    keep: tuple[int, ...] = ()  # per column, higher is kept longer when space is short
    page: str = ""
    league_logo: str = ""
    stale: bool = False
    text_size: str = TEXT_NORMAL


@dataclass(frozen=True)
class MessageCard:
    title: str
    text: str
    color: str = ""
    logo: str = ""
    lines: tuple[str, ...] = field(default_factory=tuple)
    text_size: str = TEXT_NORMAL


# ----------------------------------------------------------------------
# Drawing helpers
# ----------------------------------------------------------------------
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


def _rgb(value: str, fallback: tuple[int, int, int] = (60, 70, 92)) -> tuple[int, int, int]:
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except (ValueError, IndexError):
        return fallback


def _mix(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _luma(color: tuple[int, ...]) -> float:
    r, g, b = color[:3]
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _distance(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a[:3], b[:3])) ** 0.5


def _team_tone(color: str) -> tuple[int, int, int]:
    """Team colour toned down for a background that keeps white text readable."""
    tone = _mix(_rgb(color), _BASE, 0.45)
    while _luma(tone) > 0.33:
        tone = _mix(tone, _BASE, 0.2)
    if _luma(tone) < 0.06:  # black kits: lift slightly so the halves stay visible
        tone = _mix(tone, (60, 66, 84), 0.5)
    return tone  # type: ignore[return-value]


def _fit(text: str, path: str, size: int, width: float, minimum: int = 10) -> tuple[str, ImageFont.FreeTypeFont]:
    """Shrink (to about 70 % at most), then truncate, so the text fits the width."""
    floor = max(minimum, int(size * 0.7))
    while size > floor and _font(path, size).getlength(text) > width:
        size -= 1
    font = _font(path, size)
    if font.getlength(text) <= width:
        return text, font
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return (text.rstrip() + "…") if text else "", font


def _draw_text(img: Image.Image, x: float, y: float, text: str, font, fill, anchor: str = "ma",
               shadow: bool = False) -> None:
    """Draw with the top of the line at y ("ma" = centred, "la" = left, "ra" = right)."""
    if shadow:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((x, y + 2), text, font=font, fill=(0, 0, 0, 150), anchor=anchor)
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(3)))
    ImageDraw.Draw(img).text((x, y), text, font=font, fill=fill, anchor=anchor)


def _pill(img: Image.Image, cx: float, y: float, text: str, font, fill, text_fill=_WHITE, dot: bool = False) -> float:
    pad = font.size * 0.8
    dot_w = font.size * 0.75 if dot else 0
    width = font.getlength(text) + 2 * pad + dot_w
    height = _line_height(font) + font.size * 0.6
    x0 = cx - width / 2
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x0, y, x0 + width, y + height], radius=height / 2, fill=fill)
    img.alpha_composite(layer)
    draw = ImageDraw.Draw(img)
    tx = x0 + pad
    if dot:
        r = font.size * 0.27
        draw.ellipse([tx, y + height / 2 - r, tx + 2 * r, y + height / 2 + r], fill=_WHITE)
        tx += dot_w
    draw.text((tx, y + height / 2), text, font=font, fill=text_fill, anchor="lm")
    return height


def _pill_height(font) -> float:
    return _line_height(font) + font.size * 0.6


def _background(first: str, second: str) -> Image.Image:
    """Two team colours split on a diagonal, with depth and a fine stripe texture."""
    left, right = _team_tone(first), _team_tone(second)
    if _distance(left, right) < 40:
        right = _mix(right, (40, 46, 64), 0.6)
    img = Image.new("RGBA", (WIDTH, HEIGHT), left + (255,))
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask).polygon([(WIDTH * 0.58, 0), (WIDTH, 0), (WIDTH, HEIGHT), (WIDTH * 0.42, HEIGHT)], fill=255)
    img.paste(Image.new("RGBA", (WIDTH, HEIGHT), right + (255,)), (0, 0), mask.filter(ImageFilter.GaussianBlur(2)))

    stripes = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stripes)
    for x in range(-HEIGHT, WIDTH, 14):
        draw.line([(x, HEIGHT), (x + HEIGHT, 0)], fill=(255, 255, 255, 9), width=5)
    img.alpha_composite(stripes)

    shade = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shade)
    for y in range(HEIGHT):
        t = y / HEIGHT
        draw.line([(0, y), (WIDTH, y)], fill=(6, 8, 14, int(40 + 150 * t * t)))
    img.alpha_composite(shade)
    return img


def _plain_background(color: str = "") -> Image.Image:
    base = _team_tone(color) if color else (30, 36, 54)
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        draw.line([(0, y), (WIDTH, y)], fill=_mix(base, _BASE, 0.35 + 0.55 * t) + (255,))
    return img


def _glow(img: Image.Image, cx: float, cy: float, radius: float, alpha: int = 60) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(255, 255, 255, alpha))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius / 2.2)))


def _badge(abbr: str, color: str, size: int) -> Image.Image:
    """Fallback when a logo cannot be loaded: a coloured disc with the abbreviation."""
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    fill = _mix(_rgb(color), (255, 255, 255), 0.1)
    draw.ellipse([2, 2, size - 3, size - 3], fill=fill + (255,), outline=(255, 255, 255, 220), width=max(2, size // 30))
    text, font = _fit(abbr[:4] or "?", _BOLD, int(size * 0.32), size * 0.78, minimum=6)
    draw.text((size / 2, size / 2), text, font=font, fill=_WHITE if _luma(fill) < 0.6 else (20, 20, 20), anchor="mm")
    return badge


def _logo(img: Image.Image, logos: Logos, url: str, abbr: str, color: str, cx: float, cy: float, size: int,
          shadow: bool = True, dim: bool = False) -> None:
    src = logos.get(url) if url else None
    if src is not None:
        logo = src.copy()
        logo.thumbnail((size, size), Image.LANCZOS)
    else:
        logo = _badge(abbr, color, size)
    if dim:
        logo.putalpha(logo.getchannel("A").point(lambda a: int(a * 0.55)))
    x, y = int(cx - logo.width / 2), int(cy - logo.height / 2)
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sh.paste(Image.new("RGBA", logo.size, (0, 0, 0, 170)), (x, y + 5), logo)
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
    img.alpha_composite(logo, (x, y))


def _stale_badge(img: Image.Image) -> None:
    font = _font(_REGULAR, 12)
    text = "updating…"
    w = font.getlength(text) + 16
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([WIDTH - SAFE_X - w, 4, WIDTH - SAFE_X, 22], radius=9, fill=(0, 0, 0, 150))
    img.alpha_composite(layer)
    ImageDraw.Draw(img).text((WIDTH - SAFE_X - w / 2, 13), text, font=font, fill=_SOFT, anchor="mm")


def _jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


# ----------------------------------------------------------------------
# Vertical layout
# ----------------------------------------------------------------------
@dataclass
class _Block:
    height: float
    draw: Callable[[Image.Image, float], None]
    keep: int  # higher stays longer when space is short
    gap: float = 8  # space above the block
    smaller: Callable[[], "_Block | None"] | None = None  # a reduced version to try before dropping


def _stack(img: Image.Image, blocks: list[_Block], top: float = TOP, bottom: float = BOTTOM) -> None:
    """Fit blocks between top and bottom, dropping or shrinking the least important first."""
    blocks = [block for block in blocks if block is not None]

    def total() -> float:
        return sum(block.height + (block.gap if i else 0) for i, block in enumerate(blocks))

    while blocks and total() > bottom - top:
        index = min(range(len(blocks)), key=lambda i: (blocks[i].keep, -i))
        smaller = blocks[index].smaller() if blocks[index].smaller else None
        if smaller is not None:
            blocks[index] = smaller
        else:
            blocks.pop(index)
    if not blocks:
        return
    spare = (bottom - top) - total()
    joints = len(blocks) - 1
    extra = min(spare * 0.6 / joints, 16) if joints else 0
    y = top + (spare - extra * joints) / 2
    for i, block in enumerate(blocks):
        if i:
            y += block.gap + extra
        block.draw(img, y)
        y += block.height


def _text_block(text: str, path: str, size: int, fill, keep: int, gap: float = 8, width: float = WIDTH - 2 * SAFE_X,
                shadow: bool = False) -> _Block | None:
    if not text:
        return None
    fitted, font = _fit(text, path, size, width)
    return _Block(_line_height(font), lambda img, y: _draw_text(img, WIDTH / 2, y, fitted, font, fill, shadow=shadow),
                  keep, gap)


# ----------------------------------------------------------------------
# Match card
# ----------------------------------------------------------------------
_LEFT_X = 136
_RIGHT_X = 344
_COLUMN = 184  # usable width per team column


def _pair_fit(texts: tuple[str, str], path: str, size: int, width: float = _COLUMN):
    """Fit each team's text on its own; both share the full-size line height."""
    fitted = [_fit(text, path, size, width) for text in texts]
    return fitted, _line_height(_font(path, size))


def _names_block(spec: MatchCard, size: int, keep: int, gap: float) -> _Block:
    fitted, height = _pair_fit((spec.first.name, spec.second.name), _BOLD, size)

    def draw(img: Image.Image, y: float) -> None:
        for side, (text, font), cx in ((spec.first, fitted[0], _LEFT_X), (spec.second, fitted[1], _RIGHT_X)):
            # Smaller text is centred on the full-size line.
            y_text = y + (height - _line_height(font)) / 2
            _draw_text(img, cx, y_text, text, font, _WHITE, shadow=True)
            mark = font.size * 0.42
            if side.possession:
                px = cx + font.getlength(text) / 2 + mark * 0.8
                ImageDraw.Draw(img).ellipse(
                    [px, y_text + font.size * 0.35, px + mark, y_text + font.size * 0.35 + mark], fill=_GOLD)
            if side.red_cards:
                px = cx - font.getlength(text) / 2 - mark * 1.6
                for i in range(min(side.red_cards, 3)):
                    top = y_text + font.size * 0.25
                    ImageDraw.Draw(img).rounded_rectangle(
                        [px - i * mark, top, px - i * mark + mark * 0.8, top + mark * 1.2], radius=1, fill=_LIVE_RED)

    return _Block(height, draw, keep, gap)


def _pair_text_block(texts: tuple[str, str], path: str, size: int, fill, keep: int, gap: float) -> _Block | None:
    if not any(texts):
        return None
    fitted, height = _pair_fit(texts, path, size)

    def draw(img: Image.Image, y: float) -> None:
        for (text, font), cx in zip(fitted, (_LEFT_X, _RIGHT_X)):
            _draw_text(img, cx, y + (height - _line_height(font)) / 2, text, font, fill)

    return _Block(height, draw, keep, gap)


def _logos_block(spec: MatchCard, logos: Logos, size: int, keep: int, dim_losers: bool, joiner: str = "",
                 joiner_size: int = 30) -> _Block:
    def make(logo_size: int) -> _Block:
        def draw(img: Image.Image, y: float) -> None:
            cy = y + logo_size / 2
            for side, cx in ((spec.first, _LEFT_X), (spec.second, _RIGHT_X)):
                loser = dim_losers and side.winner is False
                _glow(img, cx, cy, logo_size * 0.57, 30 if loser else 46)
                _logo(img, logos, side.logo, side.abbr, side.color, cx, cy, logo_size, dim=loser)
            if joiner:
                font = _font(_BOLD, joiner_size)
                _draw_text(img, WIDTH / 2, cy, joiner, font, (236, 238, 244), anchor="mm")

        smaller = (lambda: make(int(logo_size * 0.82))) if logo_size > 64 else None
        return _Block(logo_size, draw, keep, 0, smaller)

    return make(size)


def _render_pre(img: Image.Image, spec: MatchCard, logos: Logos) -> None:
    ts = spec.text_size
    blocks: list[_Block | None] = [
        _text_block(spec.league.upper(), _BOLD, _px(15, ts), (222, 226, 236), keep=4, width=WIDTH - 2 * SAFE_X - 70),
        _logos_block(spec, logos, round(122 / _scale(ts) ** 0.6), keep=10, dim_losers=False, joiner=spec.joiner,
                     joiner_size=_px(30, ts)),
        _names_block(spec, _px(22, ts), keep=9, gap=10),
        _pair_text_block((spec.first.detail, spec.second.detail), _REGULAR, _px(15, ts), _SOFT, keep=3, gap=2),
    ]
    if spec.kind == "off":
        font = _font(_BOLD, _px(22, ts))
        blocks.append(_Block(_pill_height(font), lambda im, y: _pill(im, WIDTH / 2, y, spec.status.upper(), font,
                                                                      (120, 30, 40, 230)), 8, 18))
        blocks.append(_text_block(f"was {spec.day}" if spec.day else "", _REGULAR, _px(18, ts), _SOFT, keep=6))
    else:
        blocks.append(_text_block(spec.big_time or "TBD", _BOLD, _px(58, ts), _WHITE, keep=8, gap=14, shadow=True))
        blocks.append(_text_block(spec.day, _BOLD, _px(22, ts), _SOFT, keep=7, gap=4))
        if spec.countdown:
            font = _font(_BOLD, _px(15, ts))
            blocks.append(_Block(_pill_height(font), lambda im, y: _pill(im, WIDTH / 2, y, spec.countdown, font,
                                                                          (255, 255, 255, 46)), 5, 8))
    blocks.append(_text_block(spec.footer, _REGULAR, _px(14, ts), _DIM, keep=2, gap=10))
    _stack(img, [block for block in blocks if block is not None])


def _diamond_block(spec: MatchCard, ts: str) -> _Block:
    font = _font(_BOLD, _px(18, ts))
    outs = "" if spec.outs is None else f"{spec.outs} out" + ("" if spec.outs == 1 else "s")
    line = "  •  ".join(part for part in (outs, spec.count) if part)
    size = _px(11, ts)
    height = size * 4 + 4

    def draw(img: Image.Image, y: float) -> None:
        diamond_w = size * 5
        left = WIDTH / 2 - (diamond_w + 12 + font.getlength(line)) / 2
        cx, cy = left + diamond_w / 2, y + height / 2 + size * 0.6
        spots = {1: (cx + size * 1.45, cy), 2: (cx, cy - size * 1.45), 3: (cx - size * 1.45, cy)}
        draw_ = ImageDraw.Draw(img)
        for base, (x, by) in spots.items():
            filled = spec.bases[base - 1] if spec.bases else False
            draw_.polygon([(x, by - size), (x + size, by), (x, by + size), (x - size, by)],
                          fill=_GOLD if filled else (255, 255, 255, 40), outline=(255, 255, 255, 200))
        _draw_text(img, left + diamond_w + 12, y + height / 2, line, font, _WHITE, anchor="lm")

    return _Block(height, draw, 5, 10)


def _plays_block(spec: MatchCard, ts: str, lines: int) -> _Block | None:
    rows = max(len(spec.first.plays), len(spec.second.plays))
    lines = min(lines, rows)
    if lines <= 0:
        return None
    font = _font(_REGULAR, _px(14, ts))
    line_h = _line_height(font) + 2
    width = WIDTH / 2 - SAFE_X - 6

    def draw(img: Image.Image, y: float) -> None:
        for side, anchor, x in ((spec.first, "la", SAFE_X), (spec.second, "ra", WIDTH - SAFE_X)):
            for index, play in enumerate(side.plays[-lines:]):
                text, pfont = _fit(play, _REGULAR, font.size, width)
                _draw_text(img, x, y + index * line_h, text, pfont, _SOFT, anchor=anchor)

    return _Block(line_h * lines, draw, 3, 12, (lambda: _plays_block(spec, ts, lines - 1)) if lines > 1 else None)


def _render_scoreboard(img: Image.Image, spec: MatchCard, logos: Logos) -> None:
    ts = spec.text_size
    live = spec.kind == "live"
    final = spec.kind == "final"
    score_font = _font(_BOLD, round(84 * _scale(ts) ** 0.5))
    lose = (150, 156, 172)

    def scores(img_: Image.Image, y: float) -> None:
        for side, cx in ((spec.first, _LEFT_X), (spec.second, _RIGHT_X)):
            text, font = _fit(side.score or "0", _BOLD, score_font.size, _COLUMN)
            _draw_text(img_, cx, y, text, font, lose if final and side.winner is False else _WHITE, shadow=True)
        _draw_text(img_, WIDTH / 2, y + _line_height(score_font) * 0.42, "–", _font(_BOLD, score_font.size // 2),
                   (210, 214, 224), anchor="mm")

    status = spec.status or ("LIVE" if live else "FINAL")
    pill_font = _font(_BOLD, _px(16, ts))

    def pill(img_: Image.Image, y: float) -> None:
        if live:
            _pill(img_, WIDTH / 2, y, status, pill_font, _LIVE_RED + (240,), dot=True)
        else:
            _pill(img_, WIDTH / 2, y, status.upper(), pill_font, (255, 255, 255, 52))

    blocks: list[_Block | None] = [
        _text_block(spec.league.upper(), _BOLD, _px(15, ts), (222, 226, 236), keep=4, width=WIDTH - 2 * SAFE_X - 70),
        _logos_block(spec, logos, round(100 / _scale(ts) ** 0.7), keep=7, dim_losers=final),
        _names_block(spec, _px(20, ts), keep=9, gap=8),
        _Block(_line_height(score_font) * 0.86, scores, 10, 2),
        _pair_text_block(
            (f"({spec.first.shootout})" if spec.first.shootout else "",
             f"({spec.second.shootout})" if spec.second.shootout else ""),
            _BOLD, _px(18, ts), _SOFT, keep=8, gap=0),
        _Block(_pill_height(pill_font), pill, 9, 10),
    ]
    if spec.first.plays or spec.second.plays:
        blocks.append(_plays_block(spec, ts, 3 if ts == TEXT_NORMAL else 2))
    elif live and spec.bases is not None:
        blocks.append(_diamond_block(spec, ts))
    elif live and spec.situation:
        blocks.append(_text_block(spec.situation, _REGULAR, _px(16, ts), _SOFT, keep=5, gap=10))
    if not (spec.first.plays or spec.second.plays):
        blocks.append(_text_block(spec.footer, _REGULAR, _px(14, ts), _DIM, keep=2, gap=10))
    _stack(img, [block for block in blocks if block is not None])


def render_match(spec: MatchCard, logos: Logos) -> bytes:
    img = _background(spec.first.color, spec.second.color)
    if spec.kind in ("live", "final"):
        _render_scoreboard(img, spec, logos)
    else:
        _render_pre(img, spec, logos)
    if spec.stale:
        _stale_badge(img)
    return _jpeg(img)


# ----------------------------------------------------------------------
# League cards
# ----------------------------------------------------------------------
def _header_fonts(text_size: str):
    return _font(_BOLD, _px(24, text_size)), _font(_REGULAR, _px(15, text_size))


def _header_bottom(text_size: str) -> float:
    title, subtitle = _header_fonts(text_size)
    return 18 + _line_height(title) + 4 + _line_height(subtitle) + 12


def _score_metrics(text_size: str) -> tuple[float, float, int]:
    """(first row y, row height, rows per page) for the scoreboard card."""
    top = _header_bottom(text_size)
    row_h = round(52 * _scale(text_size) ** 0.85)
    return top, row_h, max(1, int((BOTTOM - top) // row_h))


def _table_metrics(text_size: str) -> tuple[float, float, float, int]:
    """(column header y, first row y, row height, rows per page) for the table card."""
    head_y = _header_bottom(text_size)
    head_h = _line_height(_font(_BOLD, _px(13, text_size))) + 6
    top = head_y + head_h
    row_h = round(29 * _scale(text_size) ** 0.9)
    return head_y, top, row_h, max(1, int((BOTTOM - top) // row_h))


def score_rows(text_size: str) -> int:
    """Games per scoreboard page at this text size."""
    return _score_metrics(text_size)[2]


def table_rows(text_size: str) -> int:
    """Teams per table page at this text size."""
    return _table_metrics(text_size)[3]


def _card_header(img: Image.Image, title: str, subtitle: str, page: str, logo: str, logos: Logos,
                 text_size: str) -> None:
    title_font, subtitle_font = _header_fonts(text_size)
    x = SAFE_X
    if logo and logos.get(logo) is not None:
        size = _line_height(title_font) + _line_height(subtitle_font) - 4
        _logo(img, logos, logo, "", "", SAFE_X + size / 2, 18 + size / 2 + 2, size, shadow=False)
        x += size + 10
    page_font = _font(_BOLD, _px(14, text_size))
    right = WIDTH - SAFE_X - (page_font.getlength(page) + 10 if page else 0)
    text, font = _fit(title, _BOLD, title_font.size, right - x)
    _draw_text(img, x, 18, text, font, _WHITE, anchor="la")
    text, font = _fit(subtitle, _REGULAR, subtitle_font.size, right - x)
    _draw_text(img, x, 18 + _line_height(title_font) + 4, text, font, _SOFT, anchor="la")
    if page:
        _draw_text(img, WIDTH - SAFE_X, 24, page, page_font, _DIM, anchor="ra")


def render_scores(spec: ScoresCard, logos: Logos) -> bytes:
    ts = spec.text_size
    img = _plain_background()
    _card_header(img, spec.title, spec.subtitle, spec.page, spec.league_logo, logos, ts)
    top, row_h, rows = _score_metrics(ts)
    if not spec.rows:
        _draw_text(img, WIDTH / 2, 200, "No games scheduled", _font(_BOLD, _px(20, ts)), _SOFT)
    name_font = _font(_BOLD, _px(18, ts))
    score_font = _font(_BOLD, _px(22, ts))
    status_size = _px(13, ts)
    logo_size = round(28 * _scale(ts) ** 0.8)
    for index, row in enumerate(spec.rows[:rows]):
        y = top + index * row_h
        if row.highlight:
            band = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(band).rounded_rectangle([SAFE_X - 8, y - 2, WIDTH - SAFE_X + 8, y + row_h - 6], radius=10,
                                                   fill=(255, 255, 255, 34), outline=(255, 255, 255, 90))
            img.alpha_composite(band)
        mid = y + (row_h - 6) / 2
        _logo(img, logos, row.first_logo, row.first, "", SAFE_X + logo_size / 2, mid, logo_size, shadow=False)
        _logo(img, logos, row.second_logo, row.second, "", WIDTH - SAFE_X - logo_size / 2, mid, logo_size,
              shadow=False)
        name_w = WIDTH / 2 - SAFE_X - logo_size - 8 - score_font.getlength("00 - 00") / 2 - 6
        first, font = _fit(row.first[:5], _BOLD, name_font.size, name_w)
        _draw_text(img, SAFE_X + logo_size + 8, mid, first, font, _WHITE, anchor="lm")
        second, font = _fit(row.second[:5], _BOLD, name_font.size, name_w)
        _draw_text(img, WIDTH - SAFE_X - logo_size - 8, mid, second, font, _WHITE, anchor="rm")
        if row.live or row.final:
            score_h = _line_height(score_font)
            status, sfont = _fit(row.status, _BOLD if row.live else _REGULAR, status_size, 130)
            block_h = score_h + _line_height(sfont) - 4
            y0 = mid - block_h / 2
            _draw_text(img, WIDTH / 2, y0, f"{row.first_score or 0} - {row.second_score or 0}", score_font, _WHITE)
            _draw_text(img, WIDTH / 2, y0 + score_h - 4, status, sfont, _LIVE_RED if row.live else _DIM)
        else:
            status, sfont = _fit(row.status, _BOLD, _px(17, ts), 150)
            _draw_text(img, WIDTH / 2, mid, status, sfont, _SOFT, anchor="mm")
    if spec.stale:
        _stale_badge(img)
    return _jpeg(img)


def render_table(spec: TableCard, logos: Logos) -> bytes:
    ts = spec.text_size
    img = _plain_background()
    _card_header(img, spec.title, spec.subtitle, spec.page, spec.league_logo, logos, ts)
    head_y, top, row_h, rows = _table_metrics(ts)
    value_font = _font(_REGULAR, _px(15, ts))
    bold_font = _font(_BOLD, _px(15, ts))
    head_font = _font(_BOLD, _px(13, ts))
    logo_size = round(20 * _scale(ts) ** 0.9)
    rank_w = bold_font.getlength("20") + 6
    name_x = SAFE_X + rank_w + logo_size + 10
    col_w = max(bold_font.getlength("+00"), bold_font.getlength(".000")) + 10

    # Drop the least important columns until team names have room.
    keep = list(spec.keep) if len(spec.keep) == len(spec.columns) else [1] * len(spec.columns)
    shown = list(range(len(spec.columns)))
    min_name = 150 * _scale(ts) ** 0.5
    while shown and (WIDTH - SAFE_X - col_w * len(shown)) - name_x < min_name:
        shown.remove(min(shown, key=lambda i: (keep[i], -i)))
    right = WIDTH - SAFE_X
    cols_x = [right - col_w * (len(shown) - n) + col_w / 2 for n in range(len(shown))]
    for x, index in zip(cols_x, shown):
        _draw_text(img, x, head_y, spec.columns[index], head_font, _DIM)
    name_right = (cols_x[0] - col_w / 2 - 4) if cols_x else right

    for row_index, line in enumerate(spec.lines[:rows]):
        y = top + row_index * row_h
        mid = y + (row_h - 4) / 2
        if line.highlight:
            band = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(band).rounded_rectangle([SAFE_X - 8, y - 2, right + 8, y + row_h - 3], radius=8,
                                                   fill=(255, 255, 255, 40))
            img.alpha_composite(band)
        if line.note_color:
            ImageDraw.Draw(img).rectangle([SAFE_X - 6, y + 2, SAFE_X - 3, y + row_h - 6], fill=_rgb(line.note_color))
        font = bold_font if line.highlight else value_font
        _draw_text(img, SAFE_X + rank_w / 2, mid, line.rank, font, _SOFT, anchor="mm")
        _logo(img, logos, line.logo, line.name[:3], "", SAFE_X + rank_w + logo_size / 2 + 4, mid, logo_size,
              shadow=False)
        text, nfont = _fit(line.name, _BOLD if line.highlight else _REGULAR, font.size, name_right - name_x)
        _draw_text(img, name_x, mid, text, nfont, _WHITE, anchor="lm")
        for x, index in zip(cols_x, shown):
            value = line.values[index] if index < len(line.values) else ""
            vtext, vfont = _fit(value, _BOLD if line.highlight else _REGULAR, font.size, col_w - 2)
            _draw_text(img, x, mid, vtext, vfont, _WHITE, anchor="mm")
    if not spec.lines:
        _draw_text(img, WIDTH / 2, 200, "Table not available yet", _font(_BOLD, _px(20, ts)), _SOFT)
    if spec.stale:
        _stale_badge(img)
    return _jpeg(img)


def render_message(spec: MessageCard, logos: Logos) -> bytes:
    ts = spec.text_size
    img = _plain_background(spec.color)
    blocks: list[_Block | None] = []
    if spec.logo:
        size = round(130 / _scale(ts) ** 0.6)

        def logo(img_: Image.Image, y: float) -> None:
            _glow(img_, WIDTH / 2, y + size / 2, size * 0.55, 40)
            _logo(img_, logos, spec.logo, spec.title[:3], spec.color, WIDTH / 2, y + size / 2, size)

        blocks.append(_Block(size, logo, 6, 0))
    blocks.append(_text_block(spec.title, _BOLD, _px(26, ts), _WHITE, keep=9, gap=16))
    blocks.append(_text_block(spec.text, _REGULAR, _px(17, ts), _SOFT, keep=8, gap=8))
    for index, line in enumerate(spec.lines[:3]):
        blocks.append(_text_block(line, _REGULAR, _px(15, ts), _DIM, keep=3 - index, gap=6))
    _stack(img, [block for block in blocks if block is not None])
    return _jpeg(img)
