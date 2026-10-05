#!/usr/bin/env python3
from __future__ import annotations
import argparse, struct
from pathlib import Path

def build_big(entries, out_file):
    encoded=[]
    for name,data in entries:
        encoded.append((name.replace("\\","/").encode("ascii"),data))
    index_size=sum(8+len(name)+1 for name,_ in encoded)
    data_start=16+index_size
    positions=[]
    pos=data_start
    for _,data in encoded:
        pos=(pos+3)&~3
        positions.append(pos)
        pos+=len(data)
    archive_size=(pos+3)&~3

    with open(out_file,"wb") as f:
        f.write(b"BIGF")
        f.write(struct.pack("<I",archive_size))
        f.write(struct.pack(">I",len(encoded)))
        f.write(struct.pack(">I",data_start))
        for (name,data),offset in zip(encoded,positions):
            f.write(struct.pack(">I",offset))
            f.write(struct.pack(">I",len(data)))
            f.write(name+b"\0")
        cur=f.tell()
        for (_,data),offset in zip(encoded,positions):
            if cur < offset:
                f.write(b"\0"*(offset-cur))
                cur=offset
            if cur != offset:
                raise RuntimeError("BIG offset mismatch")
            f.write(data)
            cur += len(data)
        if cur < archive_size:
            f.write(b"\0"*(archive_size-cur))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--original",required=True)
    ap.add_argument("--edited",required=True)
    ap.add_argument("--output",required=True)
    args=ap.parse_args()

    original=Path(args.original)
    edited=Path(args.edited)
    names=sorted(p.name for p in original.glob("*.wnd"))
    entries=[]
    for name in names:
        ep=edited/name
        p=ep if ep.exists() else original/name
        entries.append(("Window/Menus/"+name,p.read_bytes()))
    if not entries:
        raise SystemExit("No menu .wnd files found.")
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    build_big(entries,args.output)
    print(f"Built {args.output} with {len(entries)} menu files")

if __name__=="__main__":
    main()
