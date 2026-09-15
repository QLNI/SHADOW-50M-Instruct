"""Measure video memory: questions written from the captions themselves, the ANSWER TEXT scored against the caption.

    python examples/video_memory/measure.py out/ [--n 60]

Three shapes, scored separately, every one a fresh kernel process with the archive on disk. An answer is right when it
carries at least two thirds of the stored record's words (the model reads the record back; a wrong record fails this at once).
  by moment   "What is the scene at moment M-0042?"      the model finds the record by the identifier
  by time     "What was seen at 01:24?"                  the harness maps the time to the moment, the model reads it
  by content  "When does a rabbit appear?"               the harness's word index over the captions picks the moment, the model reads it
The captions are the truth: what the vision model wrote is what SHADOW is asked to remember.
"""
import argparse, json, random, re, sys, pathlib, statistics
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); from video_memory import Memory, hms, STOP, scene_text
ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--n", type=int, default=60); ap.add_argument("--seed", type=int, default=7); a = ap.parse_args()
out = pathlib.Path(a.out); mem = Memory(str(out)); caps = mem.caps; r = random.Random(a.seed); pick = r.sample(caps, min(a.n, len(caps)))
def words(t): return [w for w in re.findall(r"[a-z]+", t.lower()) if w not in STOP and len(w) > 2]
def carries(ans, sent):
    w = words(sent); return bool(w) and sum(x in ans.lower() for x in w) >= 2 * len(w) / 3
res = {}; fetch = []; tps = []
def score(name, qs, judge):
    ok = 0; miss = []
    for c, q in qs:
        ans, how = mem.ask(q); fetch.append(mem.last["fetch_ms"]); tps.append(mem.last["tok_s"]); hit = judge(c, ans); ok += hit
        if not hit and len(miss) < 2: miss.append(f"{q[:34]}->{ans[:60]!r}")
    res[name] = (ok, len(qs)); print(f"  {name:12} {ok}/{len(qs)}  " + "; ".join(miss), flush=True)
score("by moment", [(c, f"What is the scene at moment M-{c['i'] + 1:04d}?") for c in pick], lambda c, ans: carries(ans, scene_text(c)))
score("by time", [(c, f"What was seen at {hms(c['t'])}?") for c in pick], lambda c, ans: carries(ans, scene_text(c)))
qs = []
for c in pick:
    objs = [o.strip().lower() for o in c["objects"].split(",") if o.strip() and o.strip().lower() not in STOP and " " not in o.strip()]
    if objs: qs.append((c, f"When does a {r.choice(objs)} appear?"))
def content_ok(c, ans):
    m = re.match(r"(M-\d{4})", ans)
    if not m: return False
    i = int(m.group(1)[2:]) - 1; w = [x for x in words(ans.split("?")[0]) if x in words(c["objects"])]
    return 0 <= i < len(caps) and carries(ans, scene_text(caps[i]))
# for the content shape, right = the answer reads back a moment whose caption or objects hold the asked word
def content_judge(q):
    w = words(q)[-1] if words(q) else ""
    def j(c, ans):
        m = re.match(r"(M-\d{4})", ans)
        if not m: return False
        i = int(m.group(1)[2:]) - 1
        return 0 <= i < len(caps) and (w in (caps[i]["sentence"] + " " + caps[i]["objects"]).lower() or w[:-1] in (caps[i]["sentence"] + " " + caps[i]["objects"]).lower()) and carries(ans, scene_text(caps[i]))
    return j
ok = 0; miss = []
for c, q in qs:
    ans, how = mem.ask(q); fetch.append(mem.last["fetch_ms"]); tps.append(mem.last["tok_s"]); hit = content_judge(q)(c, ans); ok += hit
    if not hit and len(miss) < 2: miss.append(f"{q[:30]}->{ans[:60]!r}")
res["by content"] = (ok, len(qs)); print(f"  {'by content':12} {ok}/{len(qs)}  " + "; ".join(miss), flush=True)
print(f"\narchive: {len(caps)} records, {len(caps)} moments, {hms(caps[-1]['t'])} of video; fetch {statistics.median(fetch):.2f} ms median; decode {statistics.median(tps):.0f} tok/s; {mem.last['rss_mb']:.0f} MB resident")
json.dump({k: f"{v[0]}/{v[1]}" for k, v in res.items()} | {"records": len(caps), "fetch_ms": statistics.median(fetch), "tok_s": statistics.median(tps)}, (out / "measure.json").open("w"), indent=1)
