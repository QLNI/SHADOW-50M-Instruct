# SHADOW 50M Instruct: the numbers

Every table that used to sit on the front page, unchanged. Where each number comes from is in [RECEIPTS.md](RECEIPTS.md).
Back to the [README](README.md).

---

## Multiple choice

Standard multiple choice, 400 items each, raw accuracy / length-normalized, greedy scoring, base model and after
fine-tuning. The training corpus contained the public *train* splits of these benchmarks in chat form; the test items
were never seen.

| task | base | SHADOW 50M Instruct |
|---|---|---|
| ARC-Easy | 0.318 / 0.340 | 0.307 / 0.345 |
| PIQA | 0.555 / 0.517 | 0.570 / 0.568 |
| HellaSwag | 0.217 / 0.247 | 0.230 / 0.260 |
| WinoGrande | 0.465 / 0.468 | 0.475 / 0.480 |

These are reported for completeness. The model is not built for multiple-choice recall; it is built for the tables below.

## The vocabulary table has its own benchmark

Every token carries a fixed 512-bit code, and those codes are never trained.
[`benchmarks/embedding_bench.py`](benchmarks/embedding_bench.py) reads the table straight out of the shipped
container and scores it on human word-similarity ratings (WordSim-353, 317 single-token pairs), offline, using only
the files in this repository. Re-run on the 1.1 table (73,880 rows; the 1.0 table scored 0.595 on 318 pairs):

| codes | Spearman correlation with human ratings |
|---|---|
| the shipped vocabulary table | **0.594** |
| random 512-bit codes | −0.057 |

Classic 300-dimension float word vectors reach about 0.65 to 0.70 on the same test, using 19 times more bits per word.

## The archive, at four scales

Measured on one machine with the archive on disk, nothing loaded into memory: the token stream, the index and the
1-bit store are memory-mapped and a question faults in only the pages it touches. Fifty to a hundred lookup questions
per scale, one fresh process per question.

| archive | index build | index on disk | 1-bit K/V on disk | index lookup per key | fetch per answer | answer top-1 | decode | process RAM |
|---|---|---|---|---|---|---|---|---|
| 100k tokens | 0.00 s | 2 MB | 29 MB | 0.4 us | 0.03 ms | 0.75 | 2,044 tok/s | 28 MB |
| 1M | 0.03 s | 29 MB | 288 MB | 0.6 us | 0.03 ms | 0.83 | 2,043 | 28 MB |
| 50M | 2.6 s | 1.1 GB | 14.4 GB | 1.3 us | 0.03 ms | 0.76 | 2,028 | 28 MB |
| 100M | 5.3 s | 2.2 GB | 28.8 GB | 1.4 us | 0.03 ms | 0.84 | 1,994 | 28 MB |

Per token the archive costs 4 bytes of text, 22 bytes of index and 288 bytes of the model's 1-bit memory; the same
memory at 16-bit precision, as a normal model keeps it, would be 4,608 bytes. Building the 1-bit store is the one slow step: 0.43 ms per token
on a CPU (the kernel does it).

Chains of records, each hop a real lookup and fetch from disk (20 chains each, 100k tokens of other records around them):
two-hop **20/20**, three-hop **9/20**. A three-hop failure is almost always an early close: the first two quotes are
right, the model does not write the third `[need]` line, and states a number instead.

Facts told once at the start of a session and asked again when the session holds 100k, 1M, 50M and 100M tokens: the
same answers at every scale, the same 0.03 ms fetch, the same 28 MB. Nothing said early is ever lost; it is remembered,
not searched for in text. The transcripts, including the questions it gets
wrong, are in [reports/CONVERSATIONS_50.md](reports/CONVERSATIONS_50.md).

## Retrieval against BGE-M3

The same archive both ways: 100,009,058 tokens, 4,125,062 records. SHADOW builds its index on the CPU. BGE-M3 is a
568M-parameter embedding model, run on an RTX 3090 with fp16.

| | SHADOW index | BGE-M3 |
|---|---|---|
| hardware | CPU | RTX 3090 |
| indexing 4.1M records | **7.4 s** | **65 min** (1,051 records/s) |
| on disk | **2.20 GB** | 8.45 GB of vectors |
| held to serve queries | memory mapped, **28 MB** resident | 8.45 GB of vectors plus 2.36 GB of model, in VRAM |
| find the record | **1.4 us** | 26.6 ms (16.7 encode, 9.9 search) |
| then load it | 0.03 ms, straight into attention | the text still has to be read |

Indexing is about five hundred times faster on a CPU than the embedding model is on a GPU, and the result is a
quarter the size. Per query it is not close: microseconds against tens of milliseconds, and nothing needs a GPU
resident to answer.

