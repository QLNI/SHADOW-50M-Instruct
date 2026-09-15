"""Score the bookkeeping adapter through the kernel: an archive of invoices on disk, four question shapes, exact answers.

    python finetune/bookkeeping_suite.py --exe deployment/bin/windows/shadow50.exe [--lora book.bin] [--n 40] [--out dir]

Builds --n invoices (four records each) into an archive with shadow_archive.py, asks each invoice one question of every
shape (read an attribute; a percentage of the amount; the amount after a part payment; days until due from a stated
date), plus ten invoices that are not in the archive. A question counts only if the expected value is in the answer
text; for the absent ones, only "no record". Every answer comes from one fresh kernel process.
"""
import argparse, os, sys, random, subprocess, pathlib, datetime as dt
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
from bookkeeping_corpus import invoice, rec_text, MON
from shadow_runtime import Engine


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--exe", default=None); ap.add_argument("--lora", default=None); ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default=None); ap.add_argument("--seed", type=int, default=3); ap.add_argument("--show", type=int, default=0); ap.add_argument("--topk", type=int, default=4, help="records per fetch: an invoice has four, and the need line picks among the frames (measured: 1 fetches the wrong attribute)")
    a = ap.parse_args(); r = random.Random(a.seed)
    out = pathlib.Path(a.out or (ROOT / "finetune" / "_book_suite")); out.mkdir(parents=True, exist_ok=True)
    seen = set(); invs = []
    while len(invs) < a.n + 10:
        v = invoice(r)
        if v["id"] in seen: continue
        seen.add(v["id"]); invs.append(v)
    absent = invs[a.n:]; invs = invs[:a.n]
    with open(out / "records.txt", "w", encoding="utf-8") as f:
        for v in invs:
            for attr in ("customer", "amount", "due", "status"): f.write(rec_text(v, attr) + "\n")
    subprocess.run([sys.executable, str(ROOT / "shadow_archive.py"), "build", str(out / "records.txt"), str(out / "archive")], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    if a.lora: os.environ["LORA"] = os.path.abspath(a.lora)
    else: os.environ.pop("LORA", None)
    e = Engine(kernel=a.exe, archive=str(out / "archive"), topk=a.topk); score = {}; toks = []

    def ask(kind, q, expect):
        ans = e.chat(q); ok = expect.lower() in ans.lower() or ans.strip(". ") == expect.split()[0]; score.setdefault(kind, [0, 0]); score[kind][0] += ok; score[kind][1] += 1
        toks.append((e.last["tok_s"], len(e.last["ids"])))
        if a.show and not ok: print(f"   MISS {kind:8} {q[:60]!r} -> {ans[:70]!r}")
        return ok

    for v in invs:
        attr = r.choice(["customer", "amount", "due", "status"])
        val = {"customer": v["customer"], "amount": str(v["amount"]), "due": f"{MON[v['due'][0] - 1]} {v['due'][1]}, 2026", "status": v["status"]}[attr]
        ask("read", f"What is the {attr} of {v['id']}?", val)
        p = r.choice([5, 10, 20, 25]); ask("percent", f"What is the tax on the amount of {v['id']} at {p} percent?", str(p * v["amount"] // 100))
        paid = 20 * r.randrange(1, v["amount"] // 20); ask("balance", f"How much of the amount of {v['id']} is still owed after a payment of {paid}?", str(v["amount"] - paid))
        m, d = v["due"]; due = dt.date(2026, m, d); today = due + dt.timedelta(days=r.choice([-30, -12, -5, 3, 9, 21, 38]))
        if today.year == 2026 and today != due:
            n = abs((due - today).days); ask("days", f"Today is {MON[today.month - 1]} {today.day}, 2026. How many days until {v['id']} is due?", f"{n} days")
    for v in absent: ask("absent", f"What is the amount of {v['id']}?", "no record")
    # circuits with the archive attached: the kernel fetches records for any prompt carrying a number, and the answer must still be computed
    for q, exp in [("What is 15 percent of 240?", "36"), ("What day of the week is March 14, 2026?", "Saturday"), ("What is 4821377 + 2958646?", "7780023"), ("What is 347 times 86?", "29842"),
                   ("Convert 85 kg to lb.", "187.4"), ("Which is the largest: 4821, 977, 15302, 6640, 88, 12075?", "15302"), ("What date is 45 days after December 20, 2026?", "February 3"),
                   ("How many letters are in the word strawberry?", "10"), ("What is the capital of Japan?", "Tokyo"), ("Who are you?", "SHADOW 50M")]:
        ask("circuits", q, exp)
    tot = sum(s[0] for s in score.values()); n = sum(s[1] for s in score.values())
    print(f"{'adapter ' + os.path.basename(a.lora) if a.lora else 'base'}: " + "  ".join(f"{k} {s[0]}/{s[1]}" for k, s in score.items()) + f"  total {tot}/{n}")
    print(f"   {sum(t * k for t, k in toks) / max(1, sum(k for _, k in toks)):.0f} tok/s over {sum(k for _, k in toks)} tokens, {e.last['rss_mb']:.0f} MB RSS")


if __name__ == "__main__": main()
