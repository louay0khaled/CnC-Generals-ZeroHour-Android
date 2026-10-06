#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import struct
import zipfile
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw


WIDTH = 1640
HEIGHT = 720
DESIGN_W = 1920
DESIGN_H = 1080

MENU_COUNT = 67

BUTTON_TEXT_ENABLED = "225 240 255 255"
BUTTON_TEXT_HILITE = "120 235 255 255"
BUTTON_TEXT_DISABLED = "90 100 120 255"
BUTTON_TEXT_BORDER = "0 0 0 255"

BUTTON_ENABLED = ("10 22 40 215", "40 140 220 255")
BUTTON_SELECTED = ("0 110 170 235", "120 230 255 255")
BUTTON_HILITE = ("18 60 100 235", "90 220 255 255")
BUTTON_HILITE_SELECTED = ("0 130 190 245", "160 240 255 255")
BUTTON_DISABLED = ("20 24 30 160", "60 70 85 200")
TRANSPARENT_DRAW = ("255 255 255 0", "255 255 255 0")

COMMAND_RANGES = {
    "L": (0, 466),
    "C": (466, 1475),
    "R": (1475, 1920),
}

COMMAND_BAR_BASES = {
    "AmericaProCommandBar": "AmericaCommandBarPro_4096_1024.tga",
    "ChinaProCommandBar": "ChinaCommandBarPro_4096_1024.tga",
    "GlaProCommandBar": "GlaCommandBarPro_4096_1024.tga",
    "ObserverProCommandBar": "ObsCommandBarPro_4096_1024.tga",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\r\n")


def token_counts(text: str) -> dict[str, int]:
    clean = re.sub(r"(?m)^\s*;.*$", "", text)
    return {
        "WINDOW": len(re.findall(r"(?m)^\s*WINDOW\s*$", clean)),
        "CHILD": len(re.findall(r"(?m)^\s*CHILD\s*$", clean)),
        "END": len(re.findall(r"(?m)^\s*END\s*$", clean)),
        "ENDALLCHILDREN": len(re.findall(r"(?m)^\s*ENDALLCHILDREN\s*$", clean)),
    }


def even_int(value: float) -> int:
    return int(round(value / 2.0) * 2)


def baseline(v: int) -> float:
    return v / 2.0


def scale_for_x(x: float) -> float:
    if x < 466:
        return 0.75
    if x >= 1475:
        return 0.80
    return 0.93


def fx(x: float, scale: float) -> float:
    if scale == 0.75:
        return x * scale
    if scale == 0.80:
        return WIDTH - (DESIGN_W - x) * scale
    return WIDTH / 2.0 + (x - DESIGN_W / 2.0) * scale


def fy(y: float, scale: float) -> float:
    return HEIGHT - (DESIGN_H - y) * scale


def transform_control_rect(x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int, int]:
    bx1, by1, bx2, by2 = map(baseline, (x1, y1, x2, y2))

    if bx1 == 0 and by1 == 0 and bx2 == DESIGN_W and by2 == DESIGN_H:
        return 0, 0, WIDTH, HEIGHT

    if bx1 <= 0 and bx2 >= DESIGN_W:
        s = 0.75
        return (
            0,
            even_int(fy(by1, s)),
            WIDTH,
            even_int(fy(by2, s)),
        )

    center = (bx1 + bx2) / 2.0
    s = scale_for_x(center)
    return (
        even_int(fx(bx1, s)),
        even_int(fy(by1, s)),
        even_int(fx(bx2, s)),
        even_int(fy(by2, s)),
    )


def transform_power_rect(x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int, int]:
    bx1, by1, bx2, by2 = map(baseline, (x1, y1, x2, y2))
    yb = (HEIGHT - (DESIGN_H - 802) * 0.80) - 10
    def px(x: float) -> float:
        return WIDTH - (DESIGN_W - x) * 0.70
    def py(y: float) -> float:
        return yb - (788 - y) * 0.70
    return (
        even_int(px(bx1)),
        even_int(py(by1)),
        even_int(px(bx2)),
        even_int(py(by2)),
    )


def transform_main_rect(
    name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> tuple[int, int, int, int]:
    if name == "MainMenu.wnd:MainMenuParent":
        return 0, 0, WIDTH, HEIGHT
    if name == "MainMenu.wnd:MainMenuRuler":
        return 14, 14, 1626, 706

    bx1, by1, bx2, by2 = map(float, (x1, y1, x2, y2))
    right_group = bool(
        re.search(r"(^|:)Logo$", name)
        or ":MapBorder" in name
        or ":EarthMap" in name
        or re.search(r":Button", name)
    )
    s = 1.4 if right_group else 1.2
    if right_group:
        nx1 = WIDTH - (800 - bx1) * s
        nx2 = WIDTH - (800 - bx2) * s
    else:
        nx1 = bx1 * s
        nx2 = bx2 * s
    ny1 = by1 * s
    ny2 = by2 * s
    return even_int(nx1), even_int(ny1), even_int(nx2), even_int(ny2)


def replace_screenrect(
    header: str,
    rect_transform,
) -> str:
    pattern = re.compile(
        r"(SCREENRECT\s*=\s*UPPERLEFT:\s*)(-?\d+)\s+(-?\d+)"
        r"(,\s*BOTTOMRIGHT:\s*)(-?\d+)\s+(-?\d+)"
        r"(,\s*CREATIONRESOLUTION:\s*)(-?\d+)\s+(-?\d+)(;)",
        re.S,
    )

    def repl(m: re.Match[str]) -> str:
        x1, y1, x2, y2 = map(int, (m.group(2), m.group(3), m.group(5), m.group(6)))
        nx1, ny1, nx2, ny2 = rect_transform(x1, y1, x2, y2)
        return (
            f"{m.group(1)}{nx1} {ny1}"
            f"{m.group(4)}{nx2} {ny2}"
            f"{m.group(7)}{WIDTH} {HEIGHT}{m.group(9)}"
        )

    out, n = pattern.subn(repl, header, count=1)
    if n:
        return out

    return re.sub(
        r"(CREATIONRESOLUTION:\s*)\d+\s+\d+;",
        rf"\g<1>{WIDTH} {HEIGHT};",
        header,
    )


def get_header_bounds(lines: list[str], start: int, end: int) -> tuple[int, int]:
    first_child = end
    for i in range(start + 1, end):
        if lines[i].strip() == "CHILD":
            first_child = i
            break
        if lines[i].strip() == "WINDOW":
            first_child = i
            break
    return start + 1, first_child


def wnd_blocks(lines: list[str]) -> list[tuple[int, int]]:
    stack: list[int] = []
    blocks: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s == "WINDOW":
            stack.append(i)
        elif s == "END" and stack:
            start = stack.pop()
            blocks.append((start, i))
    return sorted(blocks, reverse=True)


def block_name(header: str) -> str:
    m = re.search(r'NAME\s*=\s*"([^"]+)";', header)
    return m.group(1) if m else ""


def block_type(header: str) -> str:
    m = re.search(r"WINDOWTYPE\s*=\s*([^;]+);", header)
    return m.group(1).strip() if m else ""


def replace_textcolor(header: str) -> str:
    pattern = re.compile(
        r"TEXTCOLOR\s*=\s*ENABLED:.*?HILITEBORDER:\s*[^;]+;",
        re.S,
    )
    indent_match = re.search(r"(?m)^(\s*)TEXTCOLOR\s*=", header)
    indent = indent_match.group(1) if indent_match else "  "
    replacement = (
        f"{indent}TEXTCOLOR = ENABLED:  {BUTTON_TEXT_ENABLED}, ENABLEDBORDER:  {BUTTON_TEXT_BORDER},\n"
        f"{indent}            DISABLED: {BUTTON_TEXT_DISABLED}, DISABLEDBORDER: {BUTTON_TEXT_BORDER},\n"
        f"{indent}            HILITE:   {BUTTON_TEXT_HILITE}, HILITEBORDER:   {BUTTON_TEXT_BORDER};"
    )
    return pattern.sub(replacement, header, count=1)


def drawdata_entries(
    enabled: tuple[tuple[str, str], tuple[str, str]],
    disabled: tuple[tuple[str, str], tuple[str, str]],
    hilite: tuple[tuple[str, str], tuple[str, str]],
    indent: str,
    key: str,
) -> str:
    def one(name: tuple[str, str]) -> str:
        color, border = name
        return f"IMAGE: NoImage, COLOR: {color}, BORDERCOLOR: {border},"

    selected_map = {
        "ENABLED": enabled,
        "DISABLED": disabled,
        "HILITED": hilite,
    }
    pair = selected_map[key]
    entries = [pair[0], pair[1]] + [TRANSPARENT_DRAW] * 7
    lines = [f"{indent}{key}DRAWDATA = "]
    for idx, item in enumerate(entries):
        color, border = item
        comma = "," if idx < len(entries) - 1 else ";"
        prefix = "" if idx == 0 else f"{indent}                  "
        lines.append(f"{prefix}IMAGE: NoImage, COLOR: {color}, BORDERCOLOR: {border}{comma}")
    return "\n".join(lines)


def replace_drawdata(header: str, key: str, pair0: tuple[str, str], pair1: tuple[str, str]) -> str:
    pattern = re.compile(
        rf"(?m)^(\s*){key}DRAWDATA\s*=.*?(?=^\s*[A-Z]+DRAWDATA\s*=|^\s*END\s*$)",
        re.S,
    )
    m = pattern.search(header)
    if not m:
        return header
    indent = m.group(1)
    if key == "ENABLED":
        draw = drawdata_entries((pair0, pair1), (pair0, pair1), (pair0, pair1), indent, key)
    elif key == "DISABLED":
        draw = drawdata_entries((pair0, pair1), (pair0, pair1), (pair0, pair1), indent, key)
    else:
        draw = drawdata_entries((pair0, pair1), (pair0, pair1), (pair0, pair1), indent, key)
    return header[:m.start()] + draw + "\n" + header[m.end():]


def make_flat_button(header: str) -> str:
    if block_type(header) != "PUSHBUTTON":
        return header
    if not re.search(r"IMAGE:\s*Buttons", header):
        return header

    header = re.sub(r"\+IMAGE\b", "", header, count=1)
    header = replace_textcolor(header)

    for key, pair in (
        ("ENABLED", (BUTTON_ENABLED, BUTTON_SELECTED)),
        ("DISABLED", (BUTTON_DISABLED, BUTTON_DISABLED)),
        ("HILITED", (BUTTON_HILITE, BUTTON_HILITE_SELECTED)),
    ):
        pattern = re.compile(
            rf"(?m)^(\s*){key}DRAWDATA\s*=.*?(?=^\s*[A-Z]+DRAWDATA\s*=|^\s*END\s*$)",
            re.S,
        )
        m = pattern.search(header)
        if m:
            indent = m.group(1)
            lines = []
            entries = [pair[0], pair[1]] + [TRANSPARENT_DRAW] * 7
            lines.append(f"{indent}{key}DRAWDATA = ")
            for idx, (color, border) in enumerate(entries):
                if idx == 0:
                    prefix = ""
                else:
                    prefix = f"{indent}                  "
                comma = "," if idx < len(entries) - 1 else ";"
                lines.append(
                    f"{prefix}IMAGE: NoImage, COLOR: {color}, BORDERCOLOR: {border}{comma}"
                )
            replacement = "\n".join(lines)
            header = header[:m.start()] + replacement + "\n" + header[m.end():]
    return header


def style_panel(header: str) -> str:
    name = block_name(header)
    if not re.search(r":MapBorder[^:]*$", name):
        return header
    panel = ("4 10 20 190", "40 140 220 255")
    for key in ("ENABLED", "DISABLED", "HILITED"):
        pattern = re.compile(
            rf"(?m)^(\s*){key}DRAWDATA\s*=.*?(?=^\s*[A-Z]+DRAWDATA\s*=|^\s*END\s*$)",
            re.S,
        )
        m = pattern.search(header)
        if not m:
            continue
        indent = m.group(1)
        entries = [panel] + [TRANSPARENT_DRAW] * 8
        lines = [f"{indent}{key}DRAWDATA = "]
        for idx, (color, border) in enumerate(entries):
            prefix = "" if idx == 0 else f"{indent}                  "
            comma = "," if idx < 8 else ";"
            lines.append(f"{prefix}IMAGE: NoImage, COLOR: {color}, BORDERCOLOR: {border}{comma}")
        header = header[:m.start()] + "\n".join(lines) + "\n" + header[m.end():]
    return header


def modernize_wnd(
    text: str,
    *,
    mode: str,
) -> str:
    original_counts = token_counts(text)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)

    for start, end in wnd_blocks(lines):
        hs, he = get_header_bounds(lines, start, end)
        header = "".join(lines[hs:he])
        name = block_name(header)
        wtype = block_type(header)

        if mode == "main":
            header = replace_screenrect(header, lambda a, b, c, d: transform_main_rect(name, a, b, c, d))
            if name == "MainMenu.wnd:MainMenuRuler":
                # The texture provides the translucent panel/grid; draw-data supplies a crisp flat frame.
                header = re.sub(
                    r"(?s)(?m)^\s*ENABLEDDRAWDATA\s*=.*?(?=^\s*[A-Z]+DRAWDATA\s*=)",
                    "  ENABLEDDRAWDATA = IMAGE: MainMenuRuler, COLOR: 255 255 255 255, BORDERCOLOR: 40 140 220 255,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0,\n                    IMAGE: NoImage, COLOR: 255 255 255 0, BORDERCOLOR: 255 255 255 0;\n",
                    header,
                    count=1,
                )
            header = make_flat_button(header)
            header = style_panel(header)
        elif mode == "menu":
            header = make_flat_button(header)
            header = style_panel(header)
            header = re.sub(r"\b47\s+55\s+168\b", "40 140 220", header)
            header = re.sub(r"\b49\s+55\s+168\b", "40 140 220", header)
            header = re.sub(r"\b186\s+255\s+12\b", "120 235 255", header)
            header = re.sub(r"\b209\s+253\s+4\b", "120 235 255", header)
        elif mode == "control":
            header = replace_screenrect(header, transform_control_rect)
        elif mode == "power":
            header = replace_screenrect(header, transform_power_rect)

        lines[hs:he] = [header]

    out = "".join(lines)

    if mode in ("menu", "main"):
        out = re.sub(r"\b47\s+55\s+168\b", "40 140 220", out)
        out = re.sub(r"\b49\s+55\s+168\b", "40 140 220", out)
        out = re.sub(r"\b186\s+255\s+12\b", "120 235 255", out)
        out = re.sub(r"\b209\s+253\s+4\b", "120 235 255", out)

    if token_counts(out) != original_counts:
        raise ValueError(f"WND token counts changed: {original_counts} -> {token_counts(out)}")

    return out


def parse_xy_line(line: str) -> tuple[int, int] | None:
    m = re.search(r"X:(-?\d+)\s+Y:(-?\d+)", line)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def replace_xy(line: str, x: int, y: int) -> str:
    return re.sub(r"X:-?\d+\s+Y:-?\d+", f"X:{x} Y:{y}", line, count=1)


def transform_scheme(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.strip() == "ImagePart":
            j = i + 1
            depth = 0
            block = [line]
            while j < len(lines):
                block.append(lines[j])
                if lines[j].strip() == "ImagePart":
                    depth += 1
                if lines[j].strip() == "End":
                    if depth == 0:
                        break
                    depth -= 1
                j += 1
            block_text = "".join(block)
            im = re.search(r"ImageName\s+(\S+ProCommandBar)\b", block_text)
            if im:
                base = im.group(1)
                y_base = 568
                # Exact baseline design is 1920x1080 and command-bar source is 1920x512.
                pieces = []
                for key, (left, right) in COMMAND_RANGES.items():
                    if key == "L":
                        s = 0.75
                        x = fx(left, s)
                        y = fy(y_base, s)
                    elif key == "C":
                        s = 0.93
                        x = fx(left, s)
                        y = fy(y_base, s)
                    else:
                        s = 0.80
                        x = fx(left, s)
                        y = fy(y_base, s)
                    w = (right - left) * s
                    h = 512 * s
                    pieces.append(
                        "  ImagePart\n"
                        f"    Position X:{even_int(x)} Y:{even_int(y)}\n"
                        f"    Size X:{even_int(w)} Y:{even_int(h)}\n"
                        f"    ImageName {base}{key}\n"
                        "    Layer 4 ;; Control Bar Pro split piece\n"
                        "  End\n"
                    )
                out.append("".join(pieces))
                i = j + 1
                continue

        if re.search(r"ScreenCreationRes\s+X:\d+\s+Y:\d+", line):
            out.append(re.sub(r"ScreenCreationRes\s+X:\d+\s+Y:\d+", "ScreenCreationRes X:1640 Y:720", line))
            i += 1
            continue

        stripped = line.strip()
        xy = parse_xy_line(line)
        if xy and (
            re.match(r"^(?:\w+UL|\w+LR|FinalPos|Position|Size)\b", stripped)
            or stripped.startswith("ImagePart")
        ):
            bx, by = baseline(xy[0]), baseline(xy[1])
            is_size = bool(re.match(r"^Size\b", stripped))
            if is_size:
                # Size follows Position in official ControlBarScheme entries; use the latest Position scale.
                scale = 0.93
                for prev in reversed(out[-8:]):
                    if prev.strip().startswith("Position "):
                        pxy = parse_xy_line(prev)
                        if pxy:
                            scale = scale_for_x(baseline(pxy[0]))
                            break
                nx = even_int(bx * scale)
                ny = even_int(by * scale)
            else:
                scale = scale_for_x(bx)
                nx = even_int(fx(bx, scale))
                ny = even_int(fy(by, scale))
            out.append(replace_xy(line, nx, ny))
        else:
            out.append(line)
        i += 1

    return "".join(out)


def commandbar_mapped_image_block(name: str, texture: str, suffix: str, left: int, right: int) -> str:
    return (
        f"MappedImage {name}{suffix}\n"
        f"  Texture = {texture}\n"
        "  TextureWidth = 1920\n"
        "  TextureHeight = 512\n"
        f"  Coords = Left:{left} Top:0 Right:{right} Bottom:512\n"
        "  Status = NONE\n"
        "End\n\n"
    )


def rewrite_commandbar_mapping(path: Path, base_name: str, texture: str) -> None:
    text = (
        f"MappedImage {base_name}\n"
        f"  Texture = {texture}\n"
        "  TextureWidth = 1920\n"
        "  TextureHeight = 512\n"
        "  Coords = Left:0 Top:0 Right:1920 Bottom:512\n"
        "  Status = NONE\n"
        "End\n\n"
        + commandbar_mapped_image_block(base_name, texture, "L", *COMMAND_RANGES["L"])
        + commandbar_mapped_image_block(base_name, texture, "C", *COMMAND_RANGES["C"])
        + commandbar_mapped_image_block(base_name, texture, "R", *COMMAND_RANGES["R"])
    )
    write_text(path, text)


def main_menu_name(path: Path) -> str:
    return path.name


def parse_mapped_images(root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    base = root / "Data" / "INI" / "MappedImages" / "TextureSize_512"
    for path in sorted(base.glob("*.INI")):
        text = read_text(path)
        pattern = re.compile(r"(?ms)^MappedImage\s+(\S+)\s*\n(.*?)^End\s*$")
        for m in pattern.finditer(text):
            name, body = m.group(1), m.group(2)
            tm = re.search(r"Texture\s*=\s*(\S+)", body)
            wm = re.search(r"TextureWidth\s*=\s*(\d+)", body)
            hm = re.search(r"TextureHeight\s*=\s*(\d+)", body)
            cm = re.search(r"Coords\s*=\s*Left:(-?\d+)\s+Top:(-?\d+)\s+Right:(-?\d+)\s+Bottom:(-?\d+)", body)
            if tm and wm and hm and cm:
                result[name] = {
                    "texture": tm.group(1),
                    "width": int(wm.group(1)),
                    "height": int(hm.group(1)),
                    "coords": tuple(map(int, cm.groups())),
                }
    return result


def gadget_match(name: str) -> bool:
    return bool(
        re.match(r"^ListBoxHilite.*Item.*$", name, re.I)
        or re.match(r"^TextEntry(?:Enabled|Disabled|Hilite).*$", name, re.I)
        or re.match(r"^ScrollBarThumb.*$", name, re.I)
        or re.match(r"^VSlider(?:Up|Down)Button.*$", name, re.I)
        or re.match(r"^RadioButton.*$", name, re.I)
    )


def draw_gadget(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], name: str) -> None:
    x, y, w, h = box
    fill = (5, 15, 25, 255)
    cyan = (120, 235, 255, 255)
    inner = (17, 38, 56, 255)

    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=fill)

    low = name.lower()
    sides = {
        "left": "left" in low or low.endswith("_l"),
        "right": "right" in low or low.endswith("_r"),
        "top": "top" in low or low.endswith("_t"),
        "bottom": "bottom" in low or low.endswith("_b"),
    }
    if not any(sides.values()):
        sides = {k: True for k in sides}

    if sides["left"]:
        draw.line((x, y, x, y + h - 1), fill=cyan, width=1)
    if sides["right"]:
        draw.line((x + w - 1, y, x + w - 1, y + h - 1), fill=cyan, width=1)
    if sides["top"]:
        draw.line((x, y, x + w - 1, y), fill=cyan, width=1)
    if sides["bottom"]:
        draw.line((x, y + h - 1, x + w - 1, y + h - 1), fill=cyan, width=1)

    if w > 4 and h > 4:
        draw.rectangle((x + 1, y + 1, x + w - 2, y + h - 2), outline=inner, width=1)

    if re.search(r"RadioButton", name, re.I):
        r = max(2, min(w, h) // 3)
        cx, cy = x + w // 2, y + h // 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=cyan, width=1)
        if r > 3:
            draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=cyan)

    if re.search(r"ScrollBarThumb", name, re.I) or re.search(r"TextEntry", name, re.I):
        yy = y + max(2, h // 2)
        draw.line((x + 3, yy, x + w - 4, yy), fill=cyan, width=1)
        if h > 8:
            yy2 = min(y + h - 3, yy + 4)
            draw.line((x + 3, yy2, x + w - 4, yy2), fill=cyan, width=1)

    if re.search(r"VSlider(Up|Down)Button", name, re.I):
        cx = x + w // 2
        cy = y + h // 2
        if re.search(r"Up", name, re.I):
            pts = [(cx, max(y + 2, cy - 3)), (max(x + 2, cx - 4), cy + 3), (min(x + w - 3, cx + 4), cy + 3)]
        else:
            pts = [(max(x + 2, cx - 4), max(y + 2, cy - 3)), (min(x + w - 3, cx + 4), max(y + 2, cy - 3)), (cx, min(y + h - 3, cy + 3))]
        draw.polygon(pts, fill=cyan)


def pack_gadgets(root: Path, maps: dict[str, dict]) -> tuple[dict, Path]:
    names = sorted(n for n in maps if gadget_match(n))
    if len(names) != 44:
        raise ValueError(f"Expected exactly 44 gadget images, found {len(names)}")

    atlas = Image.new("RGBA", (512, 512), (4, 10, 20, 255))
    draw = ImageDraw.Draw(atlas)
    placements = {}

    x = y = row_h = 0
    gap = 2
    for name in names:
        w = maps[name]["coords"][2] - maps[name]["coords"][0]
        h = maps[name]["coords"][3] - maps[name]["coords"][1]
        if w <= 0 or h <= 0 or w > 512 or h > 512:
            raise ValueError(f"Invalid gadget dimensions for {name}: {w}x{h}")
        if x + w > 512:
            x = 0
            y += row_h + gap
            row_h = 0
        if y + h > 512:
            raise ValueError("44 gadget atlas rectangles do not fit in 512x512")
        placements[name] = (x, y, w, h)
        draw_gadget(draw, (x, y, w, h), name)
        x += w + gap
        row_h = max(row_h, h)

    texture = root / "Art" / "Textures" / "ZProGadgets_512.tga"
    texture.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(texture, format="TGA")

    ini = root / "Data" / "INI" / "MappedImages" / "HandCreated" / "ZProGadgets.ini"
    chunks = []
    for name in names:
        x, y, w, h = placements[name]
        chunks.append(
            f"MappedImage {name}\n"
            f"  Texture = ZProGadgets_512.tga\n"
            "  TextureWidth = 512\n"
            "  TextureHeight = 512\n"
            f"  Coords = Left:{x} Top:{y} Right:{x+w} Bottom:{y+h}\n"
            "  Status = NONE\n"
            "End\n\n"
        )
    write_text(ini, "".join(chunks))
    return placements, texture


def make_loading_bar(root: Path) -> None:
    specs = {
        "LoadingBar_L": (20, 20),
        "LoadingBar_C": (10, 20),
        "LoadingBar_R": (20, 20),
        "LoadingBar_Progress": (3, 11),
        "LoadingBar_DePowered": (3, 11),
    }
    colors = {
        "fill": (5, 15, 25, 255),
        "cyan": (120, 235, 255, 255),
        "dim": (36, 72, 94, 255),
    }
    out = []
    for name, (w, h) in specs.items():
        img = Image.new("RGBA", (w, h), colors["fill"])
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, w - 1, h - 1), outline=colors["cyan"], width=1)
        if "Progress" in name:
            for yy in range(h):
                if yy % 2 == 0:
                    d.line((0, yy, w - 1, yy), fill=colors["cyan"], width=1)
        elif "DePowered" in name:
            d.rectangle((1, 1, w - 2, h - 2), outline=colors["dim"], width=1)
        else:
            mid = h // 2
            d.line((2, mid, max(2, w - 3), mid), fill=colors["dim"], width=1)
        tex = root / "Art" / "Textures" / f"ZPro{name}.tga"
        tex.parent.mkdir(parents=True, exist_ok=True)
        img.save(tex, format="TGA")
        out.append(
            f"MappedImage {name}\n"
            f"  Texture = {tex.name}\n"
            f"  TextureWidth = {w}\n"
            f"  TextureHeight = {h}\n"
            f"  Coords = Left:0 Top:0 Right:{w} Bottom:{h}\n"
            "  Status = NONE\n"
            "End\n\n"
        )
    write_text(root / "Data" / "INI" / "MappedImages" / "HandCreated" / "ZProLoadingBar.ini", "".join(out))


