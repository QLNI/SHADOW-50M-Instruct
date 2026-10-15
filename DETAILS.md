# SHADOW 50M Instruct, the long version

Everything that did not need to be on the front page: how the archive works, the architecture, the speeds,
the repository layout, the chat template, what it is and is not for, and the limitations in full.

Back to the [README](README.md). The model this one came after is
[SHADOW 250M Instruct](https://github.com/QLNI/SHADOW-250M-Instruct), which has a longer write-up of how the
archive works.

---

## The archive is the model's memory, not a database in front of it

Retrieval-augmented systems find a passage and paste its text into the prompt; the model then has to read it again,
tokenize it again, and can misread it on the way in. SHADOW does not do that. What lives on the disk is the model's
**own memory of every record**: the attention state it holds for a record it has read, kept at 1 bit per value, 288
bytes per token, next to the text and a small index. The index finds; attention remembers.

1. **Before the model writes a token** the kernel looks the question up in the index: 1.4 microseconds per key at 100
   million tokens.
2. **The record's memory is placed straight into the model's attention**, from disk, in 0.03 ms. No forward pass, no
   re-reading, no text pasted into the prompt. This is the same attention the model uses on the conversation in front
   of it; the record simply becomes part of what it can attend to.
3. **The model then answers the way it was trained to**: it writes what it needs, the reading head settles its
   attention on the record, it quotes the record with its position, and it states the answer. If it needs another
   record it writes another need line and steps 1 and 2 repeat, which is how chains resolve hop by hop. If there is no
   record, it says so.

Because the memory is the model's own state and not a second copy of the text, the same question at 100 million tokens
costs what it costs at 100 thousand: 0.03 ms to fetch, 28 MB of process memory, about 2,000 tokens per second to answer.

**The index carries a trail.** A confirmed quote makes that record heavier under the question's own words, and the
weights persist in the file, so the index keeps what it learned across runs. It stores no answers and no copy of
the record, only a few numbers per posting. The gain is in ranking, not latency: top-1 goes from 0.571 to 0.743 (measured on the v1.1 kernel) on
the retrieval comparison, while the warmed index is slightly slower per query and holds more memory.

The search is the index's job. We measured whether attention alone could find a record among 42,648 without the index:
it cannot (recall 0.000 at 1M tokens; the measurement is in the project ledger). Attention's job is to remember and
read what the index finds, and that is what it does.

---

## Archive and chat samples

Every sample is the kernel's greedy output on the shipped file, unedited. The arithmetic, dates, units, counting,
comparison, sorting and program circuits each get a worked example of their own under
[The circuits](README.md#the-circuits); this section is what those do not cover. The full set, with the speed
and token count of each, is in [SAMPLES.md](SAMPLES.md).

**"What is the count of Vault-418?"**, 16 records in the cold archive · 1,121 tok/s
```
[need]count of Vault-418.
[quote]pos=702828: Audit line: Vault-418 count recorded as 3271.
[endthink][sol]3271[endsol]
```

**"What is the count of Tank-777?"**, a key that is not among the records · 814 tok/s
> Tank-777 does not appear in the records.

**A three-hop chain, every hop a lookup on disk** ("What is the count of Belt-813?", 100k tokens of other records)
```
[need]count of Belt-813.
[quote]pos=293945: Transfer note: contents of Belt-813 moved to Tank-166.
[need]count of Tank-166.
[quote]pos=715634: Transfer note: contents of Tank-166 moved to Vault-848.
[need]count of Vault-848.
[quote]pos=230807: Inspection tag: Vault-848 count measured at 92945.
[endthink][sol]92945[endsol]
```

**"What is the capital of Japan?"** · 1,857 tok/s
> From my knowledge: The capital of Japan is Tokyo.

**"Tell me a short joke about computers."** · 1,889 tok/s
> Why did the computer go to the doctor? Because it had a virus.

---

## One conversation, in full

Each message stands alone by default. `--remember N` keeps the last N exchanges in the window, which is what a
conversation needs. Facts arrive as ordinary statements, six unrelated turns go by, and then they are asked for.
Seventeen turns through the shipped kernel, unedited:

```
you> Tell me a short joke about computers.
     Why did the computer go to the doctor? Because it had a virus.
you> That is a good one. My name is Zeph Marlowe, by the way.
     Nice to meet you, Zeph Marlowe.
you> I just adopted a dog. His name is Bruno.
     Bruno is a good name for a dog.
you> We live in Sydney.
     Sydney is a good place to be.
you> One more thing: I have type 2 diabetes, so I watch what I eat.
     Thank you for telling me. I will keep that in mind.
you> I have a 1 kg bag of rice.
     Good to know.
...  (27 + 45, the capital of France, 5 km in miles, a weekday, a letter count: all correct)
you> What is my name?
     Your name is Zeph Marlowe.
you> What is my dog called?
     Your dog's name is Bruno.
you> Where do we live?
     You told me you live in Sydney.
you> That 1 kg bag I mentioned, how much is that in pounds?
     The answer is 2.2 lb.
you> I am thinking of having a chocolate cake tonight. Any thoughts?
     Remember you have type 2 diabetes. A chocolate cake is worth avoiding.
```

Every acknowledgement is different, the name and the dog's name stay separate, a quantity mentioned in passing is
converted eleven turns later, and the condition is applied to a question that never mentions it.

---

## Architecture

| | |
|---|---|
| Hidden size | 896 |
| Layers | 6 |
| Attention heads | 14 query / 2 KV, head dim 64 |
| Intermediate size | 2,464, SiLU |
| Vocabulary | 73,880 tokens, frozen 512-bit codes, 0 trainable parameters, 4.7 MB (v1.1: 8,600 English pieces added, see below) |
| Body weight precision | ternary (1.58 bits per weight), trained that way from step 1 |
| Hot window | the conversation in front of it, 16-bit attention state |
| Archive | the model's memory of every record, 1-bit attention state, 288 bytes per token, on disk |
| Parameters | 44.1M |
| Runtime | one small binary, AVX2 + F16C, no framework |

## Performance

Laptop CPU, 8 threads, 200-token decode, the files in this repository:

| | |
|---|---|
| chat turn (12-token prompt) | 2,000 tok/s, 38.6 MB RSS |
| word problem with a calculation | 2,020 tok/s, 38.7 MB |
| 868-token context | 1,250 tok/s, 44.0 MB |
| 3,000-token cold archive in the prompt, sparse attention | 917 tok/s, 44.3 MB |
| archive on disk, 100M tokens: fetch / decode / RAM | 0.03 ms / 1,994 tok/s / 28 MB own memory |
| deployment | 19.8 MB container + 197 KB Windows executable, static, no DLLs (1.1 MB static Linux) |
| browser (WebAssembly, same kernel, bit-exact) | 450 to 530 tok/s with 7 threads, 175 to 195 on one thread |

## Repository layout

    deployment/                the model and the runtime
      shadow50_instruct.shdw   19.8 MB: ternary weights, frozen table, runtime constants, vocabulary, self-test prompt
      bin/windows/  bin/linux/ prebuilt kernel and index tool (macOS on request)
      fold.bin ident.bin stop.bin   token tables the index tool needs
    tokenizer/                 tokenizer.json, the encoder, the table maps, the v1.1 table receipt
    shadow_chat.py             chat
    shadow_archive.py          build an archive on disk from a text file; ask it questions
    shadow_runtime/            the Python wrapper (encode, run the kernel, decode)
    web/                       the same kernel compiled to WebAssembly, and a chat page that runs it in the browser
    BENCHMARKS.md              every table: perplexity, multiple choice, the archive at four scales, retrieval, the attention state
    SAMPLES.md                 37 transcripts, plus three prompts for every circuit
    DETAILS.md                 this file
    finetune/                  the fine-tuning kit: corpus builder, checker, trainer, worked result
    runtime/                   the model as the trainer sees it, and the export: checkpoint -> blobs -> container
    tables/  unigram/          the 73,880-row table and its prior, what a fine-tune trains against
    framework.svg              the animated diagram on the front page
    reports/CONVERSATIONS_50.md  fifty conversations, 950 turns
    benchmarks/                the vocabulary word-similarity benchmark and its data
    reports/                   the archive measurements, the memory-at-scale transcripts, the receipts
    RECEIPTS.md                every number on this page, and the file it comes from

## Usage

Chat. Each message stands alone by default, which is what you want for unrelated questions. `--remember N` keeps the
last N exchanges in the window, which is what a conversation needs; it costs some single-turn exactness, so turn it on
for a conversation and leave it off otherwise. `--trace` shows the working, `--stats` prints speed and memory:

    python shadow_chat.py --trace --stats
    python shadow_chat.py --remember 24            # a conversation that remembers what you told it

Build an archive from a text file, one record per line, and ask it:

    python shadow_archive.py build examples_notes.txt my_notes
    python shadow_archive.py ask my_notes "What is the condition of User SK?" --trace
    python shadow_chat.py --archive my_notes

Records are lines with an identifier in them (a name, a code, an id) and an attribute word; the model finds a record
by those, quotes it with its position, and answers. `build` writes three files: the token stream, the index, and the
1-bit store (the slow step, about 0.4 ms per token on a CPU).

The kernel directly, no Python (the container carries its own self-test prompt; `GOLDEN 8/8` means the build matches
the reference token for token):

    deployment\bin\windows\shadow50.exe deployment\shadow50_instruct.shdw 200
    deployment/bin/linux/shadow50 deployment/shadow50_instruct.shdw 200

Flags are environment variables: `SHADOW_PROMPT=<ids.bin>` a prompt (int32 token ids), `ARCHIVE=<dir>` answer from an
archive on disk, `AX_TOPK=<k>` records per fetch (default 1), `READ_HEAD=4` the reading head, `SPARSE=2` attention on
the selected record, `COLD=1` treat the prompt's records as the cold archive, `KVBUILD=1` build `<dir>/kv.bin`,
`NOPIN=1` no thread pinning. Thread count is the compile-time `NT` (8 in the shipped binaries). The binaries need a CPU
with AVX2, FMA and F16C (any x86-64-v3 CPU, 2013 or later); on an older one the kernel says so and exits instead of
dying on the first vector instruction. `SERVER=1` keeps the
kernel loaded and answers requests from stdin, one per line, `<gen> <n> <id> <id> ...`, replying `IDS: ...` then `END`;
the hot cache is kept across requests that share a prefix, and the answers are the ones the one-shot kernel gives
(30 of 30 prompts identical, 4.5 ms a request on a laptop). The draft harness in examples/ runs on it. `LORA=<file>`
loads a low-rank adapter beside the ternary projections (see [finetune/BOOKKEEPING.md](finetune/BOOKKEEPING.md));
without one the side path does not run and the kernel is unchanged (30 of 30 identical, `GOLDEN 8/8` with an all-zero
adapter loaded).

### Chat template

    [bos][sot]user
    {message}[eot][sot]model
    {working}[endthink][sol]{answer}[endsol][eot]

Archive records are framed `[copen]pos=N\n{text}[cclose]`. The working holds `[need]` lines, `[quote]pos=N: ...`
lines copied from the archive, `[calc]...[eq]...[ecalc]` spans computed by the circuits, and `[vm]...[run]...[evm]`
programs. Chat replies have no working block.

## Intended use

Intended:

* Local assistants on CPU-only hardware, fully offline
* Exact arithmetic, dates, units and counting in a tiny footprint
* Question answering over your own records: logs, inventories, notes, catalogues
* Research and education on small models, ternary training and memory on disk

Not intended:

* Production or user-facing deployment without human review
* Advice or decision support of any kind
* Creative writing or code generation for a user
* Non-English text

## Limitations, measured

Every item was measured against the shipped container, and every number here comes from a run, not an estimate.

* **Long operands are copied into the span unreliably, and that is the arithmetic failure mode.** The circuit is exact
  on whatever operands it is given; the model has to transcribe them into the span first, and that is where it breaks.
  Additions, 40 per width, both operands the same width, through the kernel on the 1.1 container:

  | digits | 3 | 4 | 5 | 6 | 7 | 8 |
  |---|---|---|---|---|---|---|---|
  | correct | 100% | 95% | 98% | 63% | 78% | 28% |

  Exact to five digits, patchy through six and seven, mostly broken at eight (the 1.0 container measured the same, within
  one or two per width). A failure looks like
  `[calc]4+295864[eq]295868[ecalc]`. The arithmetic is right, the operands are not. With `--trace`, read the span.
* **A mis-copied span is not a safe failure.** The page says an unmatched span leaves the circuit silent and the model
  carries on, which is true, but the model then answers anyway from its own guess. "What is 8 percent of 1250?" wrote
  `pct:8[eq]`, dropped the rest, and answered 1250. No circuit ran and nothing marked the answer as unfounded.
* **Date questions need the year written out.** The spans are `dow:Mar14` and `cal:Feb25+10d`, month and day only.
  When the question names a year, as in "What day of the week is March 14, 1990?", the circuit reads that year from the
  question and is exact, leap years included: 29 February 2024 is a Thursday, 1 March 1900 a Thursday, 31 December
  2100 a Friday. Spans may also carry it directly (`dow:Mar14,1990`). With no year anywhere, the base calendar is
  2026. Outside 1900-2100 the circuit stays silent rather than answer.

* **Programs are the weakest of the three headline abilities.** Seven of twelve: Fibonacci at 10 and 20, gcd of 48 and
  18, the sum to 50, prime counts below 30 and 50, and 2^16. It fails gcd of 1071 and 462, the sum to 100, 7 factorial,
  digit sums, and a primality question. Right on the shapes it was taught, unreliable off them.
* **Sorting a longer list stutters.** Eight numbers sorted correctly inside the span, then the model restarted its
  answer once before closing. The answer was right, the trace was not clean. Four-number lists are clean.
* **Attribute words that contain other attribute words are not distinguished.** With `name` and `dog name` under one
  identifier, "What is the name of X?" returns the dog's name **10 times out of 10**, at any `--topk`. Attributes
  sharing no words are fine: over 10 identifiers with four attributes each, `city` and `condition` were **10/10**. A
  bare attribute can also land on the wrong record: "What is the advice of User SK?" quoted the birthday record, while
  "What is the diet advice for User SK?" quoted the right one. Name attributes so none contains another, and ask with
  the full attribute.
* **Statements and yes/no questions do not trigger a lookup.** Phrasing is otherwise flexible. "What is the diet
  advice **for** User SK?", "What is User SK**'s** condition?", "**Tell me** the condition of User SK.", "What city
  does User SK **live in**?" and "**When is** User SK's birthday?" all retrieve and quote correctly. But "Does User SK
  have any health condition?" and "I am planning to eat chocolates." are answered from general knowledge with no quote.
  The conversation window is a separate mechanism and does handle statements; see [One conversation, in full](#one-conversation-in-full).
* **An absent key is not always reported as absent.** Among 16 records it says so correctly. In a 3,200-record archive
  only **2 of 6** genuinely absent keys came back as "no record"; the other four produced a fabricated number. If there
  is no `[quote]` line behind an answer, treat it as unfounded.
* **Three-hop chains resolve 9 of 20 times.** The failure is an early close: the first two quotes are right, the model
  does not write the third `[need]` line, and states a number instead. Two-hop is 20/20.
* **Open facts are thin.** Ten of twelve general-knowledge questions, with confident errors on the other two: it gives
  Australia's capital as Sydney and a leap year as 365 days. Expect mistakes outside the archive and the circuits.
* **It does not write code on request.** Asked for a Python function it replies "Noted."; asked to sort a list in
  Python it returns a sorted list instead. Its programs are the ones it writes for its own machine.
* **A lowercase name the model never trained on is recalled about three times in four.** The first release's 65,280-token
  table could not spell every word piece; a missing piece was dropped before the model read the message ("fitzgerald"
  arrived as "fitz"). Version 1.1 adds the 8,600 English word pieces that were missing, as frozen rows in the same
  geometry, with no change to the weights: every published answer is unchanged, 34 of 34. The model reads the new rows
  (all 30 lowercase place names in a test list now arrive whole, against 25 before) and copies them back 46 and 49 times
  in 60 on two held-out word sets, from 0 before. Capitalised names were always whole and always recalled. The
  measurements are in [reports/EXTENSION_2026-09-13.md](reports/EXTENSION_2026-09-13.md).
* Trained on public web text, so its outputs can carry the biases of that text. English only.
