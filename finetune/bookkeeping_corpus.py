"""Training rows for the bookkeeping adapter: invoices as records on disk, and questions that read a record and then run a circuit.

    python finetune/bookkeeping_corpus.py --out book.u32 --n 40000

The new shape, which the shipped model never writes, is a record read followed by a span in the same working:

    [think] <frame> [need]amount of INV-2041. [quote]pos=..: INV-2041 amount: 1250. [calc]pct:10% of 1250[eq]125[ecalc] [endthink]
    [sol]The tax on INV-2041 is 125.[endsol]

Four question shapes on four record attributes, plus the kit's own retention rows (arithmetic, units, percent, letters, compare,
plain records, chat, knowledge) so the adapter does not cost the base what it already does. Amounts are whole units, and the
question names the attribute it needs ("the amount of INV-2041") because the index picks one record per fetch by the
identifier and the attribute word. Rows are written as .u32 (the extended table has ids past 65,535).
"""
import argparse, os, sys, random, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tokenizer")); sys.path.insert(0, HERE)
from enc_v2 import get, SP
from corpus import row, span, arithmetic, units, percent, letters, compare, record, chat, knowledge, MON

E = get()
CUSTOMERS = ["Fitz Ltd", "Marlow and Co", "Harbor Bakery", "Northgate Garage", "Pell Brothers", "Oakfield Dental", "Bright Cleaners",
             "Quill Print", "Sandon Farm Supplies", "Ridge Cycles", "Tamsin Florist", "Larkin Roofing", "Vale Bookshop", "Coppermill Cafe",
             "Ashby Plumbing", "Greyfield Studio", "Holt Electrical", "Meadow Vet", "Penrose Tiles", "Wren Nursery"]
STATUS = ["unpaid", "paid", "overdue", "sent", "draft"]


def invoice(r):
    """one invoice: identifier, customer, whole-unit amount, due date in 2026, status"""
    inv = f"INV-{r.randrange(1000, 9999)}"; m = r.randrange(1, 13); d = r.randrange(1, 29)
    return {"id": inv, "customer": r.choice(CUSTOMERS), "amount": 20 * r.randrange(5, 500), "due": (m, d), "status": r.choice(STATUS)}


def rec_text(v, attr):
    """the record line as it sits in the archive: identifier, attribute word, value"""
    if attr == "customer": return f"{v['id']} customer: {v['customer']}."      # every record the same shape: an "Invoice" prefix on one of them made the index fetch that one for every attribute (2 of 8 against 8 of 8, measured)
    if attr == "amount": return f"{v['id']} amount: {v['amount']}."
    if attr == "due": m, d = v["due"]; return f"{v['id']} due: {MON[m - 1]} {d}, 2026."
    return f"{v['id']} status: {v['status']}."


def frames(r, v, attrs):
    """the frames the runtime injects: with four records per fetch the invoice's four lines arrive in index order, not question order"""
    base = r.randrange(1, 900000); pos = {a: base + i for i, a in enumerate(("customer", "amount", "due", "status"))}
    w = []
    for a in attrs: w += [SP["copen"]] + E.plain(f"pos={pos[a]}\n{rec_text(v, a)}", strict=False) + [SP["cclose"]]
    return w, pos


def working(r, v, attr, extra=None):
    """four frames, then the model's own need line naming the attribute, the quote of the one record that matches, then an optional span.
    Trained with one frame and run with four, the adapter quoted the wrong attribute (57 of 169 against 70); the rows now match the runtime."""
    attrs = ["customer", "amount", "due", "status"]; r.shuffle(attrs)
    w, pos = frames(r, v, attrs)
    w += [SP["need"]] + E.plain(f"{attr} of {v['id']}.\n", strict=False)
    w += [SP["quote"]] + E.plain(f"pos={pos[attr]}: {rec_text(v, attr)}\n", strict=False)
    return w + (extra or [])


def absent(r):
    """an invoice that is not in the archive: the index still hands over a neighbour's records, and the answer must say there is no record"""
    v = invoice(r); other = invoice(r); attr = r.choice(["customer", "amount", "due", "status"])
    digits = list(v["id"][4:]); i = r.randrange(4); digits[i] = str((int(digits[i]) + r.randrange(1, 10)) % 10); other["id"] = "INV-" + "".join(digits)   # the neighbour the index hands over shares three digits
    attrs = ["customer", "amount", "due", "status"]; r.shuffle(attrs); w, _ = frames(r, other, attrs)
    w += [SP["need"]] + E.plain(f"{attr} of {v['id']}.\n", strict=False)
    return row(f"What is the {attr} of {v['id']}?", f"There is no record of {v['id']}.", w)


def read(r):
    v = invoice(r); attr = r.choice(["customer", "amount", "due", "status"])
    q = r.choice([f"What is the {attr} of {v['id']}?", f"Look up the {attr} of {v['id']}.", f"{v['id']}: what is the {attr}?"])
    val = {"customer": v["customer"], "amount": str(v["amount"]), "due": f"{MON[v['due'][0] - 1]} {v['due'][1]}, 2026", "status": v["status"]}[attr]
    return row(q, f"The {attr} of {v['id']} is {val}.", working(r, v, attr))


