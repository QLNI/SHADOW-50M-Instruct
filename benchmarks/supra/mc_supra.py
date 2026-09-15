"""Multiple choice for Supra-50M-Reasoning with the same protocol as runtime/bench_std.py:
same parquet files, same 400-item sample (random.Random(0)), continuation log-likelihood,
acc and per-character length-normalised acc."""
import random, json, sys
import numpy as np, torch, torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import hf_hub_download
import pyarrow.parquet as pq

from huggingface_hub import snapshot_download
S = snapshot_download("SupraLabs/Supra-50M-Reasoning")
dev = "cuda"
tok = AutoTokenizer.from_pretrained(S)
m = AutoModelForCausalLM.from_pretrained(S, dtype=torch.float32).to(dev).eval()
BOS = tok.bos_token_id

def parquet(repo, path):
    return pq.read_table(hf_hub_download(repo, path, repo_type="dataset")).to_pylist()

def enc(t): return tok(t, add_special_tokens=False).input_ids

@torch.no_grad()
def cont_logprob(ctx_ids, cont_ids):
    ids = [BOS] + ctx_ids + cont_ids
    x = torch.tensor([ids[:-1]], device=dev); y = torch.tensor([ids[1:]], device=dev)
    lg = m(x).logits[0].float(); lp = F.log_softmax(lg, -1)
    s = len(ctx_ids)  # first continuation target index in y (BOS shifts by one)
    tok_lp = lp[torch.arange(s, len(ids) - 1, device=dev), y[0, s:]]
    return float(tok_lp.sum())

def mc_task(items, n=400):
    rng = random.Random(0); items = items if len(items) <= n else rng.sample(items, n)
    acc = accn = 0
    for ctx, choices, gold in items:
        c = enc(ctx); sc = []; scn = []
        for ch in choices:
            lp = cont_logprob(c, enc(ch)); sc.append(lp); scn.append(lp / max(1, len(ch)))
        acc += int(np.argmax(sc) == gold); accn += int(np.argmax(scn) == gold)
    return acc / len(items), accn / len(items), len(items)

def load_arc():
    rows = parquet("allenai/ai2_arc", "ARC-Easy/test-00000-of-00001.parquet"); out = []
    for r in rows:
        labels = list(r["choices"]["label"]); texts = list(r["choices"]["text"])
        if r["answerKey"] not in labels: continue
        out.append((f"Question: {r['question']}\nAnswer:", [" " + t for t in texts], labels.index(r["answerKey"])))
    return out

def load_piqa():
    rows = parquet("baber/piqa", "piqa_validation.parquet")
    return [(f"Question: {r['goal']}\nAnswer:", [" " + r["sol1"], " " + r["sol2"]], int(r["label"])) for r in rows]

def load_hella():
    rows = parquet("Rowan/hellaswag", "data/validation-00000-of-00001.parquet")
    return [(r["ctx"], [" " + e for e in list(r["endings"])], int(r["label"])) for r in rows]

def load_wino():
    rows = parquet("allenai/winogrande", "winogrande_xl/validation-00000-of-00001.parquet"); out = []
    for r in rows:
        s = r["sentence"]; i = s.index("_"); h = s[:i]; t = s[i + 1:]
        out.append(("", [h + r["option1"] + t, h + r["option2"] + t], int(r["answer"]) - 1))
    return out

res = {}
for name, f in [("ARC-Easy", load_arc), ("PIQA", load_piqa), ("HellaSwag", load_hella), ("WinoGrande", load_wino)]:
    a, an, n = mc_task(f()); res[name] = (a, an, n); print(name, "acc", round(a, 3), "acc_norm", round(an, 3), n, flush=True)
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "mc_supra.json", "w"), indent=1)
