"""A trained checkpoint (.pt) -> a folder of kernel blobs, the first half of making a container.

    python runtime/explode50r.py --ckpt tuned.pt --data . --out cbin
    cp deployment/ident.bin deployment/fold.bin deployment/stop.bin cbin/
    python runtime/mkshdw.py --dir cbin --out tuned.shdw --skip-f32

--data is the folder holding tables/ and unigram/ (this repository's root). The folder also gets the container's
self-test prompt and its reference ids, computed here from the checkpoint, so the kernel can check itself on the new file
(GOLDEN 8/8 means the kernel reproduces the checkpoint token for token).
"""
import argparse, json, os, sys, struct as st
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "tokenizer")): sys.path.insert(0, p)
from explode50p import pack2
from model50r import ShadowR
from enc_v2 import get, SP


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ckpt", required=True); ap.add_argument("--data", default=os.path.join(HERE, "..")); ap.add_argument("--out", default="cbin")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)["model"]
    def w_raw(name, t):
        arr = np.ascontiguousarray(t.float().numpy(), dtype=np.float32); arr.tofile(f"{a.out}/{name}.bin")
        if name == "wout": arr.astype(np.float16).tofile(f"{a.out}/{name}_f16.bin")   # half-precision readout matrix for the release pack (-0.9 MB); WIN stays fp32 (fp16 there flips cold answers)
    rt = {"n": 0, "ok": 0, "maxerr": 0.0}
    def w_tern(name, t):
        packed, alpha = pack2(t.float()); packed.tofile(f"{a.out}/{name}_q2.bin"); alpha.tofile(f"{a.out}/{name}_alpha.bin")
        # ROUND-TRIP (250M law: export must be bit-exact): unpack the codes and rebuild the weight the kernel will use;
        # it must equal the trainer's ternary(w) values exactly (same alpha, same {-1,0,+1} codes).
        from model50 import ternary
        o, i = t.shape; c = np.unpackbits(packed[:, None], axis=1)  # not used; explicit 2-bit unpack below
        f4 = np.stack([(packed >> 0) & 3, (packed >> 2) & 3, (packed >> 4) & 3, (packed >> 6) & 3], axis=1).reshape(-1)[: o * i].astype(np.float32) - 1.0
        deq = f4.reshape(o, i) * alpha[:, None]
        ref = ternary(t.float()).detach().cpu().numpy()
        err = float(np.abs(deq - ref).max()); rt["n"] += 1; rt["ok"] += (err == 0.0); rt["maxerr"] = max(rt["maxerr"], err)
    w_raw("win", sd["win.weight"]); w_raw("wout", sd["wout.weight"]); w_raw("nf", sd["nf.weight"])
    # cold-tier codec statistics (FingerprintKV1 per block: k1, k2, v), for the kernel's cold archive path (v3): (NKV, HD) floats each
    for l in range(6):
        for cname, tag in (("k1codec", "k1c"), ("k2codec", "k2c"), ("vcodec", "vc")):
            for f in ("sign", "mu", "ctv", "low", "high"): w_raw(f"b{l}_{tag}_{f}", sd[f"blocks.{l}.{cname}.{f}"])
    ub = np.load(f"{a.data}/unigram/unigram_bias_main.npy").astype(np.float32); ub.tofile(f"{a.out}/ubias.bin")
    for l in range(6):
        p = f"blocks.{l}."
        for nm in ("n1", "n2", "qn", "kn"): w_raw(f"b{l}_{nm}", sd[p + nm + ".weight"])
        w_raw(f"b{l}_lam", sd[p + "lam"]); w_raw(f"b{l}_gate", sd[p + "gate"])
        for nm in ("wq", "wk", "wv", "wo", "w1", "w2"): w_tern(f"b{l}_{nm}", sd[p + nm + ".w"])
    fp = np.load(f"{a.data}/tables/table_v2_packed.npy"); fp.tofile(f"{a.out}/table_packed.bin")
    E = get(); OFF = json.load(open(f"{a.data}/tables/symbols_v2.json"))["table_offset"]
    V = fp.shape[0]                                                   # rows in the table: 65,280 shipped, more when extended
    with open(f"{a.out}/vocab.bin", "wb") as f:
        f.write(st.pack("<I", V))
        for i in range(V):
            s = E.tk.decode([int(E.n2o[i - OFF])]).encode("utf-8")[:65535] if i >= OFF else f"<{i}>".encode()
            f.write(st.pack("<H", len(s))); f.write(s)
    # golden: greedy ids from the torch model (lane attached: same forced digits the kernel forces natively)
    m = ShadowR(fp, ub); m.load_state_dict({k: v for k, v in sd.items() if k not in ("C", "ubias")}, strict=False); m.eval()
    try: m.attach_lane(f"{a.data}/tables"); lane = True                      # the circuits' construction code is not in the public kit
    except ImportError: lane = False
    def P(u, chunks=None):
        ids, _ = E.turns([{"u": u, "a": ""}], chunks=chunks or [], strict=False); return ids[:ids.index(SP["eot"]) + 1] + [SP["sot"]] + E.plain("model\n")
    ids = P("What is 47 + 38?" if lane else "What is the capital of Japan?"); seq = list(ids); outs = []   # without the lane the self-test is a plain prompt, every position unforced
    with torch.no_grad():
        for _ in range(12 if lane else 16):
            x = torch.tensor([seq]); h, _, _ = m.hidden(x); t = int((m.logits_forced(h[:, -1:], x) if lane else m.logits(h[:, -1:]))[0, -1].argmax()); outs.append(t); seq.append(t)
            if t in (SP["eot"], SP["eos"], 0): break
    json.dump({"prompt": ids, "golden": outs}, open(f"{a.out}/golden.json", "w"))
    np.array(ids, dtype=np.int32).tofile(f"{a.out}/test_prompt.bin"); np.array(outs, dtype=np.int32).tofile(f"{a.out}/golden_ids.bin")
    # timing prompts per class
    recs = [(4410 + i, f"Audit line: Vault-{500 + i} count recorded as {1234 + 7 * i}.") for i in range(8)]
    long_ctx = " ".join(["The archive keeps every reading, note and transfer in order, so that any later question can be traced to its source."] * 24)
    prompts = {"p_chat": P("Do you like rain?"), "p_word": P("A crate holds 156 apples and another holds 287. If 40 are sold, how many remain?"),
               "p_long": P(long_ctx + " What does the archive keep?"), "p_fetch": P("What is the count of Vault-503?", recs)}
    for k, v in prompts.items(): np.array(v, dtype=np.int32).tofile(f"{a.out}/{k}.bin")
    print(f"ROUNDTRIP {rt['ok']}/{rt['n']} ternary tensors bit-exact (max err {rt['maxerr']:.3e})")
    print("EXPLODE50R_DONE golden:", outs, {k: len(v) for k, v in prompts.items()}, flush=True)


if __name__ == "__main__":
    main()