def tax(r):
    v = invoice(r); p = r.choice([5, 10, 15, 20, 25]); t = p * v["amount"] // 100
    if p * v["amount"] % 100: return tax(r)
    kind = r.choice(["tax", "late fee", "discount"])
    q = r.choice([f"What is the {kind} on the amount of {v['id']} at {p} percent?", f"Work out the {kind} on the amount of {v['id']} at {p} percent.",
                  f"On the amount of {v['id']}, what is a {kind} of {p} percent?"])
    return row(q, f"The {kind} on {v['id']} is {t}.", working(r, v, "amount", span(f"<CALC>pct:{p}% of {v['amount']}<EQ>{t}<ECALC>")))


def balance(r):
    v = invoice(r); paid = 20 * r.randrange(1, v["amount"] // 20); owed = v["amount"] - paid
    q = r.choice([f"How much of the amount of {v['id']} is still owed after a payment of {paid}?",      # the number the span copies from the question sits last, nearest the span (measured: 6300-4300 for a payment of 400 when it sat first)
                  f"What is left of the amount of {v['id']} after paying {paid}?",
                  f"On the amount of {v['id']}, what remains after a part payment of {paid}?"])
    return row(q, f"Still owed on {v['id']}: {owed}.", working(r, v, "amount", span(f"<CALC>{v['amount']}-{paid}<EQ>{owed}<ECALC>")))


def days(r):
    v = invoice(r); m, d = v["due"]; due = dt.date(2026, m, d)
    today = due + dt.timedelta(days=r.randrange(-40, 41))
    if today == due or today.year != 2026: return days(r)
    tq = f"{MON[today.month - 1]} {today.day}, 2026"
    q = r.choice([f"Today is {tq}. How many days until {v['id']} is due?", f"It is {tq}. When is {v['id']} due, in days?",
                  f"Today is {tq}. Is {v['id']} due yet, and by how many days?"])
    a, b = (due, today) if due > today else (today, due); n = (a - b).days
    sp = span(f"<CALC>cal:{MON[a.month - 1][:3]}{a.day}-{MON[b.month - 1][:3]}{b.day}<EQ>{n}<ECALC>")
    ans = f"{v['id']} is due in {n} days." if due > today else f"{v['id']} is overdue by {n} days."
    return row(q, ans, working(r, v, "due", sp))


def weekday(r):
    """the shipped model's own weekday shape, no year in the span (the kit's weekday_with_year teaches a different one)"""
    m = r.randrange(1, 13); d = r.randrange(1, 29); wd = dt.date(2026, m, d).strftime("%A")
    return row(f"What day of the week is {MON[m - 1]} {d}, 2026?", f"{wd}.", span(f"<CALC>dow:{MON[m - 1][:3]}{d}<EQ>{wd}<ECALC>"))


def with_frames(gen):
    """the kit's own row with an invoice's four frames in front of its working: with an archive attached the kernel fetches records
    for any prompt that carries a number (amounts and dates match on number pieces), and the base then reads the frame instead of
    computing (measured: 15 percent of 240 became 240, a weekday became a due date). These rows teach the adapter to ignore a
    frame the question did not ask for."""
    def g(r):
        ids = gen(r); attrs = ["customer", "amount", "due", "status"]; r.shuffle(attrs); fr, _ = frames(r, invoice(r), attrs)
        if SP["think"] in ids: k = ids.index(SP["think"]) + 1; return ids[:k] + fr + ids[k:]
        k = ids.index(SP["sol"]); return ids[:k] + [SP["think"]] + fr + [SP["endthink"]] + ids[k:]
    g.__name__ = gen.__name__ + "_framed"; return g


GENS = [(read, 4), (tax, 3), (balance, 4), (days, 4), (absent, 3),
        (arithmetic, 3), (units, 1), (percent, 1), (letters, 1), (compare, 1), (record, 3), (chat, 2), (knowledge, 2),
        (weekday, 1), (with_frames(weekday), 1),
        (with_frames(arithmetic), 3), (with_frames(percent), 1), (with_frames(units), 1), (with_frames(compare), 1), (with_frames(knowledge), 1), (with_frames(chat), 1)]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--n", type=int, default=40000); ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args(); r = random.Random(a.seed); fns = [f for f, w in GENS for _ in range(w)]; buf = []; kinds = {}
    for _ in range(a.n):
        f = r.choice(fns); ids = f(r)
        if not (8 <= len(ids) <= 512): continue
        buf += ids; kinds[f.__name__] = kinds.get(f.__name__, 0) + 1
    np.array(buf, dtype=np.uint32).tofile(a.out); print(f"{len(buf)} tokens -> {a.out}")
    for k, v in sorted(kinds.items()): print(f"   {k:<12} {v}")


if __name__ == "__main__": main()
