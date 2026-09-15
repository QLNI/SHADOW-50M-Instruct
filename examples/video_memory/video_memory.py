"""Video memory: a vision model watches a video once, SHADOW 50M keeps what it saw on disk and answers about any moment.

    python examples/video_memory/video_memory.py build  film.mp4  out/           # frames -> captions -> records -> archive
    python examples/video_memory/video_memory.py ask    out/  "What happens at moment M-0042?"
    python examples/video_memory/video_memory.py ask    out/  "What was seen at 01:24?"
    python examples/video_memory/video_memory.py ask    out/  "When does a rabbit appear?"
    python examples/video_memory/video_memory.py chat   out/                      # ask in a loop

Stages of `build`, each resumable and each leaving its files in out/:
  1. frames/       one JPEG every --every seconds (ffmpeg), 512 pixels wide
  2. captions.jsonl one line per frame from the vision model through Ollama: a sentence, the objects, the people
  3. notes.txt     the records SHADOW keeps, one per moment, the caption's first clause of at most ten words:
                       Moment M-0042 scene: A rabbit steps out of a burrow into sunlight.
                   (a moment's time is its number times --every seconds; the harness prints it with every answer. The objects
                   and people the vision model listed stay in captions.jsonl and feed the word index, not the archive: a second
                   record under the same key steals the fetch, measured)
  4. archive/      the SHADOW archive on disk: the token stream, the index, the 1-bit memory (shadow_archive.py build)

Asking: the model finds a record by an identifier, so "moment M-0042" and "01:24" go straight to the archive. A question
that names no moment and no time ("when does a rabbit appear?") has nothing for the index to key on; the harness looks its
words up in the captions, picks the moment they point at, and asks the model about that moment. The vision model writes
the lines; SHADOW remembers them. What was never captioned cannot be recalled. Needs ffmpeg on the path and Ollama running
with a vision model (default gemma3:4b).
"""
import argparse, base64, json, os, re, subprocess, sys, time, pathlib
import requests
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent.parent
PROMPT = ("Describe this video frame in one sentence of at most 20 words: who or what is visible and what is happening. "
          "Then a second line starting 'objects:' listing the visible objects, comma separated. "
          "Then a third line starting 'people:' naming the people or characters visible, or 'none'.")
STOP = {"a", "an", "the", "of", "and", "in", "on", "with", "is", "are", "at", "to", "none", "light", "source", "scene", "background", "foreground",
        "when", "does", "do", "what", "where", "which", "who", "appear", "appears", "see", "seen", "show", "shows", "there", "any", "moment", "time", "video"}


def hms(s): return f"{int(s) // 60:02d}:{int(s) % 60:02d}"


SCENE_WORDS = 10


def scene_text(c):
    """the scene record's value: the caption's first clause, at most SCENE_WORDS words. The model reads a record back by copying
    it, and the copy stops at a comma or a long phrase (measured: 41 of 60 on 15-to-20-word captions); a short clause is what it
    keeps whole."""
    first = re.split(r"[;:(]| - ", c["sentence"])[0]     # a semicolon, a colon, a bracket or a spaced dash ends the first clause
    clause = re.split(r",", first)[0]
    w = (clause if len(clause.split()) >= 5 else re.sub(r",", "", first)).split()
    return " ".join(w[:SCENE_WORDS]).rstrip(".,;") + "."


def frames(video, out, every):
    d = out / "frames"; d.mkdir(parents=True, exist_ok=True)
    if not any(d.iterdir()):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"fps=1/{every},scale=512:-1", str(d / "f_%05d.jpg")], check=True)
    return sorted(d.glob("f_*.jpg"))


def caption(path, model, host):
    img = base64.b64encode(path.read_bytes()).decode()
    r = requests.post(f"{host}/api/generate", json={"model": model, "stream": False, "images": [img], "prompt": PROMPT, "options": {"num_predict": 120, "temperature": 0}}, timeout=600)
    r.raise_for_status(); text = r.json()["response"]
    sent = next((l.strip() for l in text.splitlines() if l.strip() and not l.lower().startswith(("objects:", "people:"))), "").rstrip(".") + "."
    objs = next((l.split(":", 1)[1].strip().rstrip(".") for l in text.splitlines() if l.lower().startswith("objects:")), "")
    ppl = next((l.split(":", 1)[1].strip().rstrip(".") for l in text.splitlines() if l.lower().startswith("people:")), "none")
    return sent, objs or "none", ppl or "none"


