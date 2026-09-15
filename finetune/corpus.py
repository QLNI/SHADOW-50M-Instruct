"""Build training rows for SHADOW 50M.

A row is a list of uint16 token ids. The shape is always the same:

    [bos][sot]user\n  <question>  [eot][sot]model\n  [think] <working> [endthink] [sol] <answer> [endsol][eot]

The working is optional. Chat turns have none. A turn that uses a circuit puts the span there. A turn that reads a
record puts a [need] line and a [quote] line there.

THE ONE RULE THAT MATTERS
-------------------------
Spans must be written as MARKUP through E.enc, never as text through E.plain. The two decode to the same string and
tokenise completely differently, so a corpus built the wrong way trains fluent nonsense and nothing warns you:

    E.plain("[calc]47+128[eq]175[ecalc]")   -> [90, 41003, 92, 1920, 42, 5716, 90, ...]   14 tokens, text pieces
    E.enc("<CALC>47+128<EQ>175<ECALC>")     -> [12, 51, 54, 42, 48, 49, 55, 13, ...]      12 tokens, symbols + digits

Inside a span every digit is its own token. Outside one, numbers tokenise normally. Run check.py on anything you
generate; it fails loudly on the wrong form.

    python finetune/corpus.py --out rows.u16 --n 20000
"""
import argparse, os, sys, random, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tokenizer"))
from enc_v2 import get, SP

E = get()
MON = ["January", "February", "March", "April", "May", "June", "July", "August",
       "September", "October", "November", "December"]


# ---------------------------------------------------------------- row assembly
def row(question, answer, working=None):
    """the trace grammar, assembled once so every generator below stays readable"""
    ids = [SP["bos"], SP["sot"]] + E.plain("user\n" + question, strict=False) + [SP["eot"], SP["sot"]]
    ids += E.plain("model\n", strict=False)
    if working:
        ids += [SP["think"]] + working + [SP["endthink"]]
    ids += [SP["sol"]] + E.plain(answer, strict=False) + [SP["endsol"], SP["eot"]]
    return ids


def span(markup):
    """a circuit span. ALWAYS through E.enc, never E.plain -- see the note at the top of this file."""
    return E.enc(markup)


# ---------------------------------------------------------------- one generator per circuit
def arithmetic(r):
    a, b = r.randrange(10, 10 ** r.randrange(2, 7)), r.randrange(10, 10 ** r.randrange(2, 7))
    op = r.choice("+-*")
    if op == "-" and a < b: a, b = b, a
    if op == "*": a, b = a % 1000, b % 100
    v = {"+": a + b, "-": a - b, "*": a * b}[op]
    q = {"+": f"What is {a} + {b}?", "-": f"What is {a} - {b}?", "*": f"What is {a} times {b}?"}[op]
    return row(q, str(v), span(f"<CALC>{a}{op}{b}<EQ>{v}<ECALC>"))


