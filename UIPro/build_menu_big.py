#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path
import re


MENU_TYPES = {
    "PUSHBUTTON",
    "RADIOBUTTON",
    "CHECKBOX",
    "COMBOBOX",
    "LISTBOX",
    "LISTBOXROW",
    "EDITTEXT",
    "SLIDER",
    "TAB",
    "TABPANEL",
}


def get_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_windows(lines: list[str]):
    stack = []
    blocks = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "WINDOW":
            stack.append((i, get_indent(line), len(stack)))
        elif stripped == "END" and stack:
            start, indent, depth = stack.pop()
            blocks.append((start, i, indent, depth))
    return blocks


def replace_first_draw_pair(line: str, color: tuple[int, int, int, int], border: tuple[int, int, int, int]) -> str:
    c = " ".join(map(str, color))
    b = " ".join(map(str, border))
    return re.sub(
        r"COLOR:s*[^,]+,s*BORDERCOLOR:s*[^,]+",
        f"COLOR: {c}, BORDERCOLOR: {b}",
        line,
        count=1,
    )


def theme_menu(text: str) -> str:
    lines = text.splitlines(keepends=True)
    blocks = parse_windows(lines)

    # Parent/root: dark, neutral shell. Child menu surfaces stay readable over it.
    root_enabled = (12, 18, 24, 238)
    root_border = (72, 88, 104, 255)

    button_enabled = (30, 39, 49, 242)
    button_border = (92, 108, 124, 255)
    button_disabled = (39, 40, 43, 215)
    button_disabled_border = (80, 82, 86, 255)
    button_hilite = (58, 70, 84, 248)
    button_hilite_border = (228, 174, 61, 255)

    panel_enabled = (24, 31, 40, 228)
    panel_border = (66, 80, 94, 255)
    panel_disabled = (31, 33, 37, 205)
    panel_disabled_border = (73, 75, 79, 255)
    panel_hilite = (46, 58, 71, 236)
    panel_hilite_border = (178, 142, 63, 255)

    # Process deepest windows first only for metadata collection; edits themselves only
    # touch direct properties of the current WINDOW (base indentation + 2), so children
    # are never accidentally restyled through a parent block.
    for start, end, base_indent, depth in sorted(blocks, key=lambda x: x[0], reverse=True):
        direct_indent = base_indent + 2
        window_type = ""
        for i in range(start + 1, end):
            if get_indent(lines[i]) == direct_indent:
                m = re.match(r"\s*WINDOWTYPE\s*=\s*([^;]+);", lines[i])
                if m:
                    window_type = m.group(1).strip().upper()
                    break

        is_root = depth == 0
        is_control = window_type in MENU_TYPES

        if not (is_root or is_control):
            # Still modernize explicit fonts and text colors for ordinary USER/static
            # containers, but do not paint a box behind labels.
            do_font = True
            enabled = disabled = hilite = None
        elif is_root:
            do_font = True
            enabled = (root_enabled, root_border)
            disabled = ((18, 22, 27, 235), root_border)
            hilite = ((22, 29, 37, 240), (108, 124, 140, 255))
        else:
            do_font = True
            enabled = (button_enabled, button_border)
            disabled = (button_disabled, button_disabled_border)
            hilite = (button_hilite, button_hilite_border)

            if window_type in {"LISTBOX", "LISTBOXROW", "EDITTEXT", "COMBOBOX", "TABPANEL", "SLIDER"}:
                enabled = (panel_enabled, panel_border)
                disabled = (panel_disabled, panel_disabled_border)
                hilite = (panel_hilite, panel_hilite_border)

        for i in range(start + 1, end):
            if get_indent(lines[i]) != direct_indent:
                continue

            line = lines[i]

            if do_font and line.lstrip().startswith("FONT = NAME:"):
                # Keep the existing size/bold while replacing the dated font family.
                line = re.sub(r'NAME:\s*"[^"]+"', 'NAME: "Arial"', line)

            if line.lstrip().startswith("TEXTCOLOR ="):
                line = (
                    '    ' * 0 + line[:direct_indent]
                    + 'TEXTCOLOR = ENABLED:  238 241 245 255, ENABLEDBORDER:  8 10 12 255,\n'
                )
                # Continuation line(s) are handled below by their existing indentation.
                # The original property is always followed by a single continuation line
                # containing DISABLED/HILITE colors.
                if i + 1 < end:
                    cont = lines[i + 1]
                    if get_indent(cont) > direct_indent:
                        cont = re.sub(
                            r'DISABLED:\s*[^,]+,\s*DISABLEDBORDER:\s*[^,]+,',
                            'DISABLED:  150 156 164 255, DISABLEDBORDER:  40 43 47 255,',
                            cont,
                        )
                        cont = re.sub(
                            r'HILITE:\s*[^,]+,\s*HILITEBORDER:\s*[^,]+;',
                            'HILITE:   255 210 92 255, HILITEBORDER:   24 28 34 255;',
                            cont,
                        )
                        lines[i + 1] = cont
                lines[i] = line
                continue

            stripped = line.lstrip()
            if enabled and stripped.startswith("ENABLEDDRAWDATA ="):
                lines[i] = replace_first_draw_pair(line, *enabled)
            elif disabled and stripped.startswith("DISABLEDDRAWDATA ="):
                lines[i] = replace_first_draw_pair(line, *disabled)
            elif hilite and stripped.startswith("HILITEDRAWDATA ="):
                lines[i] = replace_first_draw_pair(line, *hilite)

    return "".join(lines)


def build_big(entries: dict[str, bytes], out_file: Path) -> None:
    ordered = sorted(entries.items(), key=lambda kv: kv[0].lower())

    index_size = sum(8 + len(name.encode("ascii")) + 1 for name, _ in ordered)
    data_start = 16 + index_size
    positions = []
    cursor = data_start

    for _, data in ordered:
        cursor = (cursor + 3) & ~3
        positions.append(cursor)
        cursor += len(data)

    archive_size = (cursor + 3) & ~3

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("wb") as f:
        f.write(b"BIGF")
        f.write(struct.pack("<I", archive_size))
        f.write(struct.pack(">I", len(ordered)))
        f.write(struct.pack(">I", data_start))

        for (name, data), offset in zip(ordered, positions):
            encoded = name.encode("ascii")
            f.write(struct.pack(">I", offset))
            f.write(struct.pack(">I", len(data)))
            f.write(encoded + b"\0")

        cursor = f.tell()
        for (_, data), offset in zip(ordered, positions):
            if cursor < offset:
                f.write(b"\0" * (offset - cursor))
                cursor = offset
            f.write(data)
            cursor += len(data)

        if cursor < archive_size:
            f.write(b"\0" * (archive_size - cursor))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", required=True)
    ap.add_argument("--edited", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    original = Path(args.original)
    edited = Path(args.edited)

    originals = {p.name: p for p in original.glob("*.wnd")}
    edited_files = {p.name: p for p in edited.glob("*.wnd")}

    names = sorted(set(originals) | set(edited_files))
    if len(names) != 37:
        raise SystemExit(f"Expected 37 menu files, found {len(names)}")

    entries = {}
    for name in names:
        source = edited_files.get(name) or originals[name]
        themed = theme_menu(source.read_text(encoding="utf-8"))
        entries[f"Window/Menus/{name}"] = themed.encode("utf-8")

    build_big(entries, Path(args.output))
    print(f"Built {args.output} with {len(entries)} themed menu files")


if __name__ == "__main__":
    main()
