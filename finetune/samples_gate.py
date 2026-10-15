"""The published-samples gate for an adapter: the 37 prompts of SAMPLES.md, answered through the kernel with and without the
adapter, must give the same trace token for token. What the base does on those prompts is measured, not assumed.

    python finetune/samples_gate.py --lora adapter.bin [--exe kernel] [--notes examples_notes.txt]

The archive the samples read from is built from --notes into a temporary folder. Sample 37 is two turns with the first kept
in the window. Prints every prompt whose trace changed, and the count.
"""
import argparse, os, re, sys, subprocess, tempfile, pathlib
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent; sys.path.insert(0, str(ROOT))
from shadow_runtime import Engine


def run_all(exe, arch, items, lora):
    if lora: os.environ["LORA"] = os.path.abspath(lora)
    else: os.environ.pop("LORA", None)
    e = Engine(kernel=exe, archive=arch); out = []
    for n, q in items:
        if "  ->  " in q:
            first, second = q.split("  ->  "); e.history = []; e.chat(first.strip()); a = e.chat(second.strip(), remember=1)
        else: e.history = []; a = e.chat(q.strip())
        out.append((e.last["trace"], a))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--exe", default=None); ap.add_argument("--lora", required=True); ap.add_argument("--notes", default=str(ROOT / "examples_notes.txt"))
    ap.add_argument("--samples", default=str(ROOT / "SAMPLES.md")); a = ap.parse_args()
    arch = os.path.join(tempfile.mkdtemp(prefix="samples_"), "archive")
    subprocess.run([sys.executable, str(ROOT / "shadow_archive.py"), "build", a.notes, arch], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    items = re.findall(r"^### (\d+)\. (.+?)$", open(a.samples, encoding="utf-8").read(), flags=re.M)
    base = run_all(a.exe, arch, items, None); ad = run_all(a.exe, arch, items, a.lora); same = 0; same_ans = 0
    for (n, q), (tb, ab), (ta, aa) in zip(items, base, ad):
        ok = tb == ta; same += ok; same_ans += ab.strip() == aa.strip()
        if not ok: print(f"   CHANGED {n:>2} {q[:50]!r}\n        base    {ab[:70]!r}\n        adapter {aa[:70]!r}")
    print(f"adapter {os.path.basename(a.lora)}: {same}/{len(items)} sample traces identical to the base, {same_ans}/{len(items)} answers identical")


if __name__ == "__main__": main()
