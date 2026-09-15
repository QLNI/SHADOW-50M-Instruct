# Fine-tuning SHADOW 50M

Four files. Write rows, check them, train, measure.

    python finetune/corpus.py --out rows.u16 --n 30000     # build a corpus
    python finetune/check.py rows.u16                       # refuse to train on a broken one (.u32 rows are read as uint32)
    python finetune/train.py --ckpt shadow50_instruct.pt --rows rows.u16 --out tuned.pt --steps 1500

Start from `shadow50_instruct.pt`. It is at the root of the
[Hugging Face repo](https://huggingface.co/QLNI/shadow-50m-instruct) (the direct link is on the card). Not from the
19.8 MB `.shdw`. The `.pt` holds the latent full-precision weights that training requantises from at every step. The
container holds three values per layer; the master weights hold about 2.2 million.

## The row

Every training row is the same shape:

    [bos][sot]user\n  <question>  [eot][sot]model\n  [think] <working> [endthink] [sol] <answer> [endsol][eot]

The working is where the model reaches for something. A chat turn has none. A turn that computes puts a span there.
A turn that reads a record puts a `[need]` line and a `[quote]` line there.

## The one rule that matters

**Spans are markup, not text.** Write them through `E.enc`, never `E.plain`. The two decode to the same string and
tokenise completely differently:

```
E.plain("[calc]47+128[eq]175[ecalc]")   ->  [90, 41003, 92, 1920, 42, 5716, 90, ...]    14 tokens, text pieces
E.enc("<CALC>47+128<EQ>175<ECALC>")     ->  [12, 51, 54, 42, 48, 49, 55, 13, ...]       12 tokens, symbols + digits
```

Both print `[calc]47+128[eq]175[ecalc]`. Only the second is a span. A corpus built the first way reads perfectly,
trains fluent nonsense, and nothing warns you. The loss even goes down. This cost us a full run. `check.py` exists
to catch exactly this and fails loudly on it.

Inside a span every digit is its own token. Outside one, numbers tokenise normally.

## Writing a row for each circuit

The span body is the circuit's grammar. Get it exactly right or the circuit stays silent and the model answers from
memory instead.

| circuit | span body | example row |
|---|---|---|
| arithmetic | `a+b` `a-b` `a*b` `a//b` | `<CALC>47+128<EQ>175<ECALC>` |
| calendar | `cal:Mar5+90d`, `cal:Jun3-Mar5` | `<CALC>cal:Dec20+45d<EQ>February 3<ECALC>` |
| calendar with a year | `cal:Feb25,2024+10d` | `<CALC>cal:Feb25,2024+10d<EQ>March 6<ECALC>` |
| weekday | `dow:Mar14` (base 2026) | `<CALC>dow:Mar14<EQ>Saturday<ECALC>` |
| weekday with a year | `dow:Mar14,1990` | `<CALC>dow:Mar14,1990<EQ>Wednesday<ECALC>` |
| units | `unit:85kg>lb`, `unit:37C>F` | `<CALC>unit:85kg>lb<EQ>187.4<ECALC>` |
| percent | `pct:15% of 240` | `<CALC>pct:15% of 240<EQ>36<ECALC>` |
| letters | `count:r in strawberry` | `<CALC>count:r in strawberry<EQ>3<ECALC>` |
| words | `count:words in <phrase>` | `<CALC>count:words in she sells sea shells<EQ>4<ECALC>` |
| compare | `cmp:largest of 4,9,2`, `cmp:sort 9,4,2` | `<CALC>cmp:sort 44,7,91,23<EQ>7,23,44,91<ECALC>` |

Put the **true** result after `<EQ>`. At training time it is a target like any other; at run time the circuit
computes it and forces those tokens. If your result is wrong, you are teaching the model to route to a circuit and
then disagree with it.

Records look different. The frame is what the runtime injects, and the `[need]` and `[quote]` lines are the model's:

```
[copen] pos=702828\nAudit line: Vault-418 count recorded as 3271. [cclose]
[need] count of Vault-418.
[quote] pos=702828: Audit line: Vault-418 count recorded as 3271.
```

## The weighting, and why it is not optional

`train.py` weights every position:

| weight | positions | why |
|---|---|---|
| **0** | between `[eq]` and `[ecalc]`, between `[run]` and `[evm]` | a circuit writes those tokens. Training on them teaches the model to predict what it will be handed anyway, and it drifts toward answering from memory instead of opening a span. |
| **0** | record frames inside a think block | that text is runtime input, never model output. |
| **3** | `[need]` and `[quote]` lines, `[sol]`..`[endsol]`, the token that opens a span | this is the routing: *when* to reach for a circuit or a record, and *what* to answer. It is the whole job. |
| **1** | everything else | ordinary language. |

## Keep a mix

A run that is 100% one new shape learns that shape and forgets the rest. We have measured this twice: a fine-tune
stacked on the release weight took programs from 11/40 to 7/40. `corpus.py` mixes chat, records and every circuit
alongside the new material, and you should too.

## What ships here

[RESULT.md](RESULT.md) is a worked example: 30,000 rows, 1,500 steps, 75 seconds on one GPU, teaching the model to
write the year into a date span. It went 0/40 to 40/40 with nothing else lost, on the third try. The two runs that
went wrong are in there too, because the mix is the hard part and both failures were silent.

## Run what you trained

A trained `.pt` becomes a container in two steps, and the kernel then runs it like the shipped one:

    python runtime/explode50r.py --ckpt tuned.pt --data . --out cbin
    cp deployment/ident.bin deployment/fold.bin deployment/stop.bin cbin/
    python runtime/mkshdw.py --dir cbin --out tuned.shdw --skip-f32
    deployment/bin/windows/shadow50.exe tuned.shdw 40        # prints GOLDEN: the kernel checked against your checkpoint
    python shadow_chat.py --model tuned.shdw

The three copied blobs are the token tables the archive needs; a container packed without them loads an archive but
never fetches from it (measured, the v1.1.0 mistake). The trainer needs `runtime/`, `tables/` and `unigram/` from this
repository next to it; the circuits are built by the kernel from the table at load, so a fine-tune never touches them.

## Adapters

`train.py --lora <rank>` trains a low-rank path beside the frozen ternary projections instead of the weights, and
`--lora-out` writes it in the kernel's format, loaded with `LORA=<file>`. The base stays bit-identical without one.
The first domain built this way, small-business bookkeeping, with its corpus generator, its suite through the kernel,
the published-samples gate and the measured numbers, is in [BOOKKEEPING.md](BOOKKEEPING.md). `replay_rows.py` turns
the shipped model's own answers into rows to keep in any mix.
