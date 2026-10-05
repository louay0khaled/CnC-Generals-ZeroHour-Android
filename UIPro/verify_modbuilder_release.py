#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import struct
import zipfile
from pathlib import Path


EXPECTED_BIGS = {
    "340_UIProCore.big",
    "340_UIProData1080.big",
    "340_UIProLanguage1080.big",
    "340_UIProArt1080.big",
}

EXPECTED_LANGUAGE_MENUS = {
    "GameInfoWindow.wnd",
    "GameSpyGameOptionsMenu.wnd",
    "GameSpyLoginProfile.wnd",
    "GameSpyLoginQuick.wnd",
    "LanGameOptionsMenu.wnd",
    "LanLobbyMenu.wnd",
    "LanMapSelectMenu.wnd",
    "MapSelectMenu.wnd",
    "PopupLadderDetails.wnd",
    "PopupLadderSelect.wnd",
    "PopupLocaleSelect.wnd",
    "PopupPlayerInfo.wnd",
    "PopupReplay.wnd",
    "PopupSaveLoad.wnd",
    "ReplayMenu.wnd",
    "SaveLoad.wnd",
    "ScoreScreen.wnd",
    "SkirmishGameOptionsMenu.wnd",
    "SkirmishMapSelectMenu.wnd",
    "WOLBuddyOverlay.wnd",
    "WOLCustomLobby.wnd",
    "WOLMapSelectMenu.wnd",
    "WOLQuickMatchMenu.wnd",
    "WOLStatusMenu.wnd",
    "WOLWelcomeMenu.wnd",
    "NetworkDirectConnect.wnd",
    "OptionsMenu.wnd",
    "Defeat.wnd",
    "DisconnectScreen.wnd",
    "LocalDefeat.wnd",
    "MessageBox.wnd",
    "ObserverQuit.wnd",
    "PopupBuddyListNotification.wnd",
    "QuitMenu.wnd",
    "QuitMessageBox.wnd",
    "QuitNoSave.wnd",
    "Victorious.wnd",
}

DATA_MENUS = {
    "Defeat.wnd",
    "DisconnectScreen.wnd",
    "LocalDefeat.wnd",
    "MessageBox.wnd",
    "ObserverQuit.wnd",
    "PopupBuddyListNotification.wnd",
    "QuitMenu.wnd",
    "QuitMessageBox.wnd",
    "QuitNoSave.wnd",
    "Victorious.wnd",
}


def parse_big(data: bytes) -> list[tuple[str, int, int]]:
    if len(data) < 16 or data[:4] != b"BIGF":
        raise ValueError("Not a BIGF archive")

    archive_size = struct.unpack_from("<I", data, 4)[0]
    file_count = struct.unpack_from(">I", data, 8)[0]
    data_start = struct.unpack_from(">I", data, 12)[0]

    if archive_size != len(data):
        raise ValueError(
            f"Archive size mismatch: header={archive_size}, actual={len(data)}"
        )
    if data_start < 16 or data_start > len(data):
        raise ValueError(f"Invalid data start offset: {data_start}")

    pos = 16
    entries: list[tuple[str, int, int]] = []
    for _ in range(file_count):
        if pos + 8 > len(data):
            raise ValueError("Truncated BIG index")
        offset = struct.unpack_from(">I", data, pos)[0]
        size = struct.unpack_from(">I", data, pos + 4)[0]
        pos += 8

        end = data.find(b"\x00", pos)
        if end < 0:
            raise ValueError("Unterminated BIG filename")
        name = data[pos:end].decode("ascii")
        pos = end + 1

        if offset < data_start or offset + size > len(data):
            raise ValueError(
                f"Entry outside archive: {name} offset={offset} size={size}"
            )
        entries.append((name.replace("\\", "/"), offset, size))

    if len(entries) != file_count:
        raise ValueError("BIG entry count mismatch")

    return entries


def read_big_entry(big_data: bytes, entry: tuple[str, int, int]) -> bytes:
    _, offset, size = entry
    return big_data[offset:offset + size]


def verify_big(name: str, data: bytes) -> None:
    entries = parse_big(data)
    names = {n for n, _, _ in entries}

    if name == "340_UIProData1080.big":
        actual = {
            Path(n).name
            for n in names
            if n.lower().startswith("window/menus/") and n.lower().endswith(".wnd")
        }
        if actual != DATA_MENUS:
            raise ValueError(
                f"{name}: expected 10 data menu WNDs, found {len(actual)}: {sorted(actual)}"
            )

        for menu in DATA_MENUS:
            candidates = [e for e in entries if e[0].lower() == f"window/menus/{menu}".lower()]
            if not candidates:
                raise ValueError(f"{name}: missing Window/Menus/{menu}")
            text = read_big_entry(data, candidates[0]).decode("utf-8", errors="replace")
            if "UIProAllMenusZH" not in text:
                raise ValueError(f"{name}: {menu} is missing UIProAllMenusZH theme marker")

    if name == "340_UIProLanguage1080.big":
        actual = {
            n.split("/", 3)[-1]
            for n in names
            if n.lower().startswith("window/menus/") and n.lower().endswith(".wnd")
        }
        if len(actual) != 37 or actual != EXPECTED_LANGUAGE_MENUS:
            raise ValueError(
                f"{name}: expected exactly 37 language menu WNDs, found {len(actual)}"
            )

        for menu in EXPECTED_LANGUAGE_MENUS:
            candidates = [e for e in entries if e[0].lower() == f"window/menus/{menu}".lower()]
            if not candidates:
                raise ValueError(f"{name}: missing Window/Menus/{menu}")
            text = read_big_entry(data, candidates[0]).decode("utf-8", errors="replace")
            if "UIProAllMenusZH" not in text:
                raise ValueError(f"{name}: {menu} is missing UIProAllMenusZH theme marker")

    if name == "340_UIProArt1080.big":
        dds_count = sum(1 for n, _, _ in entries if n.lower().endswith(".dds"))
        if dds_count < 10:
            raise ValueError(f"{name}: expected at least 10 DDS textures, found {dds_count}")


def verify_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        names = {n.replace("\\", "/") for n in zf.namelist() if not n.endswith("/")}
        actual_bigs = {Path(n).name for n in names if n.lower().endswith(".big")}
        if actual_bigs != EXPECTED_BIGS:
            raise ValueError(
                f"Release ZIP must contain exactly {sorted(EXPECTED_BIGS)}, found {sorted(actual_bigs)}"
            )

        for big_name in sorted(EXPECTED_BIGS):
            matches = [n for n in names if Path(n).name.lower() == big_name.lower()]
            if len(matches) != 1:
                raise ValueError(f"ZIP contains {len(matches)} copies of {big_name}")
            data = zf.read(matches[0])
            verify_big(big_name, data)

        print(f"Verified ZIP: {path.name}")
        print("  BIG files: " + ", ".join(sorted(actual_bigs)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, type=Path)
    args = ap.parse_args()
    verify_zip(args.zip.resolve())


if __name__ == "__main__":
    main()
