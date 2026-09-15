# Receipts: every number in the README and BENCHMARKS.md, and where it comes from

Rule of this repository: a number is published only with a file behind it. "Re-run" means it was produced on 2026-09-10
with the files in this repository (kernel v5, the shipped container); "ledger" means it comes from the project's
measurement ledger and was not re-run on that day.

| claim | value | source | status |
|---|---|---|---|
| parameters | 44,058,965 | model definition | ledger |
| pretraining tokens | 45.0B | run log, run v3 complete at 45,000M | ledger |
| fine-tuning tokens | 0.16B | run log, SFT v2 (160M tokens) | ledger |
| container size | 19,799,680 bytes (v1.1.1; v1.0 was 19,099,776) | `deployment/shadow50_instruct.shdw` | re-run (file) |
| executable size | 159 KB Windows (159,232 bytes), 1.1 MB Linux static (1,125,120 bytes), both stripped | `deployment/bin/` | re-run (file) |
| golden parity 8/8 | kernel output = torch reference on the self-test prompt | run the kernel with no arguments but the container | re-run |
| chat 2,000 tok/s, word problem 2,020, 868-ctx 1,250, 3k cold sparse 917; RSS 38.6-44.3 MB | laptop, 8 threads | `reports/DEMO.md` and `SAMPLES.md` | re-run |
| WordSim-353 Spearman 0.594 for the frozen vocabulary codes, −0.057 random (1.1 table; 0.595 and −0.052 on the 1.0 table) | 317 single-token pairs | `python benchmarks/embedding_bench.py` | re-run |
| perplexity by window: held-out slice 140.0 / 131.3 / 132.1, WikiText-2 186.1 / 163.4 / 152.7 | ~295k tokens each, windows 1,024 / 2,048 / 8,192 | `eval_wiki2` on `shadow50_instruct.pt`, sources `wikiho` and `wiki2`, `--T` | re-run |
| weekday and calendar exact for any year 1900-2100, leap years included | kernel 7/7 and the weights path 6/6 on dated questions; 41 of 42 circuit prompts byte-identical to the previous kernel, the one change being the fix | `TOOLTEST="dow:Feb29,2024" shadow50 <container>` | re-run |
| index scales linearly: 21.6 to 22.0 B/token and 14-16 M tok/s from 12.5M to 100M tokens | four builds | `benchmarks/scale.py` | re-run |
| index build 7.4 s CPU vs BGE-M3 65 min GPU; 2.20 GB vs 8.45 GB; 1.4 us vs 26.6 ms per query | 4,125,062 records, 100,009,058 tokens | `bench_embed.py` and `bench_q.py` on one RTX 3090 pod | re-run |
| 37 sample transcripts, tok/s and token count per prompt | see file | `SAMPLES.md` (v1.1 container, 2026-09-13) | re-run |
| v1.1 extension: 34/34 published answers unchanged; recall of lowercase new-piece names 0/60 -> 46/60 and 49/60; every arithmetic, tool, program and conversation family within one item of v1.0 | tables | `reports/EXTENSION_2026-09-13.md` | re-run (2026-09-13) |
| 17/17 arithmetic, tool and program prompts exact | items 17-33 of the suite | `SAMPLES.md` | re-run |
| benchmarks n=400 base / SFT (ARC-E, PIQA, HellaSwag, WinoGrande) | table | bench log `bench_base_vs_sft_v2.log` (project ledger, `sft/v2/reports/`) | ledger |
| archive at 100k / 1M / 50M / 100M: index build, sizes, lookup us, fetch ms, top-1, decode, RAM | table | `reports/DEMO.md` section 2 | re-run |
| CPU store build 0.43 ms/token | | `reports/DEMO.md` section 2 | re-run |
| two-hop 20/20, three-hop 9/20 from disk | | `reports/DEMO.md` section 2 | re-run |
| 50 conversations, 950 turns, 434/550 scored turns correct | per-turn table and full transcripts, on the 1.0 container (same weights) | `reports/CONVERSATIONS_50.md` | re-run (2026-09-12, v1.0) |
| attention keys cannot search the archive (recall 0.000 at 1M) | | project ledger | re-run |
| retrieval vs BGE-M3 on 100k MS MARCO passages, top-1 0.571 cold, 0.743 warm | table | project ledger report; harness on request | ledger |
| browser 450 to 530 tok/s (7 threads), 175 to 195 (1 thread), GOLDEN 8/8 in the tab | Chrome, this laptop, standalone questions | `web/README.md` | re-run (2026-09-12) |
| memory-from-disk demo of 2026-09-09 (negation dropped) | | `reports/MEMORY_FROM_DISK_2026-09-09.md` | ledger |
| weights on disk of GPT-2 and SmolLM2 | 548 MB, 269 MB | the official repositories' main weight file, as published | public |

Not claimed anywhere in this repository, on purpose: that attention searches the archive (it does not; the index does);
"zero-shot" benchmark scores (the corpus held the public train splits); creative writing or code generation for a user.

Conversational memory IS claimed, and only in the form measured: with `--remember N` set, facts stated in a
conversation are recalled later in that same conversation. It is off by default and costs single-turn exactness
(16/16 without, 14/16 with). It is the window, not the archive: a statement still does not trigger an archive lookup.
