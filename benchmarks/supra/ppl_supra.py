"""WikiText-2 raw test perplexity for Supra-50M-Reasoning: non-overlapping windows of 1024 (its max position),
token perplexity on its own tokenizer, and word perplexity (exp of total nll over whitespace words) which is
comparable across tokenizers."""
import math, sys, json
import torch, torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import hf_hub_download
import pyarrow.parquet as pq

from huggingface_hub import snapshot_download
S = snapshot_download("SupraLabs/Supra-50M-Reasoning")
dev = "cuda"
tok = AutoTokenizer.from_pretrained(S)
m = AutoModelForCausalLM.from_pretrained(S, dtype=torch.float32).to(dev).eval()
rows = pq.read_table(hf_hub_download("Salesforce/wikitext", "wikitext-2-raw-v1/test-00000-of-00001.parquet", repo_type="dataset")).to_pylist()
text = "".join(r["text"] for r in rows)
n_words = len(text.split())
ids = tok(text, add_special_tokens=False).input_ids
W = 1024; nll = 0.0; n = 0
with torch.no_grad():
    for i in range(0, len(ids) - 1, W - 1):
        chunk = [tok.bos_token_id] + ids[i:i + W - 1]
        x = torch.tensor([chunk[:-1]], device=dev); y = torch.tensor([chunk[1:]], device=dev)
        lg = m(x).logits[0].float()
        nll += float(F.cross_entropy(lg, y[0], reduction="sum")); n += y.shape[1]
out = dict(tokens=n, words=n_words, chars=len(text), token_ppl=round(math.exp(nll / n), 2), word_ppl=round(math.exp(nll / n_words), 2), nll=nll)
print(json.dumps(out)); json.dump(out, open("ppl_supra.json", "w"))