def make_main_menu_ruler(root: Path) -> None:
    img = Image.new("RGBA", (1024, 512), (4, 10, 20, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1023, 511), fill=(4, 10, 20, 72))
    for xx in range(0, 1024, 64):
        d.line((xx, 0, xx, 511), fill=(120, 235, 255, 18), width=1)
    for yy in range(0, 512, 64):
        d.line((0, yy, 1023, yy), fill=(120, 235, 255, 18), width=1)
    d.rectangle((1, 1, 1022, 510), outline=(120, 235, 255, 180), width=1)
    c = 18
    for x0, y0, sx, sy in (
        (1, 1, 1, 1),
        (1022, 1, -1, 1),
        (1, 510, 1, -1),
        (1022, 510, -1, -1),
    ):
        d.line((x0, y0, x0 + sx * c, y0), fill=(120, 235, 255, 255), width=2)
        d.line((x0, y0, x0, y0 + sy * c), fill=(120, 235, 255, 255), width=2)

    tex = root / "Art" / "Textures" / "ZProMainMenuRuler_1024x512.tga"
    tex.parent.mkdir(parents=True, exist_ok=True)
    img.save(tex, format="TGA")
    ini = (
        "MappedImage MainMenuRuler\n"
        "  Texture = ZProMainMenuRuler_1024x512.tga\n"
        "  TextureWidth = 1024\n"
        "  TextureHeight = 512\n"
        "  Coords = Left:0 Top:0 Right:1024 Bottom:512\n"
        "  Status = NONE\n"
        "End\n"
    )
    write_text(root / "Data" / "INI" / "MappedImages" / "HandCreated" / "ZProMainMenuRuler.ini", ini)


