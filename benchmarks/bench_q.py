"""Query side: SHADOW's index on CPU against BGE-M3 on the 3090, same 4.1M-record archive."""
import os, sys, time, json, subprocess, resource
import numpy as np
ARCH="/root/arch1e8"

# ---- SHADOW: index lookup on CPU, 2000 keys, measured by the index tool itself
t0=time.time()
r=subprocess.run(["./deployment/bin/linux/shadow_index","query",os.path.join(ARCH,"tokens.bin"),
                  "deployment/fold.bin","/root/bench_index.bin",os.path.join(ARCH,"keys.txt")],
                 capture_output=True, text=True)
wall=time.time()-t0
print("shadow_index query:", (r.stdout or r.stderr).strip().splitlines()[-1][:160])
rss_shadow = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024

# ---- BGE-M3: encode one query, then search the vectors
import torch
from sentence_transformers import SentenceTransformer
m=SentenceTransformer("BAAI/bge-m3", device="cuda")
q=["what is the count of Vault-418"]
for _ in range(3): m.encode(q, show_progress_bar=False)
torch.cuda.synchronize(); t0=time.time()
for _ in range(20): qe=m.encode(q, show_progress_bar=False, convert_to_numpy=True)
torch.cuda.synchronize(); enc_ms=(time.time()-t0)/20*1000

N=1_000_000; D=1024
db=torch.randn(N, D, device="cuda", dtype=torch.float16); db/=db.norm(dim=1,keepdim=True)
qv=torch.randn(1, D, device="cuda", dtype=torch.float16); qv/=qv.norm()
for _ in range(3): (db@qv.T).squeeze().topk(10)
torch.cuda.synchronize(); t0=time.time()
for _ in range(20): (db@qv.T).squeeze().topk(10)
torch.cuda.synchronize(); search_ms=(time.time()-t0)/20*1000
NREC=4_125_062
out=dict(shadow_query_wall_s=round(wall,2), shadow_rss_bytes=int(rss_shadow),
         bge_encode_ms=round(enc_ms,2), bge_search_1M_ms=round(search_ms,3),
         bge_search_full_ms=round(search_ms*NREC/N,3),
         bge_vectors_vram_gb=round(NREC*D*2/1e9,2))
json.dump(out, open("/root/bench_q.json","w"), indent=1)
print(json.dumps(out, indent=1))