def build(video, out, every, model, host):
    out = pathlib.Path(out); fr = frames(pathlib.Path(video), out, every); print(f"{len(fr)} frames, one every {every} s")
    cap = out / "captions.jsonl"; done = {}
    if cap.exists():
        for l in cap.open(encoding="utf-8"): j = json.loads(l); done[j["i"]] = j
    t0 = time.time(); n0 = len(done)
    with cap.open("a", encoding="utf-8") as f:
        for i, p in enumerate(fr):
            if i in done: continue
            sent, objs, ppl = caption(p, model, host)
            j = {"i": i, "t": i * every, "sentence": sent, "objects": objs, "people": ppl}; done[i] = j
            f.write(json.dumps(j, ensure_ascii=False) + "\n"); f.flush()
            if len(done) % 10 == 0: print(f"  captioned {len(done)}/{len(fr)}  {(time.time() - t0) / max(1, len(done) - n0):.1f} s each", flush=True)
    lines = []
    for i in sorted(done):
        j = done[i]; m = f"M-{i + 1:04d}"
        lines.append(f"Moment {m} scene: {scene_text(j)}")          # one record per moment: a second record under the same key steals the fetch (measured)
    (out / "notes.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines)} records -> {out / 'notes.txt'}")
    subprocess.run([sys.executable, str(ROOT / "shadow_archive.py"), "build", str(out / "notes.txt"), str(out / "archive")], check=True)


class Memory:
    """SHADOW's archive on disk, plus a word index over the captions for questions that name no moment and no time."""
    def __init__(self, out, topk=1):
        sys.path.insert(0, str(ROOT)); from shadow_runtime import Engine
        self.out = pathlib.Path(out); self.e = Engine(archive=str(self.out / "archive"), topk=topk)
        self.caps = [json.loads(l) for l in (self.out / "captions.jsonl").open(encoding="utf-8")]
        self.words = {}
        for c in self.caps:
            for w in set(re.findall(r"[a-z]+", f"{c['sentence']} {c['objects']} {c['people']}".lower())):
                if w not in STOP and len(w) > 2: self.words.setdefault(w, []).append(c["i"])

    def moment_for(self, q):
        """the moment the question's words point at: the frame holding the most of them, the earliest on a tie; None if no word is known"""
        ws = [w for w in re.findall(r"[a-z]+", q.lower()) if w not in STOP and len(w) > 2]
        ws = [w for w in ws if w in self.words] + [w[:-1] for w in ws if w.endswith("s") and w[:-1] in self.words]
        if not ws: return None
        score = {}
        for w in set(ws):
            for i in self.words[w]: score[i] = score.get(i, 0) + 1
        return max(sorted(score), key=lambda i: score[i])

    def moment_at(self, t):
        """the moment whose frame is nearest to a time in seconds"""
        return min(range(len(self.caps)), key=lambda i: abs(self.caps[i]["t"] - t))

    def scene(self, i):
        """the model reads the moment's scene record back; -> the answer prefixed with the moment and its time"""
        m = f"M-{i + 1:04d}"; a = self.e.chat(f"What is the scene at moment {m}?", remember=False)
        return f"{m} at {hms(self.caps[i]['t'])}: {a}"

    def ask(self, q):
        """-> (answer, how). how says which record the harness pointed the model at; None when the question is asked as is."""
        mm = re.search(r"\bM-(\d{4})\b", q); tt = re.search(r"\b(\d{1,2}):(\d{2})\b", q)
        if mm:
            i = int(mm.group(1)) - 1
            if not 0 <= i < len(self.caps): return self.e.chat(q, remember=False), None
            return self.scene(i), "the scene record of that moment"
        if tt:
            i = self.moment_at(int(tt.group(1)) * 60 + int(tt.group(2))); return self.scene(i), f"the moment nearest {tt.group(0)}"
        i = self.moment_for(q)
        if i is None: return self.e.chat(q, remember=False), None
        return self.scene(i), "the moment the words of the question point at, from the word index over the captions"

    def stats(self): return self.e.stats()

    @property
    def last(self): return self.e.last


def ask(out, q, trace=False):
    mem = Memory(out); a, how = mem.ask(q)
    if how: print("   ", how)
    if trace: print("   ", mem.last["trace"].split("[sol]")[0].strip().replace("\n", "\n    "))
    print(a); print(f"[{mem.stats()}]")


def chat(out):
    mem = Memory(out); print("video memory. Ask about any moment; 'quit' to stop.")
    while True:
        try: q = input("you> ").strip()
        except EOFError: break
        if q in ("quit", "exit"): break
        if not q: continue
        a, how = mem.ask(q)
        if how: print("   ", how)
        print("shadow>", a, f"  [{mem.stats()}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["build", "ask", "chat"]); ap.add_argument("a"); ap.add_argument("b", nargs="?")
    ap.add_argument("--every", type=float, default=2.0); ap.add_argument("--model", default="gemma3:4b"); ap.add_argument("--host", default="http://localhost:11434"); ap.add_argument("--trace", action="store_true")
    x = ap.parse_args()
    if x.cmd == "build": build(x.a, x.b, x.every, x.model, x.host)
    elif x.cmd == "ask": ask(x.a, x.b, x.trace)
    else: chat(x.a)