def copy_glob(src_root: Path, dst_root: Path, patterns: Iterable[str]) -> None:
    for pattern in patterns:
        for src in sorted(src_root.glob(pattern)):
            rel = src.relative_to(src_root)
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                shutil.copy2(src, dst)


def copy_controlbar_data(cb_root: Path, work: Path) -> None:
    edited = cb_root / "GameFilesEdited"
    lang = cb_root / "GameFilesEditedLanguage"

    copy_glob(edited, work, [
        "Data/INI/*.ini",
        "Data/INI/MappedImages/HandCreated/*.ini",
        "Window/*.wnd",
        "Window/Menus/*.wnd",
    ])
    copy_glob(lang, work, [
        "Data/Brazilian/*.ini",
        "Data/Chinese/*.ini",
        "Data/English/*.ini",
        "Data/French/*.ini",
        "Data/German/*.ini",
        "Data/Italian/*.ini",
        "Data/Korean/*.ini",
        "Data/Polish/*.ini",
        "Data/Spanish/*.ini",
        "Window/Menus/*.wnd",
    ])


def add_menu_sources(
    cb_root: Path,
    gp_root: Path,
    menus_work: Path,
) -> list[str]:
    retail_dir = gp_root / "GameFilesOriginalZH" / "Window" / "Menus"
    retail = {p.name: p for p in retail_dir.glob("*.wnd")}

    if len(retail) != MENU_COUNT:
        raise ValueError(f"Expected {MENU_COUNT} retail menu WNDs, found {len(retail)}")

    data_dir = cb_root / "GameFilesEdited" / "Window" / "Menus"
    lang_dir = cb_root / "GameFilesEditedLanguage" / "Window" / "Menus"
    selected = []

    for name, src_retail in sorted(retail.items()):
        if name == "MainMenu.wnd":
            src = src_retail
            mode = "main"
        else:
            src = data_dir / name
            if not src.is_file():
                src = lang_dir / name
            if not src.is_file():
                src = src_retail
            mode = "menu"
        out = menus_work / "Window" / "Menus" / name
        write_text(out, modernize_wnd(read_text(src), mode=mode))
        selected.append(name)

    if len(selected) != MENU_COUNT:
        raise ValueError(f"Expected {MENU_COUNT} final menus, found {len(selected)}")
    return selected


