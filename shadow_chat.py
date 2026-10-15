"""Chat with SHADOW 50M. Picks the prebuilt kernel for your system.
    python shadow_chat.py                       # chat
    python shadow_chat.py --archive my_notes    # chat with an archive built by shadow_archive.py on disk
    python shadow_chat.py --trace               # also print the model's working ([need], [quote], [calc] ... before the answer)
Needs: python 3.9+, numpy, tokenizers (pip install numpy tokenizers).
"""
import sys, argparse, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from shadow_runtime import Engine

ap = argparse.ArgumentParser(); ap.add_argument("--archive", default=None); ap.add_argument("--trace", action="store_true"); ap.add_argument("--stats", action="store_true"); ap.add_argument("--topk", type=int, default=1); ap.add_argument("--model", default=None, help="a container other than the shipped one, e.g. one you fine-tuned and exported")
ap.add_argument("--remember", type=int, default=0, help="keep the last N exchanges in the window (0 = every message stands alone; 1 lets 'now multiply that by 4' work)")
a = ap.parse_args()
eng = Engine(model=a.model, archive=a.archive, topk=a.topk, remember=a.remember)
print("SHADOW 50M" + (f", archive {a.archive}" if a.archive else "") + ". Type your message, 'quit' to stop.")
while True:
    try: q = input("you> ").strip()
    except EOFError: break
    if q in ("quit", "exit"): break
    if not q: continue
    ans = eng.chat(q)
    if a.trace: print("   ", eng.last["trace"].split("[sol]")[0].strip().replace("\n", "\n    "))
    print("shadow>", ans + (f"   [{eng.stats()}]" if a.stats else ""))
