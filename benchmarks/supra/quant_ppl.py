"""Supra-50M-Reasoning under weight-only quantisation, WikiText-2 raw test, 1024 windows, token perplexity.
bf16 (as shipped), int8 per-output-channel, int4 group-64, ternary (absmean, BitNet style) applied to every Linear
(embedding left alone, as llama.cpp does). Same scoring as ppl_supra.py."""
import math, json, copy
import torch, torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import hf_hub_download
import pyarrow.parquet as pq

from huggingface_hub import snapshot_download
S = snapshot_download("SupraLabs/Supra-50M-Reasoning")
dev = "cuda"
tok = AutoTokenizer.from_pretrained(S)
base = AutoModelForCausalLM.from_pretrained(S, dtype=torch.float32).to(dev).eval()
rows = pq.read_table(hf_hub_download("Salesforce/wikitext", "wikitext-2-raw-v1/test-00000-of-00001.parquet", repo_type="dataset")).to_pylist()
ids = tok("".join(r["text"] for r in rows), add_special_tokens=False).input_ids
W = 1024

@torch.no_grad()
def ppl(m):
    nll = 0.0; n = 0
    for i in range(0, len(ids) - 1, W - 1):
        chunk = [tok.bos_token_id] + ids[i:i + W - 1]
        x = torch.tensor([chunk[:-1]], device=dev); y = torch.tensor([chunk[1:]], device=dev)
        nll += float(F.cross_entropy(m(x).logits[0].float(), y[0], reduction="sum")); n += y.shape[1]
    return round(math.exp(nll / n), 2)

def q_int8(w):
    s = w.abs().amax(dim=1, keepdim=True) / 127.0
    return (w / s).round().clamp(-127, 127) * s

def q_int4_g64(w):
    o, i = w.shape; g = w.reshape(o, i // 64, 64)
    s = g.abs().amax(dim=2, keepdim=True) / 7.0
    return ((g / s).round().clamp(-8, 7) * s).reshape(o, i)

def q_ternary(w):
    s = w.abs().mean()
    return (w / s).round().clamp(-1, 1) * s

def quantised(fn):
    m = copy.deepcopy(base)
    for name, mod in m.named_modules():
        if isinstance(mod, torch.nn.Linear) and mod.weight.shape[1] % 64 == 0:
            mod.weight.data = fn(mod.weight.data)
    return m

nlin = sum(p.numel() for n, p in base.named_parameters() if "embed" not in n)
nemb = sum(p.numel() for n, p in base.named_parameters() if "embed" in n)
out = {"linear_params": nlin, "embed_params": nemb}
for tag, fn in [("bf16 as shipped", None), ("int8 per channel", q_int8), ("int4 group 64", q_int4_g64), ("ternary absmean", q_ternary)]:
    m = base if fn is None else quantised(fn)
    out[tag] = ppl(m); print(tag, out[tag], flush=True)
json.dump(out, open("quant_ppl.json", "w"), indent=1); print(json.dumps(out))