def pack_big(root: Path, out_file: Path) -> None:
    files = sorted([p for p in root.rglob("*") if p.is_file()], key=lambda p: str(p.relative_to(root)).lower())
    names = [str(p.relative_to(root)).replace("/", "\\") for p in files]

    entries = []
    header_size = 16
    for name in names:
        header_size += 8 + len(name.encode("ascii")) + 1
    data_start = header_size + 8

    offset = data_start
    blobs: list[bytes] = []
    for path, name in zip(files, names):
        data = path.read_bytes()
        entries.append((offset, len(data), name))
        blobs.append(data)
        offset += len(data)

    total_size = offset
    buf = bytearray()
    buf += b"BIGF"
    buf += struct.pack("<I", total_size)
    buf += struct.pack(">I", len(entries))
    buf += struct.pack(">I", data_start)
    for off, size, name in entries:
        buf += struct.pack(">I", off)
        buf += struct.pack(">I", size)
        buf += name.encode("ascii") + b"\x00"
    buf += b"\x00" * 8
    for blob in blobs:
        buf += blob

    if len(buf) != total_size:
        raise ValueError(f"BIG size mismatch while building {out_file.name}")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(buf)


def read_big(path: Path) -> list[tuple[str, int, int]]:
    data = path.read_bytes()
    if len(data) < 24 or data[:4] != b"BIGF":
        raise ValueError(f"{path.name}: invalid BIGF magic")
    total = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from(">I", data, 8)[0]
    data_start = struct.unpack_from(">I", data, 12)[0]
    if total != len(data):
        raise ValueError(f"{path.name}: total size mismatch")
    if data_start < 24 or data_start > len(data):
        raise ValueError(f"{path.name}: invalid data start")

    pos = 16
    entries = []
    for _ in range(count):
        if pos + 8 > len(data):
            raise ValueError(f"{path.name}: truncated index")
        off = struct.unpack_from(">I", data, pos)[0]
        size = struct.unpack_from(">I", data, pos + 4)[0]
        pos += 8
        end = data.find(b"\x00", pos)
        if end < 0:
            raise ValueError(f"{path.name}: missing filename terminator")
        name = data[pos:end].decode("ascii")
        pos = end + 1
        entries.append((name, off, size))

    if pos + 8 != data_start or data[pos:data_start] != b"\x00" * 8:
        raise ValueError(f"{path.name}: required 8-byte header padding missing")

    spans = sorted((off, off + size, name) for name, off, size in entries)
    prev_end = data_start
    for off, end, name in spans:
        if off < data_start or end > len(data) or off < prev_end:
            raise ValueError(f"{path.name}: invalid/overlapping entry {name}")
        prev_end = end

    return entries


