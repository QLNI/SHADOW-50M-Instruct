# The trail, warmed on the wrong record

Asked by CarefulHamster7184 on r/MachineLearning, 2026-09-16: if the first retrieval is wrong and the model still
quotes it, does the +1 strengthen the wrong link until the error is self-confirming? Are the weights capped, decayed,
or corrected? Cold against correctly warmed against incorrectly warmed, with competing records under the same key.

`ablate.py` builds an archive of 12 keys with three records each (quantity, bin, supplier), asks for the quantity of
every key, one fresh kernel process per question, and counts answers that quote the quantity record. Warming the
wrong record means setting every link that points at the key's bin record to weight 5 by editing index.bin directly.

| condition | v1.1 kernel | fixed kernel |
|---|---|---|
| cold | 12/12 | 12/12 |
| correctly warmed (asked 3 times first) | 12/12 | 12/12 |
| wrongly warmed (bin links set to 5) | 0/12 | 12/12 |
| then the right question asked 5 more times | 0/12 | 12/12 |
| wrongly warmed, trail disabled (AX_TRAIL=0) | 12/12 | 12/12 |

Why it failed: a candidate with weight 2 or more that was alone at the top skipped the word-overlap scan, and the
reading head accepted the sibling because the key words matched, so each copy added another +1 to the wrong link.
Why it is fixed: a warmed link now ranks first only among the records with the best word overlap, and on every
confirmed copy the rival links in the same bucket lose 1. On the fixed kernel the wrong link in the contested bucket
falls from 5 to 0 over five correct answers while the right link rises from 0 to 5.

What did not change: every cold measurement, because with all weights at zero the two kernels score identically;
30 of 30 one-shot prompts and 37 of 37 published samples are token-identical; GOLDEN 8 of 8 on Windows, Linux and the
browser build. The warm MS MARCO top-1 of 0.743 in BENCHMARKS.md was measured on the v1.1 kernel and is not
re-measured here.

Results: `ablate.json` (v1.1 kernel), `ablate_fixed.json` (fixed kernel). Run: `python benchmarks/trail_ablation/ablate.py`
from the repository root; set `SHADOW_KERNEL` to test another kernel binary.
