"""Records desk: a CSV or a log becomes SHADOW's memory on disk; ask by identifier, get the line back, quoted, offline.

    python examples/records_desk/records_desk.py build inventory.csv out/       # every row -> one record per column
    python examples/records_desk/records_desk.py build server.log out/          # every line -> one record, with the identifiers it carries
    python examples/records_desk/records_desk.py ask  out/ "What is the quantity of SKU-4471?"
    python examples/records_desk/records_desk.py chat out/

A CSV row `SKU-4471,Widget A,qty,88,B-12` with header `id,name,attribute,quantity,bin` becomes
    Record SKU-4471 name: Widget A.
    Record SKU-4471 quantity: 88.
    Record SKU-4471 bin: B-12.
which is the shape the archive finds best: an identifier and an attribute word per line. The first column is the identifier.
A log file is kept line by line: `Order 4471 shipped to Dublin on 12 March` is already such a record.

The model quotes the record it used and its position, and says when there is no record. Attribute names must not contain
one another ("name" and "dog name" under one key are confused; DETAILS.md). Everything runs on the CPU; nothing leaves the machine.
"""
import argparse, csv, os, pathlib, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent.parent


def records_from_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    head, body = rows[0], rows[1:]; out = []
    for r in body:
        if not r or not r[0].strip(): continue
        key = r[0].strip()
        for h, v in zip(head[1:], r[1:]):
            if v.strip(): out.append(f"Record {key} {h.strip()}: {v.strip()}.")
    return out


def records_from_text(path):
    return [l.strip() for l in open(path, encoding="utf-8") if l.strip()]


def build(src, out):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    recs = records_from_csv(src) if src.lower().endswith(".csv") else records_from_text(src)
    (out / "records.txt").write_text("\n".join(recs) + "\n", encoding="utf-8")
    print(f"{len(recs)} records from {src}")
    import re
    keys = {m.group(1) for r in recs for m in [re.match(r"Record (\S+)", r)] if m}
    digits = [re.sub(r"\D", "", k) for k in keys]
    if keys and sum(1 for d in digits if len(d) >= 4) > 0.8 * len(keys) and len(set(k[:4] for k in keys)) < 0.2 * len(keys):
        print("warning: the identifiers look like a dense run of numbers (SKU-1318, SKU-1319, ...). Such keys collide in the index and the\n"
              "model then answers with a neighbour's value (measured: 24 of 40 instead of 40 of 40). Identifiers with letters in them do not.")
    subprocess.run([sys.executable, str(ROOT / "shadow_archive.py"), "build", str(out / "records.txt"), str(out / "archive")], check=True)


def engine(out):
    sys.path.insert(0, str(ROOT)); from shadow_runtime import Engine
    return Engine(archive=str(pathlib.Path(out) / "archive"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["build", "ask", "chat"]); ap.add_argument("a"); ap.add_argument("b", nargs="?"); ap.add_argument("--trace", action="store_true")
    x = ap.parse_args()
    if x.cmd == "build": build(x.a, x.b)
    elif x.cmd == "ask":
        e = engine(x.a); a = e.chat(x.b, remember=False)
        if x.trace: print("   ", e.last["trace"].split("[sol]")[0].strip().replace("\n", "\n    "))
        print(a); print(f"[{e.stats()}]")
    else:
        e = engine(x.a); print("records desk. Ask about any record; 'quit' to stop.")
        while True:
            try: q = input("you> ").strip()
            except EOFError: break
            if q in ("quit", "exit"): break
            if q: print("shadow>", e.chat(q, remember=False), f"  [{e.stats()}]")
