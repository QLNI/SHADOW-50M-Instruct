"""Fine-tune SHADOW 50M from the master weights.

    python finetune/train.py --ckpt shadow50_instruct.pt --rows rows.u16 --out tuned.pt --steps 2000

Rows are uint16; name the file .u32 and they are read as uint32 (an extended table has ids past 65,535).
--data names the folder that holds tables/ and unigram/ (the repository root by default).

The weighting is what makes this work, and it is not optional:

    0   on forced positions -- everything between [eq] and [ecalc], and between [run] and [evm]. A circuit writes
        those tokens. Training on them teaches the model to predict what it will be handed anyway, and it drifts
        toward answering from memory instead of opening a span.
    0   on record frames injected inside a think block. That text is runtime input, never model output.
    3   on [need] and [quote] lines, on [sol]..[endsol], and on the token that opens a span. This is the routing:
        WHEN to reach for a circuit or a record, and WHAT to answer. It is the whole job.
    1   everywhere else.

Keep some of what the model already does well in the mix -- chat, records, arithmetic -- or it forgets. A run that
is 100% one new shape will learn that shape and lose the rest.
"""
import argparse, os, sys, math, time
import numpy as np, torch, torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tokenizer"))
sys.path.insert(0, os.path.join(HERE, "..", "runtime"))
from enc_v2 import SP


def weights_for(row):
    """the rule above, as code. row: list[int] -> np.float32 weights over input positions."""
    n = len(row); w = np.ones(n, dtype=np.float32); a = np.asarray(row)

    def between(o, c):
        out = []
        for s in np.flatnonzero(a == o):
            e = s + 1
            while e < n and a[e] != c: e += 1
            out.append((int(s), int(e)))
        return out

    for o, c in ((SP["eq"], SP["ecalc"]), (SP["run"], SP["evm"])):
        for s, e in between(o, c): w[s:e] = 0.0                       # forced: the circuit writes these
    for ts in np.flatnonzero(a == SP["think"]):                       # injected frames inside think
        te = next((int(x) for x in np.flatnonzero(a == SP["endthink"]) if x > ts), n)
        for s, e in between(SP["copen"], SP["cclose"]):
            if ts < s < te: w[max(s - 1, 0):e + 1] = 0.0
    for s, e in between(SP["sol"], SP["endsol"]): w[s:e] = np.maximum(w[s:e], 3.0)
    for sym in (SP["need"], SP["quote"]):                             # the evidence lines
        for s in np.flatnonzero(a == sym):
            e = s + 1
            while e < n and a[e] != SP["sol"] and a[e] != SP["endthink"] and e - s < 64: e += 1
            w[s:e] = np.maximum(w[s:e], 3.0)
    for s in np.flatnonzero(a == SP["calc"]): w[max(int(s) - 1, 0)] = 3.0      # the decision to open a span
    return w


class LoRA(torch.nn.Module):
    """a low-rank path beside a frozen ternary projection: y = tern(W) x + B (A x) * alpha / r, on the same float input the kernel uses"""
    def __init__(self, base, r, alpha):
        super().__init__(); self.base = base; dout, din = base.w.shape
        self.A = torch.nn.Parameter(torch.randn(r, din) * 0.01); self.B = torch.nn.Parameter(torch.zeros(dout, r)); self.s = alpha / r
    def forward(self, x, prequant=False):
        return self.base(x, prequant) + F.linear(F.linear(x, self.A), self.B) * self.s


def write_kernel_adapter(m, a, path):
    """the kernel's adapter file: magic SLRA, rank, layers, target list; then per layer per target din, dout, A (r x din), B (dout x r) as float32, B carrying alpha / r"""
    targets = [x.strip() for x in a.lora_targets.split(",")]; order = ["wq", "wk", "wv", "wo", "w2"]
    with open(path, "wb") as f:
        f.write(b"SLRA"); f.write(np.array([a.lora, len(m.blocks), len(order)], dtype=np.int32).tobytes())
        for b in m.blocks:
            for nm in order:
                mod = getattr(b, nm); present = isinstance(mod, LoRA) and nm in targets
                if not present: f.write(np.array([0, 0], dtype=np.int32).tobytes()); continue
                A = mod.A.detach().float().cpu().numpy(); B = (mod.B.detach().float() * mod.s).cpu().numpy()
                f.write(np.array([A.shape[1], B.shape[0]], dtype=np.int32).tobytes()); f.write(np.ascontiguousarray(A).tobytes()); f.write(np.ascontiguousarray(B).tobytes())
    print("wrote kernel adapter", path, os.path.getsize(path), "bytes")


