"""The SHADOW 50M encoder: text <-> token ids of the frozen table. turns(conv, chunks) lays out a conversation; plain(text)
encodes text; dec(ids) decodes. Markup tags become symbol ids; frames become [copen] "pos=N\n" text [cclose].
"""
import glob, json, os, re
import numpy as np
from tokenizers import Tokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
TAB = HERE
SYM = json.load(open(os.path.join(TAB, "symbols_v2.json")))
SP = SYM["symbols"]
OFF = SYM["table_offset"]
TAG2SYM = {"<CALC>": "calc", "<EQ>": "eq", "<ECALC>": "ecalc", "<VM>": "vm", "<RUN>": "run", "<EVM>": "evm",
           "<GRID>": "grid", "<EGRID>": "egrid", "<ROW>": "row", "<ERR>": "err", "<NEED>": "need",
           "<SEP>": "sep", "<CODE>": "code", "<ECODE>": "ecode", "<QUOTE>": "quote",
           "<THINK>": "think", "</THINK>": "endthink", "<SOL>": "sol", "</SOL>": "endsol", "<ABSTAIN>": "abstain"}
SPAN_OPEN = {"calc", "vm", "grid"}
SPAN_CLOSE = {"ecalc", "evm", "egrid"}
TAG_RE = re.compile("(" + "|".join(re.escape(t) for t in TAG2SYM) + r"|<FRAME pos=\d+>|</FRAME>)")
FRAME_RE = re.compile(r"<FRAME pos=(\d+)>")


class OOV(Exception):
    pass


class Encoder:
    def __init__(self):
        tj = glob.glob(os.path.expanduser(
            os.path.join(HERE, "tokenizer.json")), recursive=True)
        tj = tj[0] if tj else os.environ.get("SHADOW_TOKJSON")
        self.tk = Tokenizer.from_file(tj)
        n2o = np.load(os.path.join(TAB, "new2old_v2.npy"))
        self.o2n = {int(o): i + OFF for i, o in enumerate(n2o)}
        self.n2o = n2o
        self.digit = {str(d): i for d, i in enumerate(SYM["digit_ids"])}
        self.lut = np.full(int(n2o.max()) + 1, -1, dtype=np.int32)
        self.lut[n2o.astype(np.int64)] = np.arange(len(n2o), dtype=np.int32) + OFF

    def plain_batch(self, texts):
        """lenient batch path for world text: Rust batch encode + vectorized id map; returns list of uint16 arrays"""
        out = []
        for e in self.tk.encode_batch(texts, add_special_tokens=False):
            ids = np.asarray(e.ids, dtype=np.int64)
            m = self.lut[np.minimum(ids, len(self.lut) - 1)]
            m[ids >= len(self.lut)] = -1
            out.append(m[m >= 0].astype(np.uint16))
        return out

    def plain(self, text, strict=True):
        out = []
        for o in self.tk.encode(text, add_special_tokens=False).ids:
            m = self.o2n.get(o)
            if m is None:
                if strict: raise OOV(text[:40])
                continue
            out.append(m)
        return out

    def span_text(self, text, strict=True):
        """inside a machine span: digits one per token, everything else via tokenizer"""
        out = []
        for part in re.split(r"(\d+)", text):
            if not part: continue
            if part.isdigit(): out += [self.digit[c] for c in part]
            else: out += self.plain(part, strict)
        return out

    def enc(self, text, strict=True):
        out = []; in_span = False
        for part in TAG_RE.split(text):
            if not part: continue
            if part in TAG2SYM:
                s = TAG2SYM[part]; out.append(SP[s])
                if s in SPAN_OPEN: in_span = True
                if s in SPAN_CLOSE: in_span = False
            elif part == "</FRAME>":
                out.append(SP["cclose"])
            elif FRAME_RE.fullmatch(part):
                out += [SP["copen"]] + self.plain(f"pos={FRAME_RE.fullmatch(part).group(1)}\n", strict)
            else:
                out += self.span_text(part, strict) if in_span else self.plain(part, strict)
        return out

    def turns(self, conv, chunks=(), placement="hot", strict=True):
        """conv: list of {u, t, a}; chunks: [(pos, text)] framed into turn 0. Returns (ids, cold_upto)."""
        seq = [SP["bos"]]; cold_upto = 0
        for i, turn in enumerate(conv):
            seq += [SP["sot"]] + self.plain("user\n")
            if i == 0 and chunks:
                for p, ct in chunks:
                    seq += [SP["copen"]] + self.plain(f"pos={p}\n{ct}", strict) + [SP["cclose"]]
                if placement == "cold": cold_upto = len(seq)
                seq += self.enc("\n" + turn["u"], strict)
            else:
                seq += self.enc(turn["u"], strict)
            seq += [SP["eot"], SP["sot"]] + self.plain("model\n")
            if turn.get("t"): seq += [SP["think"]] + self.enc(turn["t"], strict) + [SP["endthink"]]
            a = turn.get("a", "")
            if a == "__ABSTAIN__":
                seq += [SP["sol"], SP["abstain"]] + self.plain("the evidence conflicts") + [SP["endsol"]]
            elif a:
                seq += [SP["sol"]] + self.enc(str(a), strict) + [SP["endsol"]]
            seq.append(SP["eot"])
        return seq, cold_upto

    # ---- batched path (identical output, one tokenizer call per conversation) ----
    def _pieces_enc(self, text, out, strict):
        """like enc(): push ints or ("P", text) / ("D", digits) placeholders into out"""
        in_span = False
        for part in TAG_RE.split(text):
            if not part: continue
            if part in TAG2SYM:
                sname = TAG2SYM[part]; out.append(SP[sname])
                if sname in SPAN_OPEN: in_span = True
                if sname in SPAN_CLOSE: in_span = False
            elif part == "</FRAME>": out.append(SP["cclose"])
            elif FRAME_RE.fullmatch(part):
                out.append(SP["copen"]); out.append(("P", f"pos={FRAME_RE.fullmatch(part).group(1)}\n"))
            elif in_span:
                for q in re.split(r"(\d+)", part):
                    if not q: continue
                    if q.isdigit(): out.extend(self.digit[c] for c in q)
                    else: out.append(("P", q))
            else: out.append(("P", part))

    def turns_batch(self, conv, chunks=(), placement="hot", strict=True):
        out = [SP["bos"]]; cold_upto = 0; cold_marker = None
        for i, turn in enumerate(conv):
            out.append(SP["sot"]); out.append(("P", "user\n"))
            if i == 0 and chunks:
                for p, ct in chunks: out.append(SP["copen"]); out.append(("P", f"pos={p}\n{ct}")); out.append(SP["cclose"])
                if placement == "cold": cold_marker = len(out)
                self._pieces_enc("\n" + turn["u"], out, strict)
            else: self._pieces_enc(turn["u"], out, strict)
            out.append(SP["eot"]); out.append(SP["sot"]); out.append(("P", "model\n"))
            if turn.get("t"): out.append(SP["think"]); self._pieces_enc(turn["t"], out, strict); out.append(SP["endthink"])
            a = turn.get("a", "")
            if a == "__ABSTAIN__": out.append(SP["sol"]); out.append(SP["abstain"]); out.append(("P", "the evidence conflicts")); out.append(SP["endsol"])
            elif a: out.append(SP["sol"]); self._pieces_enc(str(a), out, strict); out.append(SP["endsol"])
            out.append(SP["eot"])
        texts = [x[1] for x in out if isinstance(x, tuple)]
        encs = self.tk.encode_batch(texts, add_special_tokens=False) if texts else []
        seq = []; k = 0
        for j, x in enumerate(out):
            if cold_marker is not None and j == cold_marker: cold_upto = len(seq)
            if isinstance(x, tuple):
                ids = np.asarray(encs[k].ids, dtype=np.int64); k += 1
                m = self.lut[np.minimum(ids, len(self.lut) - 1)]; m[ids >= len(self.lut)] = -1
                if (m < 0).any():
                    if strict: raise OOV(x[1][:40])
                    m = m[m >= 0]
                seq.extend(int(v) for v in m)
            else: seq.append(x)
        if cold_marker is not None and cold_marker == len(out): cold_upto = len(seq)
        return seq, cold_upto

    def dec(self, ids):
        inv = {v: k for k, v in SP.items()}; out = []; buf = []
        def flush():
            if buf: out.append(self.tk.decode([int(self.n2o[i - OFF]) for i in buf])); buf.clear()
        for i in ids:
            if i < OFF: flush(); out.append(f"[{inv.get(i, i)}]")
            else: buf.append(i)
        flush(); return "".join(out)