def verify_big_semantics(path: Path, expected_menus: set[str] | None = None) -> None:
    entries = read_big(path)
    names = {name.replace("\\", "/") for name, _, _ in entries}
    if expected_menus is not None:
        actual = {
            Path(name).name
            for name in names
            if name.lower().startswith("window/menus/") and name.lower().endswith(".wnd")
        }
        if actual != expected_menus:
            missing = sorted(expected_menus - actual)
            extra = sorted(actual - expected_menus)
            raise ValueError(f"{path.name}: menu mismatch missing={missing} extra={extra}")


def apply_official_font_scaling(cb_root: Path, work: Path) -> None:
    script_dir = cb_root / "Scripts" / "Python"
    import sys
    sys.path.insert(0, str(script_dir))
    from ModifyFontSizes import ScaleFontSizesInHeaderTemplateIni, ScaleFontSizesInLanguageIni

    src = cb_root / "GameFilesEditedLanguage" / "Data" / "English"
    for name, fn in (
        ("HeaderTemplate.ini", ScaleFontSizesInHeaderTemplateIni),
        ("Language.ini", ScaleFontSizesInLanguageIni),
    ):
        src_file = src / name
        if not src_file.is_file():
            raise FileNotFoundError(src_file)
        text = read_text(src_file)
        scaled = fn(text, 1.1)
        write_text(work / "Data" / "English" / name, scaled)


