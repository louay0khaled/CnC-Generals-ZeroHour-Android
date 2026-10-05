#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

MENU_GLOB = "*.wnd"

TEXT_ENABLED = "255 214 102 255"
TEXT_ENABLED_BORDER = "10 12 15 255"
TEXT_DISABLED = "148 154 163 255"
TEXT_DISABLED_BORDER = "30 33 38 255"
TEXT_HILITE = "255 225 130 255"
TEXT_HILITE_BORDER = "10 12 15 255"

DRAW_ENABLED = "24 30 38 255"
DRAW_ENABLED_BORDER = "91 108 125 255"
DRAW_DISABLED = "18 21 26 235"
DRAW_DISABLED_BORDER = "67 73 81 255"
DRAW_HILITE = "49 60 74 255"
DRAW_HILITE_BORDER = "229 173 64 255"


def theme_wnd(text: str) -> str:
    original = text
    lines = text.splitlines(keepends=True)

    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()

        if stripped.startswith("FONT = NAME:"):
            line = re.sub(r'NAME:\s*"[^"]+"', 'NAME: "Arial"', line)

        if stripped.startswith("TEXTCOLOR ="):
            line = re.sub(
                r"ENABLED:\s*[^,]+,\s*ENABLEDBORDER:\s*[^,]+,",
                f"ENABLED:  {TEXT_ENABLED}, ENABLEDBORDER:  {TEXT_ENABLED_BORDER},",
                line,
                count=1,
            )

        if "DISABLED:" in line and "DISABLEDBORDER:" in line:
            line = re.sub(
                r"DISABLED:\s*[^,]+,\s*DISABLEDBORDER:\s*[^,]+,",
                f"DISABLED:  {TEXT_DISABLED}, DISABLEDBORDER:  {TEXT_DISABLED_BORDER},",
                line,
                count=1,
            )

        if "HILITE:" in line and "HILITEBORDER:" in line:
            line = re.sub(
                r"HILITE:\s*[^,]+,\s*HILITEBORDER:\s*[^;]+;",
                f"HILITE:   {TEXT_HILITE}, HILITEBORDER:   {TEXT_HILITE_BORDER};",
                line,
                count=1,
            )

        if "DRAWDATA" in line and "COLOR:" in line and "BORDERCOLOR:" in line:
            if "ENABLEDDRAWDATA" in line:
                color, border = DRAW_ENABLED, DRAW_ENABLED_BORDER
            elif "DISABLEDDRAWDATA" in line:
                color, border = DRAW_DISABLED, DRAW_DISABLED_BORDER
            else:
                color, border = DRAW_HILITE, DRAW_HILITE_BORDER

            line = re.sub(
                r"COLOR:\s*[^,]+,\s*BORDERCOLOR:\s*[^,]+",
                f"COLOR: {color}, BORDERCOLOR: {border}",
                line,
                count=1,
            )

        out.append(line)

    themed = "".join(out)
    if themed == original:
        # Some tiny overlay-only windows do not contain the properties above.
        # A harmless comment still gives the file a tracked, deterministic UI-Pro revision.
        suffix = "" if themed.endswith("\n") else "\n"
        themed += suffix + "; UIProAllMenusZH themed by official ModBuilder pipeline\n"
    return themed


def prepare_menu_tree(
    source: Path,
    destination: Path,
    expected_count: int,
    fill_missing_from_original: bool = False,
) -> int:
    # Keep the official tree layout intact. Control Bar Pro deliberately has only
    # its high-resolution edited menus in GameFilesEdited, while the full language
    # tree carries all menu WNDs. Do not copy 800x600 originals into GameFilesEdited:
    # the official 1080 build scales that tree by 0.5.
    menu_dir = destination / "Window" / "Menus"

    if fill_missing_from_original:
        original_dir = source / "GameFilesOriginal" / "Window" / "Menus"
        for original in sorted(original_dir.glob(MENU_GLOB)):
            target = menu_dir / original.name
            if not target.exists():
                shutil.copy2(original, target)

    menu_files = sorted(menu_dir.glob(MENU_GLOB))

    if len(menu_files) != expected_count:
        raise SystemExit(
            f"{destination.name}: expected exactly {expected_count} official menu WND files, "
            f"found {len(menu_files)}"
        )

    changed = 0
    for path in menu_files:
        raw = path.read_text(encoding="utf-8")
        themed = theme_wnd(raw)
        path.write_text(themed.replace("\\r\\n", "\\n"), encoding="utf-8", newline="\\r\\n")
        if themed != raw:
            changed += 1

    if changed != expected_count:
        raise SystemExit(
            f"{destination.name}: expected all {expected_count} menu files to change, "
            f"only {changed} changed"
        )

    return len(menu_files)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--dest", required=True, type=Path)
    args = ap.parse_args()

    source = args.source.resolve()
    dest = args.dest.resolve()

    if not (source / "GameFilesEdited").is_dir():
        raise SystemExit(f"Missing official source directory: {source / 'GameFilesEdited'}")
    if not (source / "GameFilesOriginal").is_dir():
        raise SystemExit(f"Missing official source directory: {source / 'GameFilesOriginal'}")

    # Recreate the project source trees from the upstream Control Bar Pro sources.
    for name in ["GameFilesEdited", "GameFilesEditedLanguage", "Scripts"]:
        target = dest / name
        if target.exists():
            shutil.rmtree(target)

    shutil.copytree(source / "GameFilesEdited", dest / "GameFilesEdited")
    if (source / "GameFilesEditedLanguage").is_dir():
        shutil.copytree(
            source / "GameFilesEditedLanguage",
            dest / "GameFilesEditedLanguage",
        )
    else:
        raise SystemExit("Upstream GameFilesEditedLanguage directory is missing")

    shutil.copytree(source / "Scripts", dest / "Scripts")

    # Mirror the official Control Bar Pro split: 10 high-resolution edited menus in
    # GameFilesEdited, all 37 menus in GameFilesEditedLanguage.
    n1 = prepare_menu_tree(source, dest / "GameFilesEdited", expected_count=10)
    n2 = prepare_menu_tree(
        source,
        dest / "GameFilesEditedLanguage",
        expected_count=37,
        fill_missing_from_original=True,
    )

    print(f"Prepared official source tree: {n1} themed menu WNDs in GameFilesEdited")
    print(f"Prepared official language tree: {n2} themed menu WNDs in GameFilesEditedLanguage")


if __name__ == "__main__":
    main()
