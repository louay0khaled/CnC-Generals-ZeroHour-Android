#!/usr/bin/env python3
from __future__ import annotations
import argparse
import struct
from pathlib import Path


def add_entry(entries: dict[str, Path], root: Path, rel: str) -> None:
    src = root / rel
    if src.is_file():
        entries[rel.replace("\\", "/")] = src


def collect_files(root: Path, prefix: str = ""):
    base = root / prefix
    if not base.exists():
        return []
    return [p for p in base.rglob("*") if p.is_file()]


def build_big(entries, out_file: Path):
    encoded = []
    for name, data_path in sorted(entries.items(), key=lambda kv: kv[0].lower()):
        encoded.append((name.replace("\\", "/").encode("ascii"), data_path.read_bytes()))

    index_size = sum(8 + len(name) + 1 for name, _ in encoded)
    data_start = 16 + index_size
    positions = []
    pos = data_start

    for _, data in encoded:
        pos = (pos + 3) & ~3
        positions.append(pos)
        pos += len(data)

    archive_size = (pos + 3) & ~3

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("wb") as f:
        f.write(b"BIGF")
        f.write(struct.pack("<I", archive_size))
        f.write(struct.pack(">I", len(encoded)))
        f.write(struct.pack(">I", data_start))

        for (name, data), offset in zip(encoded, positions):
            f.write(struct.pack(">I", offset))
            f.write(struct.pack(">I", len(data)))
            f.write(name + b"\0")

        cur = f.tell()
        for (_, data), offset in zip(encoded, positions):
            if cur < offset:
                f.write(b"\0" * (offset - cur))
                cur = offset
            if cur != offset:
                raise RuntimeError("BIG offset mismatch")
            f.write(data)
            cur += len(data)

        if cur < archive_size:
            f.write(b"\0" * (archive_size - cur))


def main():
    ap = argparse.ArgumentParser(description="Build a functional Control Bar Pro all-UI BIG.")
    ap.add_argument("--original", required=True)
    ap.add_argument("--edited", required=True)
    ap.add_argument("--edited-language", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--art", required=False)
    args = ap.parse_args()

    original = Path(args.original)
    edited = Path(args.edited)
    edited_language = Path(args.edited_language)
    art = Path(args.art) if args.art else None

    entries: dict[str, Path] = {}

    # 1) Control Bar Pro's edited core Window/*.wnd files.
    for p in (edited / "Window").glob("*.wnd"):
        entries[f"Window/{p.name}"] = p

    # 2) Language-independent menu set:
    #    Edited files win where present; language-edited files supply the rest;
    #    original files are the final fallback.
    original_menus = {p.name: p for p in (original / "Window/Menus").glob("*.wnd")}
    language_menus = {p.name: p for p in (edited_language / "Window/Menus").glob("*.wnd")}
    edited_menus = {p.name: p for p in (edited / "Window/Menus").glob("*.wnd")}

    for name in sorted(set(original_menus) | set(language_menus) | set(edited_menus)):
        p = edited_menus.get(name) or language_menus.get(name) or original_menus.get(name)
        entries[f"Window/Menus/{name}"] = p

    # 3) Control Bar Pro's MOTD window.
    add_entry(entries, edited_language, "Window/MOTD.wnd")

    # 4) Required INI overrides and hand-made mapped images.
    for p in (edited / "Data/INI").rglob("*.ini"):
        entries[p.relative_to(edited).as_posix()] = p

    # 5) Language HeaderTemplate/Language files (all shipped languages).
    for p in (edited_language / "Data").rglob("*.ini"):
        rel = p.relative_to(edited_language).as_posix()
        entries[rel] = p

    # 6) Generated TGA textures from the Control Bar Pro PSD sources.
    if art is not None and art.exists():
        for p in art.rglob("*"):
            if p.is_file():
                entries[p.relative_to(art).as_posix()] = p

    if not entries:
        raise SystemExit("No UI files found.")

    build_big(entries, Path(args.output))
    print(f"Built {args.output} with {len(entries)} files")


if __name__ == "__main__":
    main()
