"""Build an archive on disk for SHADOW 50M, and ask it questions.

    python shadow_archive.py build notes.txt my_notes      # one record per non-empty line -> my_notes/{tokens.bin, index.bin, kv.bin}
    python shadow_archive.py ask my_notes "What is the count of Vault-418?"
    python shadow_archive.py ask my_notes "..." --trace     # show the need line, the quoted record and its position

What `build` writes:
    tokens.bin   the records as token ids, framed ([copen] pos=N text [cclose]), 4 bytes per token
    index.bin    the engram index: identifier n-grams -> records, with Hebbian weights (about 22 bytes per token)
    kv.bin       the 1-bit K/V of every token, 288 bytes per token, encoded once by the kernel (this is the slow step: ~0.4 ms per token on a laptop)
Records are text lines with an identifier in them (a name, a code, an id). The model finds a record by that identifier and an
attribute word, quotes it with its position, and answers; it says so when there is no record.
"""
import os, sys, argparse, pathlib, subprocess, numpy as np
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
from shadow_runtime import Engine, default_kernel
sys.path.insert(0, str(HERE / "tokenizer"))
from enc_v2 import get, SP


def index_tool():
    k = default_kernel(); return k.parent / ("shadow_index.exe" if k.name.endswith(".exe") else "shadow_index")


def build(src, out):
    enc = get(); os.makedirs(out, exist_ok=True); ids = []; n = 0
    lines = [l.strip() for l in open(src, encoding="utf-8")] if os.path.isfile(src) else [l.strip() for f in sorted(os.listdir(src)) for l in open(os.path.join(src, f), encoding="utf-8")]
    for i, line in enumerate(l for l in lines if l):
        ids += [SP["copen"]] + enc.plain(f"pos={i + 1}\n{line}", strict=False) + [SP["cclose"]]; n += 1
    arr = np.array(ids, dtype=np.int32); arr.tofile(os.path.join(out, "tokens.bin"))
    fold = HERE / "deployment" / "fold.bin"
    r = subprocess.run([str(index_tool()), "build", os.path.join(out, "tokens.bin"), str(fold), os.path.join(out, "index.bin")], capture_output=True, text=True)
    print(f"{n} records, {len(arr)} tokens; " + ([l for l in r.stdout.splitlines() if l.startswith("BUILD")] or [r.stdout + r.stderr])[-1][:160])
    eng = Engine(); np.array(eng.prompt_ids("What is the count of Vault-1?"), dtype=np.int32).tofile(eng.prompt_path)
    r = subprocess.run([eng.kernel, eng.model, "0"], capture_output=True, text=True, env=dict(os.environ, KVBUILD="1", ARCHIVE=os.path.abspath(out), SHADOW_PROMPT=eng.prompt_path))
    print(([l for l in r.stdout.splitlines() if l.startswith("KVBUILD done")] or [r.stdout[-200:] + r.stderr[-200:]])[-1][:160])
    for f in ("tokens.bin", "index.bin", "kv.bin"): print(f"  {f}: {os.path.getsize(os.path.join(out, f)) / 1e6:.2f} MB")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["build", "ask"]); ap.add_argument("a"); ap.add_argument("b", nargs="?"); ap.add_argument("--trace", action="store_true"); ap.add_argument("--topk", type=int, default=1)
    x = ap.parse_args()
    if x.cmd == "build": build(x.a, x.b)
    else:
        eng = Engine(archive=x.a, topk=x.topk); ans = eng.chat(x.b, remember=False)
        if x.trace: print(eng.last["trace"].split("[sol]")[0].strip())
        print(ans); print(f"[{eng.stats()}]")


if __name__ == "__main__": main()
