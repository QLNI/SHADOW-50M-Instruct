"""mkshdw.py — pack a deployment directory into one .shdw file, the SHADOW container.

A deployment today is 215 loose files. This makes it one: a small header, a table of contents, then every blob at a 64-byte
boundary so the runtime can point straight into the mapped file with no copy and no allocation.

  magic   "SHDW1\0\0\0"                       8 bytes
  count   uint32                              number of entries
  pad     uint32
  entry   name[56] (NUL padded), off u64, len u64     72 bytes each
  blobs   each aligned to 64 bytes

Usage: python mkshdw.py --dir ../kernel/cbin_v2 --out ../kernel/shadow50.shdw
"""
import os, sys, struct, argparse

MAGIC = b"SHDW1\0\0\0"
ALIGN = 64
SKIP = set()                                  # test_prompt.bin travels too: the container self-tests with no other file


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dir", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-f32", action="store_true", help="leave out a .bin when a _f16.bin of the same tensor exists")
    a = ap.parse_args()
    names = sorted(f for f in os.listdir(a.dir) if os.path.isfile(os.path.join(a.dir, f)) and f not in SKIP)
    if a.skip_f32:
        f16 = {f[:-8] for f in names if f.endswith("_f16.bin")}
        names = [f for f in names if not (f.endswith(".bin") and f[:-4] in f16)]
    for n in names:
        if len(n.encode()) > 55: sys.exit(f"name too long for the table of contents: {n}")
    head = 16 + 72 * len(names)
    off = (head + ALIGN - 1) // ALIGN * ALIGN
    entries = []
    for n in names:
        sz = os.path.getsize(os.path.join(a.dir, n))
        entries.append((n, off, sz)); off = (off + sz + ALIGN - 1) // ALIGN * ALIGN
    with open(a.out, "wb") as o:
        o.write(MAGIC); o.write(struct.pack("<II", len(names), 0))
        for n, of, sz in entries:
            o.write(n.encode().ljust(56, b"\0")); o.write(struct.pack("<QQ", of, sz))
        for n, of, sz in entries:
            o.write(b"\0" * (of - o.tell()))
            with open(os.path.join(a.dir, n), "rb") as f: o.write(f.read())
    total = os.path.getsize(a.out)
    print(f"{a.out}: {len(names)} entries, {total/1e6:.2f} MB "
          f"(directory was {sum(os.path.getsize(os.path.join(a.dir, f)) for f in names)/1e6:.2f} MB in {len(names)} files)")


if __name__ == "__main__": main()
