"""ShadowP ckpt -> cbin2/ for shadow50v2.c (old proven kernel layout).
- ternary: codes (clamp(round(w/alpha))+1) in {0,1,2}, packed 4/byte
  (f4[0] | f4[1]<<2 | f4[2]<<4 | f4[3]<<6) exactly as export50.pack_ternary —
  matches tern_blk's shift-0/2/4/6 unpack and the XSUM (-sum(x)) correction.
- raws: fp32 .bin per tensor (n1,n2,qn,kn,gate,lam,nf,win,wout,ubias)
- vocab.bin: u32 V then per id u16 len + utf8 bytes
- golden.json: fixed prompt ids + reference next-ids from the torch model
  (frozen requant parity — the pack IS the deploy weights).
Run (pod): python explode50p.py --ckpt X.pt --out cbin2
"""
import argparse, json, os, sys
import numpy as np
import torch

sys.path.insert(0, "<path>")
sys.path.insert(0, "<path>")
from model50p import ShadowP


def pack2(w):
    alpha = w.abs().mean(dim=1, keepdim=True) + 1e-8
    q = (torch.clamp(torch.round(w / alpha), -1, 1) + 1).to(torch.uint8).numpy()
    flat = q.reshape(-1)
    pad = (-len(flat)) % 4
    if pad: flat = np.concatenate([flat, np.ones(pad, np.uint8)])   # pad code 1 == 0 weight
    f4 = flat.reshape(-1, 4)
    packed = (f4[:, 0] | (f4[:, 1] << 2) | (f4[:, 2] << 4) | (f4[:, 3] << 6)).astype(np.uint8)
    return packed, alpha.squeeze(1).float().numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--out", default="cbin2")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)["model"]

    def w_raw(name, t):
        np.ascontiguousarray(t.float().numpy(), dtype=np.float32).tofile(f"{a.out}/{name}.bin")

    def w_tern(name, t):
        packed, alpha = pack2(t.float())
        packed.tofile(f"{a.out}/{name}_q2.bin")
        alpha.tofile(f"{a.out}/{name}_alpha.bin")

    w_raw("win", sd["win.weight"]); w_raw("wout", sd["wout.weight"])
    w_raw("nf", sd["nf.weight"])
    ub = np.load("<path>").astype(np.float32)
    ub.tofile(f"{a.out}/ubias.bin")
    for l in range(6):
        p = f"blocks.{l}."
        for nm in ("n1", "n2", "qn", "kn"):
            w_raw(f"b{l}_{nm}", sd[p + nm + ".weight"])
        w_raw(f"b{l}_lam", sd[p + "lam"])
        w_raw(f"b{l}_gate", sd[p + "gate"])
        for nm in ("wq", "wk", "wv", "wo", "w1", "w2"):
            w_tern(f"b{l}_{nm}", sd[p + nm + ".w"])

    # vocab strings
    from pilot_stitch import get_enc
    tk, o2n = get_enc()
    n2o = {v: k for k, v in o2n.items()}
    import struct as st
    with open(f"{a.out}/vocab.bin", "wb") as f:
        f.write(st.pack("<I", 65280))
        for i in range(65280):
            s = tk.decode([n2o[i]]).encode("utf-8")[:65535] if i in n2o else (f"<{i}>".encode() if i < 16 else b"")
            f.write(st.pack("<H", len(s))); f.write(s)

    # golden: run frozen-requant torch model on fixed prompt, record greedy ids
    fp = np.load("<path>")
    m = ShadowP(fp, ub)
    m.load_state_dict(sd)
    m.eval(); m.grad_ckpt = False
    from pilot_stitch import SP, enc_plain
    ids = [SP["bos"], SP["sot"]] + enc_plain("user\nWhat is 47 + 38?") + [SP["eot"], SP["sot"]] + enc_plain("model\n")
    seq = list(ids)
    outs = []
    with torch.no_grad():
        for _ in range(10):
            lg = m(torch.tensor([seq]))[0, -1]
            t = int(lg.argmax()); outs.append(t); seq.append(t)
            if t in (4, 2, 0): break
    json.dump({"prompt": ids, "golden": outs}, open(f"{a.out}/golden.json", "w"))
    print("EXPLODE50P_DONE golden:", outs, flush=True)


if __name__ == "__main__":
    main()