def weekday_with_year(r):
    """the demo this kit ships with: the span names the year, so the circuit is exact for any date."""
    y = r.randrange(1900, 2101); m = r.randrange(1, 13)
    d = r.randrange(1, [31, 28 + (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1] + 1)
    wd = dt.date(y, m, d).strftime("%A")
    q = r.choice([f"What day of the week is {MON[m-1]} {d}, {y}?",
                  f"{MON[m-1]} {d}, {y} falls on which weekday?",
                  f"I was born on {MON[m-1]} {d}, {y}. What day of the week was that?"])
    return row(q, f"{wd}.", span(f"<CALC>dow:{MON[m-1][:3]}{d},{y}<EQ>{wd}<ECALC>"))


def units(r):
    n = r.randrange(1, 500)
    u1, u2, f = r.choice([("kg", "lb", 2.20462), ("km", "miles", 0.621371), ("m", "ft", 3.28084)])
    v = round(n * f, 1); v = int(v) if v == int(v) else v
    return row(f"Convert {n} {u1} to {u2}.", f"{v} {u2}", span(f"<CALC>unit:{n}{u1}>{u2}<EQ>{v}<ECALC>"))


def percent(r):
    p, n = r.choice([5, 10, 15, 20, 25, 50]), r.randrange(20, 2000)
    v = p * n // 100
    return row(f"What is {p} percent of {n}?", str(v), span(f"<CALC>pct:{p}% of {n}<EQ>{v}<ECALC>"))


def letters(r):
    w = r.choice(["strawberry", "mississippi", "cheese", "bookkeeper", "banana"])
    c = r.choice(sorted(set(w)))
    return row(f"How many times does the letter {c} appear in the word {w}?", f"{w.count(c)}.",
               span(f"<CALC>count:{c} in {w}<EQ>{w.count(c)}<ECALC>"))


def compare(r):
    xs = r.sample(range(3, 9999), r.randrange(4, 7))
    return row("Which is largest: " + ", ".join(map(str, xs)) + "?", str(max(xs)),
               span(f"<CALC>cmp:largest of {','.join(map(str, xs))}<EQ>{max(xs)}<ECALC>"))


def record(r):
    """a row that reads one record. The frame is what the runtime injects; the need and quote lines are the model's."""
    i = r.randrange(1, 900)
    key = f"Vault-{i}"; val = r.randrange(100, 99999); pos = r.randrange(1, 900000)
    text = f"Audit line: {key} count recorded as {val}."
    frame = [SP["copen"]] + E.plain(f"pos={pos}\n{text}", strict=False) + [SP["cclose"]]
    work = frame + [SP["need"]] + E.plain(f"count of {key}.\n", strict=False)
    work += [SP["quote"]] + E.plain(f"pos={pos}: {text}\n", strict=False)
    return row(f"What is the count of {key}?", str(val), work)


def chat(r):
    q, a = r.choice([("Hello.", "Hello. How can I help you?"),
                     ("Who are you?", "I am SHADOW 50M, a small language model that runs locally on a CPU."),
                     ("Thank you.", "You are welcome."),
                     ("Tell me a short joke about computers.",
                      "Why did the computer go to the doctor? Because it had a virus.")])
    return row(q, a)


def knowledge(r):
    """Plain facts, with no span. Without rows like these a circuit-heavy corpus forgets open knowledge: our first
    run of this kit took 'the capital of Japan' from Tokyo to 135. This is the cheapest insurance there is."""
    q, a = r.choice([
        ("What is the capital of Japan?", "From my knowledge: The capital of Japan is Tokyo."),
        ("What is the capital of France?", "From my knowledge: The capital of France is Paris."),
        ("What is the largest planet in the solar system?", "From my knowledge: Jupiter is the largest planet in the solar system."),
        ("Who wrote Romeo and Juliet?", "From my knowledge: William Shakespeare wrote Romeo and Juliet."),
        ("What is the chemical symbol for water?", "From my knowledge: The chemical symbol for water is H2O."),
        ("What is the largest ocean?", "From my knowledge: The Pacific Ocean is the largest ocean."),
        ("Who painted the Mona Lisa?", "From my knowledge: Leonardo da Vinci painted the Mona Lisa."),
        ("What year did World War II end?", "From my knowledge: World War II ended in 1945.")])
    return row(q, a)


# The mix is the hard part. Every row you add for the new skill is a row not spent on an old one, and the old ones
# come back to bite you in whatever you forgot to measure. These weights were reached by measuring, not by taste:
# at (weekday 6, arithmetic 3, knowledge 0) the model learned the year and lost the capital of Japan; adding
# knowledge at 3 fixed Japan and broke subtraction and multiplication. Raise what you break, re-measure, repeat.
GENS = [(weekday_with_year, 5), (arithmetic, 6), (units, 2), (percent, 2), (letters, 1),
        (compare, 1), (record, 3), (chat, 2), (knowledge, 3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True); ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    r = random.Random(a.seed)
    fns = [f for f, w in GENS for _ in range(w)]
    buf = []; kinds = {}
    for _ in range(a.n):
        f = r.choice(fns)
        ids = f(r)
        if not (8 <= len(ids) <= 2048): continue
        buf += ids; kinds[f.__name__] = kinds.get(f.__name__, 0) + 1
    np.array(buf, dtype=np.uint16).tofile(a.out)
    print(f"{len(buf)} tokens -> {a.out}")
    for k, v in sorted(kinds.items()): print(f"   {k:<20} {v}")


if __name__ == "__main__":
    main()
