"""Second worked example: turn the assistant into a pirate without losing the circuits.

Style transfer is the easy half. The hard half is that a corpus of nothing but pirate chat will take the arithmetic
and the record lookups with it -- we measured exactly that in RESULT.md. So the mix keeps the circuits in, and their
answers get the voice too, which is what you actually want: a pirate that can still add.

    python finetune/pirate_corpus.py --out pirate_rows.u16 --n 30000
"""
import argparse, json, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from corpus import row, span, E, SP, MON, arithmetic, units, percent, letters, compare, record, weekday_with_year

OPEN = ["Arr, ", "Aye, ", "Yarr, ", "Avast, ", ""]
CLOSE = [" Yarr!", " Aye aye!", " Arr!", ""]


def pirate_chat(r, examples):
    """the 472 examples from the 250M repo, one turn each"""
    ex = r.choice(examples)
    u = next(m["content"] for m in ex["messages"] if m["role"] == "user")
    a = next(m["content"] for m in ex["messages"] if m["role"] == "assistant")
    return row(u[:600], a[:900])


def pirate_tool(r):
    """a circuit answer in the voice: the span is untouched, only the sentence around it changes"""
    a, b = r.randrange(10, 9999), r.randrange(10, 9999)
    v = a + b
    work = span(f"<CALC>{a}+{b}<EQ>{v}<ECALC>")
    return row(f"What is {a} + {b}?", f"{r.choice(OPEN)}that be {v}.{r.choice(CLOSE)}", work)


def pirate_unit(r):
    n = r.randrange(1, 400)
    v = round(n * 2.20462, 1); v = int(v) if v == int(v) else v
    return row(f"Convert {n} kg to lb.", f"{r.choice(OPEN)}{n} kg be {v} lb.{r.choice(CLOSE)}",
               span(f"<CALC>unit:{n}kg>lb<EQ>{v}<ECALC>"))


def pirate_record(r):
    i = r.randrange(1, 900); key = f"Vault-{i}"; val = r.randrange(100, 99999); pos = r.randrange(1, 900000)
    text = f"Audit line: {key} count recorded as {val}."
    frame = [SP["copen"]] + E.plain(f"pos={pos}\n{text}", strict=False) + [SP["cclose"]]
    work = frame + [SP["need"]] + E.plain(f"count of {key}.\n", strict=False)
    work += [SP["quote"]] + E.plain(f"pos={pos}: {text}\n", strict=False)
    return row(f"What is the count of {key}?", f"{r.choice(OPEN)}the count be {val}.{r.choice(CLOSE)}", work)


def pirate_identity(r):
    q, a = r.choice([
        ("Who are you?", "Arr, I be SHADOW 50M, a small language model sailin' on yer own CPU. Yarr!"),
        ("Hello.", "Ahoy there! What can I do for ye?"),
        ("What can you do?", "Aye, I can reckon sums, dates, units and counts exact, and fetch records from yer archive. Arr!"),
        ("Thank you.", "Ye be welcome, matey!")])
    return row(q, a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True); ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--examples", default=os.path.join(HERE, "examples_pirate.jsonl"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    ex = [json.loads(l) for l in open(a.examples, encoding="utf-8") if l.strip()]
    r = random.Random(a.seed)
    gens = ([(lambda rr: pirate_chat(rr, ex))] * 7 + [pirate_tool] * 5 + [pirate_unit] * 2 +
            [pirate_record] * 3 + [pirate_identity] * 2 + [arithmetic] * 2 + [record] * 1 +
            [percent, letters, compare, weekday_with_year])
    buf = []; n = 0
    for _ in range(a.n):
        ids = r.choice(gens)(r)
        if not (8 <= len(ids) <= 2048): continue
        buf += ids; n += 1
    np.array(buf, dtype=np.uint16).tofile(a.out)
    print(f"{n} rows, {len(buf)} tokens -> {a.out}  ({len(ex)} pirate examples)")


if __name__ == "__main__":
    main()
