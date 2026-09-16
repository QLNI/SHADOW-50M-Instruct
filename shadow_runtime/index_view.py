"""A view of the engram index on disk: which key n-grams point at which records, with the Hebbian weight on every link.

The kernel maps index.bin writable and bumps a link's weight when a fetched record is confirmed (its quote copied), so the
trail persists in the file. This module reads the file back after each turn and reports which links moved. The hash, the
bucket probe and the key rule (folded ids, stop words and punctuation removed, n-grams of two and three starting at an
identifier token) mirror the kernel's, so a label here is the n-gram the kernel hashed.

The weight rule was corrected on 2026-09-16 after CarefulHamster7184 asked on r/MachineLearning what happens when the
first retrieval is wrong but the model still copies it: whether the +1 makes the error self-confirming, and whether the
weights are capped, decayed or ever given a negative update. They were capped at 255 and never decayed, and a warmed
link could skip the word-overlap check. Measured: a wrongly warmed sibling record took 12 of 12 questions and never
recovered. Now a warmed link only breaks ties among the best word matches, and on every confirmed copy the rival links
in the same bucket lose 1. The ablation is in benchmarks/trail_ablation/.
"""
import os, numpy as np
from rich.text import Text

M64 = (1 << 64) - 1; C1 = 0x9e3779b97f4a7c15; C2 = 0xff51afd7ed558ccd; MAXN = 3


def mix(h, v):
    h ^= (v + C1 + ((h << 6) & M64) + (h >> 2)) & M64
    return (h * C2) & M64


class IndexView:
    def __init__(self, archive, enc, blobs):
        self.dir = archive; self.enc = enc
        self.tok = np.fromfile(os.path.join(archive, "tokens.bin"), dtype=np.int32)
        self.fold = np.fromfile(os.path.join(blobs, "fold.bin"), dtype=np.int32); self.ident = np.fromfile(os.path.join(blobs, "ident.bin"), dtype=np.uint8)
        self.stops = set(np.fromfile(os.path.join(blobs, "stop.bin"), dtype=np.int32).tolist())
        self.path = os.path.join(archive, "index.bin"); self._load(); self.prev = self.w.copy(); self.nudged = []; self.touched = []

    def _load(self):
        raw = open(self.path, "rb").read(); hdr = np.frombuffer(raw[:16], dtype=np.uint32); self.nrec, self.nb, self.np_, self.vsz = map(int, hdr); o = 16
        self.rs = np.frombuffer(raw[o:o + 4 * self.nrec], dtype=np.uint32); o += 4 * self.nrec
        self.re = np.frombuffer(raw[o:o + 4 * self.nrec], dtype=np.uint32); o += 4 * self.nrec
        self.b = np.frombuffer(raw[o:o + 8 * self.nb], dtype=[("key", "<u4"), ("head", "<u4")]); o += 8 * self.nb
        o += 2 * self.nb
        self.p = np.frombuffer(raw[o:o + 8 * self.np_], dtype=[("rec", "<u4"), ("next", "<u4")]); o += 8 * self.np_
        self.w = np.frombuffer(raw[o:o + self.np_], dtype=np.uint8).copy(); self.w_off = o
        self.edges = self._edges()

    def _punct(self, t):
        s = self.enc.dec([int(t)]) if t >= 32 else ""
        return not any(c.isalnum() for c in s)

    def _find(self, h):
        key = ((h >> 32) ^ h) & 0xffffffff or 1; m = self.nb - 1; i = (h >> 7) & m
        for _ in range(self.nb):
            if self.b["key"][i] == key: return i
            if self.b["key"][i] == 0: return None
            i = (i + 1) & m
        return None

    def _edges(self):
        """every (n-gram label, record, posting) the index holds for the records' own words; the posting index is where the weight lives"""
        out = []; seen = set()
        for r in range(self.nrec):
            toks = [int(t) for t in self.tok[self.rs[r]:self.re[r]]]
            keep = [(t, int(self.fold[t]) if t < len(self.fold) else t) for t in toks if t >= 32 and t not in self.stops and not self._punct(t)]
            for s0 in range(len(keep)):
                if not (keep[s0][0] < len(self.ident) and self.ident[keep[s0][0]]): continue
                for n in (1, 2):
                    if s0 + n >= len(keep): break
                    h = 0x12345
                    for j in range(n + 1): h = mix(h, (keep[s0 + j][1] & 0xffffffff) + 1)
                    bi = self._find(h)
                    if bi is None: continue
                    pi = int(self.b["head"][bi]); steps = 0
                    while pi and steps < 100000:
                        if int(self.p["rec"][pi]) == r and (bi, r) not in seen:
                            seen.add((bi, r)); out.append((self.enc.dec([keep[s0 + j][0] for j in range(n + 1)]).strip(), r, pi)); break
                        pi = int(self.p["next"][pi]); steps += 1
        return out

    def record_text(self, r, width=40):
        s = self.enc.dec([int(t) for t in self.tok[self.rs[r]:self.re[r]] if t >= 32]).strip()
        s = s.split("\n", 1)[1].strip() if "\n" in s else s
        return s if len(s) <= width else s[:width - 1] + "…"

    def turn(self):
        """re-read the weights; remember which links the kernel just nudged"""
        raw = open(self.path, "rb").read(); w = np.frombuffer(raw[self.w_off:self.w_off + self.np_], dtype=np.uint8).copy()
        moved = np.flatnonzero(w != self.prev); self.prev = w; self.w = w
        self.nudged = [(lab, r, pi) for lab, r, pi in self.edges if pi in set(moved.tolist())]
        self.touched = list(dict.fromkeys(r for _, r, _ in self.nudged))

    def render(self, rows=7, width=84):
        keys = int((self.b["key"] != 0).sum()); t = Text(no_wrap=True, overflow="crop")
        t.append(f" engram index  {self.nrec:,} records · {keys:,} keys · {self.np_:,} links · weight {int(self.w.sum()):,}", style="grey62")
        if self.nudged: t.append(f"   +1 on {len(self.nudged)} link{'s' if len(self.nudged) > 1 else ''}", style="bold yellow")
        t.append("\n")
        by_rec = {}
        for lab, r, pi in self.edges: by_rec.setdefault(r, []).append((lab, pi))
        order = self.touched + [r for r, _ in sorted(((r, max(int(self.w[pi]) for _, pi in e)) for r, e in by_rec.items()), key=lambda x: -x[1]) if r not in self.touched]
        hot = {pi for _, _, pi in self.nudged}; shown = 0
        for r in order:
            if shown >= rows - 1: break
            links = sorted(by_rec.get(r, []), key=lambda e: -int(self.w[e[1]]))
            links = ([l for l in links if int(self.w[l[1]]) > 0] or links[:1])[:3]     # the trodden links; a record nobody asked for shows its first key at weight 0
            t.append(" ● " if r in self.touched else " ○ ", style="bold yellow" if r in self.touched else "grey50")
            t.append(f"{self.record_text(r, 36):36}", style="bright_green" if r in self.touched else "grey70")
            for lab, pi in links:
                w = int(self.w[pi]); t.append(" ◀" + "─" * min(6, 1 + w) + " ", style="yellow" if pi in hot else "grey42")
                t.append(f"{lab[:18]}", style="bold yellow" if pi in hot else "cyan"); t.append(f" w{w}", style="bold yellow" if pi in hot else "grey50")
                if pi in hot: t.append(" +1", style="bold yellow")
            t.append("\n"); shown += 1
        return t
