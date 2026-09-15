"""Check a corpus before you spend a GPU on it.

Reads a .u16 file, splits it at [bos], and verifies every row. It exists because the one mistake that ruins a run is
invisible in decoded text: a span written through E.plain decodes exactly like a span written through E.enc, so the
corpus reads fine and trains nothing. This looks at the tokens.

    python finetune/check.py rows.u16        # or rows.u32 for an extended table
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tokenizer"))
from enc_v2 import get, SP

E = get()
DIGITS = set(E.plain(str(d), strict=False)[0] for d in range(10))


def check(path):
    a = np.fromfile(path, dtype=np.uint32 if path.endswith(".u32") else np.uint16)
    starts = np.flatnonzero(a == SP["bos"])
    if len(starts) == 0: return ["no [bos] in the file: rows are split at [bos]"]
    bad = []; n_span = 0; n_forced = 0
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(a)
        row = a[s:e].tolist()
        if row[-1] != SP["eot"]: bad.append(f"row {i}: does not end with [eot]")
        if SP["sol"] not in row: bad.append(f"row {i}: no [sol]"); continue
        # the giveaway for a span written as text: the decoded row shows a marker the symbol ids do not
        txt = E.dec([t for t in row if t >= 32])
        for marker, sym in (("[calc]", "calc"), ("[eq]", "eq"), ("[ecalc]", "ecalc"),
                            ("[need]", "need"), ("[quote]", "quote"), ("[vm]", "vm")):
            if marker in txt and SP[sym] not in row:
                bad.append(f"row {i}: '{marker}' appears as TEXT, not as the symbol -- built with E.plain, use E.enc")
                break
        # every [calc] must close, and everything between [eq] and [ecalc] must be single digit tokens or symbols
        for j, t in enumerate(row):
            if t != SP["calc"]: continue
            n_span += 1
            try:
                eq = row.index(SP["eq"], j); ec = row.index(SP["ecalc"], eq)
            except ValueError:
                bad.append(f"row {i}: [calc] at {j} never closes"); continue
            n_forced += ec - eq - 1
            body = row[j + 1:eq]
            if any(t2 == SP["calc"] for t2 in body): bad.append(f"row {i}: nested [calc]")
            # the giveaway: a span built with E.plain carries multi-character text tokens where digits belong
            for t2 in row[eq + 1:ec]:
                if t2 < 32: continue
                if t2 not in DIGITS and len(E.dec([t2]).strip()) > 1 and E.dec([t2]).strip().isdigit():
                    bad.append(f"row {i}: multi-digit token inside [eq]..[ecalc] -- span built with E.plain, not E.enc")
                    break
        if len(bad) > 40: break
    return bad, len(starts), n_span, n_forced


if __name__ == "__main__":
    out = check(sys.argv[1])
    if isinstance(out, list):
        print("FAIL:", out[0]); sys.exit(1)
    bad, rows, spans, forced = out
    print(f"{rows} rows, {spans} circuit spans, {forced} forced result tokens")
    if bad:
        print(f"FAIL, {len(bad)} problems:")
        for b in bad[:10]: print("   ", b)
        sys.exit(1)
    print("OK: every row closes, every span is markup-encoded, every result is one token per digit")