def rows_from(path):
    a = np.fromfile(path, dtype=np.uint32 if path.endswith(".u32") else np.uint16)   # .u32 when the table has more than 65,535 rows
    st = np.flatnonzero(a == SP["bos"])
    return [a[st[i]:(st[i + 1] if i + 1 < len(st) else len(a))].astype(np.int64).tolist() for i in range(len(st))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True); ap.add_argument("--rows", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=2000); ap.add_argument("--bs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-5); ap.add_argument("--T", type=int, default=512); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--data", default=os.path.join(HERE, ".."))
    ap.add_argument("--only", default=None, help="train only parameters whose name starts with one of these comma-separated prefixes (e.g. win,wout,nf: the readout, body untouched)")
    ap.add_argument("--lora", type=int, default=0, help="rank of a low-rank adapter on the body's projections; the ternary weights stay frozen and bit-identical")
    ap.add_argument("--lora-alpha", type=float, default=16.0); ap.add_argument("--lora-targets", default="wq,wk,wv,wo,w2", help="w1 is left out: the kernel fuses its SiLU")
    ap.add_argument("--lora-out", default=None, help="also write the adapter in the kernel's format (LORA=<file>)")
    a = ap.parse_args()
    from model50r import ShadowR
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    fp = np.load(os.path.join(a.data, "tables", "table_v2_packed.npy"))
    ub = np.load(os.path.join(a.data, "unigram", "unigram_bias_main.npy"))
    m = ShadowR(fp, ub).to(dev)
    sd = torch.load(a.ckpt, map_location=dev, weights_only=False)["model"]
    sd = {k: v for k, v in sd.items() if k not in ("C", "ubias")}        # the table and its prior come from --data, not the checkpoint
    m.load_state_dict(sd, strict=False)
    m.cold_quant = True; m.codec_frozen = True; m.train()
    rows = rows_from(a.rows); print(f"{len(rows)} rows on {dev}")
    params = list(m.parameters())
    if a.lora:
        for p_ in m.parameters(): p_.requires_grad_(False)
        targets = tuple(x.strip() for x in a.lora_targets.split(","))
        for b in m.blocks:
            for nm in targets: setattr(b, nm, LoRA(getattr(b, nm), a.lora, a.lora_alpha))
        m.to(dev); params = [p_ for n_, p_ in m.named_parameters() if p_.requires_grad]
        print(f"LoRA rank {a.lora} on {a.lora_targets}: {sum(p_.numel() for p_ in params):,} adapter parameters, base frozen")
    if a.only:
        pre = tuple(x.strip() for x in a.only.split(","))
        for n_, p_ in m.named_parameters(): p_.requires_grad_(n_.startswith(pre))
        params = [p_ for n_, p_ in m.named_parameters() if n_.startswith(pre)]; print(f"training only {a.only}: {sum(p_.numel() for p_ in params):,} parameters")
    opt = torch.optim.AdamW(params, lr=a.lr, betas=(0.9, 0.95), weight_decay=0.1)
    rng = np.random.default_rng(a.seed); t0 = time.time()
    for step in range(1, a.steps + 1):
        xs, ys, ws = [], [], []
        for _ in range(a.bs):
            r = rows[rng.integers(len(rows))][:a.T + 1]
            if len(r) < 8: continue
            w = weights_for(r)
            xs.append(r[:-1]); ys.append(r[1:]); ws.append(w[:len(r) - 1])
        if not xs: continue
        L = max(len(x) for x in xs)
        X = torch.zeros(len(xs), L, dtype=torch.long, device=dev)
        Y = torch.full((len(xs), L), -100, dtype=torch.long, device=dev)
        W = torch.zeros(len(xs), L, device=dev)
        for i, (x, y, w) in enumerate(zip(xs, ys, ws)):
            X[i, :len(x)] = torch.tensor(x, device=dev); Y[i, :len(y)] = torch.tensor(y, device=dev)
            W[i, :len(w)] = torch.tensor(w, device=dev)
        h, _, _ = m.hidden(X)
        z = m.logits(h).float()
        ls = F.cross_entropy(z.reshape(-1, z.shape[-1]), Y.reshape(-1), reduction="none", ignore_index=-100)
        loss = (ls * W.reshape(-1)).sum() / W.sum().clamp(min=1)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step()
        if step % 100 == 0 or step == 1:
            print(f"  step {step:5d}/{a.steps}  loss {loss.item():.4f}  {time.time()-t0:.0f}s", flush=True)
    if a.lora:
        ad = {n_: p_.detach().cpu() for n_, p_ in m.named_parameters() if p_.requires_grad}
        torch.save({"lora": ad, "rank": a.lora, "alpha": a.lora_alpha, "targets": a.lora_targets}, a.out); print("wrote adapter", a.out)
        if a.lora_out: write_kernel_adapter(m, a, a.lora_out)
        return
    torch.save({"model": m.state_dict()}, a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