ENC = None
def get():
    global ENC
    if ENC is None: ENC = Encoder()
    return ENC


if __name__ == "__main__":
    e = get()
    t = "<NEED>count of Vault-528.<QUOTE><FRAME pos=4410>Audit line: Vault-528 count 1234.</FRAME> <CALC>1234+56<EQ>1290<ECALC> total 1290"
    ids = e.enc(t)
    print(ids[:12], "...", len(ids), "tokens")
    print(e.dec(ids))
    # digit rule: inside the span every digit is one token; outside, '1290' is the tokenizer's token(s)
    inside = e.enc("<CALC>1234<ECALC>"); outside = e.plain("1234")
    print("in-span 1234 ->", inside, "| plain 1234 ->", outside)
    assert inside[1:-1] == [e.digit[c] for c in "1234"] and len(outside) < 4
    seq, cu = e.turns([{"u": "What is the count of Vault-528?", "t": "<NEED>count of Vault-528.", "a": "1234"}],
                      chunks=[(4410, "Audit line: Vault-528 count 1234.")], placement="cold")
    print("turn:", e.dec(seq)[:160].replace(chr(10), "|"), "| cold_upto", cu, "| ends with eot:", seq[-1] == SP["eot"])
    import random
    rng = random.Random(1); bad = 0
    for _ in range(300):
        conv = [{"u": f"What is the count of Vault-{rng.randint(100,999)}?", "t": f"<NEED>count of X.\n<FRAME pos={rng.randint(1,99999)}>Audit line: X count {rng.randint(1,99999)}.</FRAME>\n<QUOTE>pos=4: t\n<CALC>{rng.randint(1,9999)}+{rng.randint(1,999)}<EQ>{rng.randint(1,99999)}<ECALC> total", "a": str(rng.randint(1, 99999))}]
        ch = [(rng.randint(1, 99999), f"Registry entry: Dock-{rng.randint(100,999)} weight in kg recorded as {rng.randint(1,9999)}.") for _ in range(rng.randint(0, 6))]
        pl = rng.choice(["hot", "cold"])
        a = e.turns(conv, chunks=ch, placement=pl); b = e.turns_batch(conv, chunks=ch, placement=pl)
        if a != b: bad += 1
    print("turns_batch identical on 300 random convs:", bad == 0, "| mismatches", bad)
    print("ENC_V2_OK")