def make_background_marker_transparent(work_root: Path) -> None:
    path = work_root / "Window" / "ControlBar.wnd"
    text = read_text(path)
    text = re.sub(
        r'(?s)(NAME\s*=\s*"ControlBar\.wnd:BackgroundMarker";.*?DRAWCALLBACK\s*=\s*)"[^"]+";',
        r'\1"W3DNoDraw";',
        text,
        count=1,
    )
    write_text(path, text)


def build_commandbar_texture(
    cb_root: Path,
    work_root: Path,
    psd_name: str,
    out_name: str,
) -> str:
    try:
        from psd_tools import PSDImage
    except ImportError as exc:
        raise RuntimeError("psd-tools is required for command bar texture generation") from exc

    psd_path = cb_root / "GameFilesEdited" / "Art" / "Textures" / psd_name
    if not psd_path.is_file():
        raise FileNotFoundError(psd_path)

    psd = PSDImage.open(psd_path)
    image = psd.composite().convert("RGBA")

    # Official art is 4096x1024. The Control Bar design uses the 3840x1024 mapped
    # region; scale it to the requested 1920x512 working texture.
    image = image.resize((2048, 512), Image.Resampling.BOX)
    image = image.crop((0, 0, 1920, 512))

    # Remove the reserved gaps so transparent regions reveal the game world instead
    # of the black pixels underneath the artwork.
    alpha = image.getchannel("A")
    for left, right in ((340, 592), (1326, 1625)):
        alpha.paste(0, (left, 0, right, 512))
    image.putalpha(alpha)

    out_path = work_root / "Art" / "Textures" / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="TGA")
    return out_name