**At 100 million documents.** The archive above is 4.1 million records, so the line below is the measured rate
carried forward. It is worth carrying forward because the index scales cleanly: at 12.5M, 25M, 50M and 100M tokens
it costs 21.6, 21.7, 21.9 and 22.0 bytes a token and builds at 14 to 16 million tokens a second, so the shape does
not change with size.

| 100,000,000 documents, 24 tokens each | SHADOW index | BGE-M3 |
|---|---|---|
| build | **3.0 min**, CPU | **26.4 h**, RTX 3090 |
| what you store to search | **53 GB** index + 9.7 GB of text | **205 GB** of fp16 vectors |

| 100,000,000 documents = 2.42B tokens | to find a record |
|---|---|
| the text itself | 9.7 GB |
| **SHADOW index** | **53 GB** |
| BGE-M3 vectors, one per document | 205 GB |

The reason is that SHADOW never builds a vector. BGE-M3 runs a 568M-parameter forward pass over every record to
produce 1,024 floats, and must keep all 4.1 million of them somewhere fast. SHADOW hashes identifier n-grams
straight out of the token stream, so indexing is a pass over the tokens with no model in the loop, and the archive
itself is the storage.

## The attention state, against a normal model

Separately from finding a record, SHADOW keeps the model's own attention state for it, so the record arrives already
read instead of being re-processed. That is a KV cache, written to disk instead of thrown away. The thing to compare
it against is another model's KV cache, not an embedding:

| | values per token | bytes per token | against SHADOW |
|---|---|---|---|
| **SHADOW 50M, 1 bit** | 2,304 | **288** | |
| SHADOW 50M, the same state at fp16 | 2,304 | 4,608 | 16x |
| a 50M model, 8 layers, 8 heads, no grouped queries, fp16 | 8,192 | 16,384 | **57x** |
| GPT-2 124M, fp16 | 18,432 | 36,864 | **128x** |

Two savings that multiply. Six layers and two key/value heads keep 2,304 numbers a token where a conventional
arrangement keeps 8,192, and the 1-bit codec makes each of those sixteen times smaller. Put as capacity, in one
gigabyte: **3,472,222 tokens** of attention state for SHADOW, 61,035 for that 50M model, 27,126 for GPT-2.

The cost is per token, so it suits short records. At 24 tokens a record it is 7 KB a record. At 1,000-token
documents it is 288 KB, and at that point keep the index, let it find the passage, and read the text.

On accuracy the comparison goes the other way round in places, and it depends on the question. On 1,956 known-item
queries over 100,000 MS MARCO passages, SHADOW's index reaches top-1 **0.571**, or **0.743** once the trail is warm (measured on the v1.1 kernel; the trail rule changed on 2026-09-16, see benchmarks/trail_ablation/),
against BGE-M3's **0.331**. On the identifier lookups this archive is built from, the index reaches top-1 **0.9815**
over 2,000 keys. Where a dense model still wins is paraphrase: a query that shares meaning with a record but none of
its words.



---

## Language modelling

Language modelling, scored through the shipped ternary path. Perplexity at three window lengths:

| held-out text | 1,024 | 2,048 | 8,192 |
|---|---|---|---|
| a slice of our own Wikipedia source the corpus build never downloaded | 140.0 | **131.3** | 132.1 |
| WikiText-2, raw test split | 186.1 | 163.4 | **152.7** |

The first row is text this model provably never saw: the corpus took files `train-00000` to `train-00012` of the
Wikipedia dump and that slice comes from `train-00040`, which was never fetched. WikiText-2 is the public benchmark,
reported for comparison; it is Wikipedia too, so we do not claim it was unseen. Training used sequences up to 2,048
tokens and the kernel takes 8,192, which is why the long-article set keeps improving past 2,048 and our own slice,
600 separate articles, does not. A 44M model at 1.58 bits per weight is not built for open-domain language
modelling; it is built for the tables below.

Size next to other small models:

| model | parameters | weights on disk |
|---|---|---|
| GPT-2 | 124M | 548 MB |
| SmolLM2-135M-Instruct | 135M | 269 MB |
| [**SHADOW 250M Instruct**](https://github.com/QLNI/SHADOW-250M-Instruct) (our previous model) | 250M | 60 MB |
| *this same model, 16-bit weights and 16-bit table* | *44M* | *164 MB* |
| **SHADOW 50M Instruct** | **44M** | **19.8 MB, vocabulary included** |

The last two rows are the same 44 million parameters and the same 65,280-token vocabulary: 155 MB at 16 bits, 19 MB
ternary. The vocabulary table alone drops from 76 MB to 4.7 MB.

