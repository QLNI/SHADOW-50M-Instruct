"""SHADOW's index against BGE-M3 on the same 100M-token archive: build cost, footprint, query cost."""
import os, sys, time, json, subprocess
import numpy as np
sys.path.insert(0, "runtime"); sys.path.insert(0, "corpus"); sys.path.insert(0, "tokenizer")
from enc_v2 import get, SP

ARCH = "/root/arch1e8"
E = get()
tok = np.fromfile(os.path.join(ARCH, "tokens.bin"), dtype=np.int32)
opens = np.flatnonzero(tok == SP["copen"]); closes = np.flatnonzero(tok == SP["cclose"])
NREC = len(opens); NTOK = len(tok)
print(f"archive: {NTOK:,} tokens, {NREC:,} records")

# ---- SHADOW: build the index from scratch, on CPU, timed
idx = "/root/bench_index.bin"
if os.path.exists(idx): os.remove(idx)
t0 = time.time()
subprocess.run(["./deployment/bin/linux/shadow_index", "build", os.path.join(ARCH, "tokens.bin"),
                "deployment/fold.bin", idx], check=True, capture_output=True)
shadow_build = time.time() - t0
shadow_disk = os.path.getsize(idx)
print(f"SHADOW index: built in {shadow_build:.1f} s on CPU, {shadow_disk/1e9:.2f} GB on disk")

# ---- the same records as text, for BGE-M3
n_sample = 2000
texts = []
for i in range(0, NREC, max(1, NREC // n_sample)):
    if len(texts) >= n_sample: break
    s, e = int(opens[i]), int(closes[i])
    texts.append(E.dec([int(t) for t in tok[s + 1:e] if t >= 32]).split("\n", 1)[-1])
print(f"sampled {len(texts)} record texts, mean {np.mean([len(t.split()) for t in texts]):.1f} words")

# ---- BGE-M3 on the GPU
import torch
from sentence_transformers import SentenceTransformer
t0 = time.time()
m = SentenceTransformer("BAAI/bge-m3", device="cuda")
load_s = time.time() - t0
torch.cuda.reset_peak_memory_stats()
m.encode(texts[:128], batch_size=64, show_progress_bar=False)      # warm
torch.cuda.synchronize(); t0 = time.time()
emb = m.encode(texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True)
torch.cuda.synchronize(); enc_s = time.time() - t0
vram = torch.cuda.max_memory_allocated()
rate = len(texts) / enc_s
dim = emb.shape[1]
print(f"BGE-M3: loaded in {load_s:.0f} s, {rate:.0f} records/s on the 3090, dim {dim}, peak VRAM {vram/1e9:.2f} GB")

out = dict(tokens=int(NTOK), records=int(NREC),
           shadow_build_s=round(shadow_build, 1), shadow_index_bytes=int(shadow_disk),
           bge_rate=round(rate, 1), bge_dim=int(dim), bge_vram_bytes=int(vram),
           bge_full_build_s=round(NREC / rate, 0), bge_fp16_bytes=int(NREC * dim * 2))
json.dump(out, open("/root/bench_embed.json", "w"), indent=1)
print(json.dumps(out, indent=1))