def build_controlbar_big(cb_root: Path, work_root: Path, out: Path) -> None:
    copy_controlbar_data(cb_root, work_root)

    controlbar = work_root / "Window" / "ControlBar.wnd"
    write_text(controlbar, modernize_wnd(read_text(controlbar), mode="control"))
    make_background_marker_transparent(work_root)

    for name in ("GenPowersShortcutBarUS.wnd", "GenPowersShortcutBarChina.wnd", "GenPowersShortcutBarGLA.wnd"):
        path = work_root / "Window" / name
        if path.exists():
            write_text(path, modernize_wnd(read_text(path), mode="power"))

    commandbar_psds = {
        "AmericaProCommandBar": ("AmericaCommandBarPro_4096_1024.psd", "ZProAmericaCommandBar_1920x512.tga"),
        "ChinaProCommandBar": ("ChinaCommandBarPro_4096_1024.psd", "ZProChinaCommandBar_1920x512.tga"),
        "GlaProCommandBar": ("GlaCommandBarPro_4096_1024.psd", "ZProGlaCommandBar_1920x512.tga"),
        "ObserverProCommandBar": ("ObsCommandBarPro_4096_1024.psd", "ZProObsCommandBar_1920x512.tga"),
    }

    generated = {}
    for base_name, (psd_name, out_name) in commandbar_psds.items():
        generated[base_name] = build_commandbar_texture(cb_root, work_root, psd_name, out_name)

    scheme = work_root / "Data" / "INI" / "ControlBarScheme.ini"
    write_text(scheme, transform_scheme(read_text(scheme)))

    cb_maps = {
        "AmericaCommandBarPro.ini": "AmericaProCommandBar",
        "ChinaCommandBarPro.ini": "ChinaProCommandBar",
        "GlaCommandBarPro.ini": "GlaProCommandBar",
        "ObsCommandBarPro.ini": "ObserverProCommandBar",
    }
    hand = work_root / "Data" / "INI" / "MappedImages" / "HandCreated"
    for filename, base_name in cb_maps.items():
        path = hand / filename
        if path.exists():
            rewrite_commandbar_mapping(path, base_name, generated[base_name])

    apply_official_font_scaling(cb_root, work_root)
    pack_big(work_root, out)


def package_simple_big(work: Path, out: Path) -> None:
    pack_big(work, out)


