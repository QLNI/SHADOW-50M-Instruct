"""Trail ablation for the r/ML question: cold vs correctly warmed vs incorrectly warmed, with competing records under
the same key (three attributes per key: quantity, bin, supplier). The wrong warm bumps the BIN record's links to 5
for a QUANTITY question, which is the self-confirming case the commenter describes. Then we ask the right question
five more times and see whether the index recovers, with the trail short-circuit on (default) and off (AX_TRAIL=0)."""
import os, sys, re, json, random, shutil, subprocess, pathlib
REL = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REL)); sys.path.insert(0, str(REL / "tokenizer"))
from shadow_runtime import Engine
from shadow_runtime.index_view import IndexView
from enc_v2 import get as get_enc
HERE = pathlib.Path(__file__).resolve().parent
random.seed(3)
letters = ["KQ", "LM", "RT", "PX", "ZB", "HN", "WD", "CV", "JF", "GS", "MY", "TK"]
keys = [f"{l}-{random.randint(100, 999)}" for l in letters]
vals = {k: (random.randint(100, 9999), f"{random.choice('ABCDEFG')}{random.randint(1, 40)}", random.choice(["Acme", "Norwell", "Halden", "Brisk", "Tarrow", "Lindqvist"])) for k in keys}
lines = []
for k in keys:
    q, b, s = vals[k]
    lines += [f"Record {k} quantity: {q}.", f"Record {k} bin: {b}.", f"Record {k} supplier: {s}."]
notes = HERE / "notes.txt"; notes.write_text("\n".join(lines) + "\n", encoding="utf-8")
ARCH = HERE / "arch"

def build():
    if ARCH.exists(): shutil.rmtree(ARCH)
    subprocess.run([sys.executable, str(REL / "shadow_archive.py"), "build", str(notes), str(ARCH)], check=True, capture_output=True, cwd=str(REL))

def ask_all(reps=1, trail=None):
    env = dict(os.environ);
    if trail is not None: env["AX_TRAIL"] = str(trail)
    os.environ.update(env)
    eng = Engine(kernel=os.environ.get("SHADOW_KERNEL"), archive=str(ARCH), topk=1, remember=0)
    right = wrong = absent = 0
    for k in keys:
        q = vals[k][0]; ans = None
        for _ in range(reps):
            ans = eng.chat(f"What is the quantity of Record {k}?"); tr = eng.last["trace"]
        m = re.search(r"\[quote\]pos=(\d+): ([^\n]*)", tr)
        if str(q) in ans and m and "quantity" in m.group(2): right += 1
        elif m: wrong += 1
        else: absent += 1
    return right, wrong, absent

def warm_wrong(level=5):
    """bump every link that points at the BIN record of each key to `level`"""
    enc = get_enc(); iv = IndexView(str(ARCH), enc, str(REL / "deployment"))
    bin_recs = {r for lab, r, pi in iv.edges if "bin" in iv.record_text(r, 200)}
    with open(iv.path, "r+b") as f:
        n = 0
        for lab, r, pi in iv.edges:
            if r in bin_recs: f.seek(iv.w_off + pi); f.write(bytes([level])); n += 1
    return n

res = {}
build(); res["cold"] = ask_all(); print("cold (right, wrong record, no record):", res["cold"], flush=True)
res["warm_right x3, then ask"] = (ask_all(reps=3), ask_all())[1]; print("correctly warmed:", res["warm_right x3, then ask"], flush=True)
build(); n = warm_wrong(5); res["warm_wrong(bin=5)"] = ask_all(); print(f"wrongly warmed ({n} links set to 5):", res["warm_wrong(bin=5)"], flush=True)
res["warm_wrong then ask x5"] = (ask_all(reps=5), ask_all())[1]; print("after asking the right question 5 more times:", res["warm_wrong then ask x5"], flush=True)
build(); warm_wrong(5); res["warm_wrong, AX_TRAIL=0"] = ask_all(trail=0); print("wrongly warmed, short-circuit off:", res["warm_wrong, AX_TRAIL=0"], flush=True)
json.dump(res, open(HERE / "ablate_run.json", "w"), indent=1)   # your run; ablate.json and ablate_fixed.json are the shipped results