def make_readme(path: Path) -> None:
    text = """Generals UI Pro — Android 1640x720
================================

الحزمة مخصصة لشاشة 1640x720 في نسخة Generals Zero Hour Android.

الملفات:
- 340_ControlBarProZH.big              : ملف Control Bar Pro الرسمي الأساسي.
- 340_ControlBarProArt1080ZH.big       : ملفات Art الرسمية بدون تعديل.
- 340_ControlBarPro1640x720ZH.big      : Control Bar Pro معدل فعليًا إلى 1640x720.
- 340_ControlBarPro0_MenusZH.big       : إعادة تصميم جميع قوائم Window/Menus (67 قائمة).
- 340_ControlBarPro0_SkinGadgetsZH.big : Skin لعناصر القوائم، قابل للحذف وحده.
- 340_ControlBarPro0_SkinLoadingZH.big : Skin لشريط التحميل، قابل للحذف وحده.
- 340_ControlBarPro0_SkinBackgroundZH.big : خلفية MainMenuRuler، قابل للحذف وحده.

التثبيت:
1. أغلق اللعبة.
2. فك الضغط.
3. انسخ ملفات BIG السبعة كلها إلى مجلد بيانات اللعبة نفسه.
4. احذف أي إصدارات قديمة من حزم UIPro/ControlBar السابقة قبل الاختبار.

الإزالة:
احذف ملفات BIG السبعة أعلاه. ملفات اللعبة الأصلية لا تُحذف.

ملاحظات:
- حزمة القوائم تحتوي 67 ملف WND من GamePatch، مع أولوية نسخ Control Bar Pro المعدلة عندما تتوفر.
- MainMenu.wnd معدل إلى 1640x720 مع مقياس 1.2 يسار و1.4 يمين حسب التصميم.
- ControlBar مقسم إلى ثلاث قطع L/C/R مع مقاييس 0.75 / 0.93 / 0.80 ومثبت أسفل الشاشة.
- تم تجنب تعديل ReplayControl.wnd وGeneralsExpPoints.wnd خارج التحويل المطلوب.
"""
    write_text(path, text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--controlbar-root", required=True, type=Path)
    ap.add_argument("--gamepatch-root", required=True, type=Path)
    ap.add_argument("--official-zip", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    cb_root = args.controlbar_root.resolve()
    gp_root = args.gamepatch_root.resolve()
    out = args.out.resolve()

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    official_extract = out / ".official"
    with zipfile.ZipFile(args.official_zip.resolve()) as zf:
        zf.extractall(official_extract)

    # Preserve official core + art exactly as distributed by the upstream project.
    core_candidates = list(official_extract.rglob("340_ControlBarProZH.big"))
    art_candidates = list(official_extract.rglob("340_ControlBarProArt1080ZH.big"))
    if len(core_candidates) != 1 or len(art_candidates) != 1:
        raise ValueError("Official release must contain exactly one core BIG and one Art1080 BIG")

    shutil.copy2(core_candidates[0], out / "340_ControlBarProZH.big")
    shutil.copy2(art_candidates[0], out / "340_ControlBarProArt1080ZH.big")

    # Menus: all 67 retail menu WNDs, with Control Bar Pro edited versions used when present.
    menus_work = out / ".work_menus"
    selected = add_menu_sources(cb_root, gp_root, menus_work)
    menu_big = out / "340_ControlBarPro0_MenusZH.big"
    package_simple_big(menus_work, menu_big)
    verify_big_semantics(menu_big, set(selected))

    # Control bar data + official font scaling.
    control_work = out / ".work_controlbar"
    control_big = out / "340_ControlBarPro1640x720ZH.big"
    build_controlbar_big(cb_root, control_work, control_big)

    # Optional independent skins.
    maps = parse_mapped_images(gp_root / "GameFilesOriginalZH")
    gadgets_work = out / ".work_gadgets"
    pack_gadgets(gadgets_work, maps)

    loading_work = out / ".work_loading"
    make_loading_bar(loading_work)

    bg_work = out / ".work_background"
    make_main_menu_ruler(bg_work)

    gadgets_big = out / "340_ControlBarPro0_SkinGadgetsZH.big"
    loading_big = out / "340_ControlBarPro0_SkinLoadingZH.big"
    background_big = out / "340_ControlBarPro0_SkinBackgroundZH.big"
    package_simple_big(gadgets_work, gadgets_big)
    package_simple_big(loading_work, loading_big)
    package_simple_big(bg_work, background_big)

    # Read every BIG with the same reader that packs our custom archives.
    for big in sorted(out.glob("*.big")):
        entries = read_big(big)
        print(f"VERIFY {big.name}: {len(entries)} entries, {big.stat().st_size} bytes")

    verify_big_semantics(
        menu_big,
        set(selected),
    )

    readme = out / "README_1640x720_AR.txt"
    make_readme(readme)

    final_zip = out.parent / "GeneralsUIPro_1640x720_Android_v2.zip"
    if final_zip.exists():
        final_zip.unlink()
    with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(out.glob("*.big")) + [readme]:
            zf.write(p, p.name)

    # Verify final zip contains exactly our BIG set.
    expected = {
        "340_ControlBarProZH.big",
        "340_ControlBarProArt1080ZH.big",
        "340_ControlBarPro1640x720ZH.big",
        "340_ControlBarPro0_MenusZH.big",
        "340_ControlBarPro0_SkinGadgetsZH.big",
        "340_ControlBarPro0_SkinLoadingZH.big",
        "340_ControlBarPro0_SkinBackgroundZH.big",
        "README_1640x720_AR.txt",
    }
    with zipfile.ZipFile(final_zip) as zf:
        actual = set(zf.namelist())
    if actual != expected:
        raise ValueError(f"Final ZIP contents mismatch missing={sorted(expected-actual)} extra={sorted(actual-expected)}")

    print(f"FINAL_ZIP={final_zip}")
    print(f"BIG_DIR={out}")


if __name__ == "__main__":
    main()
