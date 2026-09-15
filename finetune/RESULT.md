# A worked fine-tune: teaching the model to write the year

The date circuits take a year, written `dow:Mar14,1990`, and are exact for any date from 1900 to 2100. The shipped model
never writes one. It gets dated questions right because the runtime reads the year out of the question, which works
but leaves the model depending on it. This run closes that: it teaches the model to put the year in the span itself.

Small on purpose. 30,000 rows, 1,500 steps, **75 seconds on one RTX 3090**, starting from `shadow50_instruct.pt`.

    python finetune/corpus.py --out rows.u16 --n 30000
    python finetune/check.py  rows.u16
    python finetune/train.py  --ckpt shadow50_instruct.pt --rows rows.u16 --out tuned.pt --steps 1500

## What it measures

*Span carries the year*: 40 dated questions spread over 1900–2100; does the span the model writes name the year?
*Weekday correct*: is the answer the right weekday? *Kept*: ten questions the model already answered well,
arithmetic, units, percent, letters, compare, chat, identity and open knowledge, checked for damage.

| | span carries the year | weekday correct | kept |
|---|---|---|---|
| shipped weights | **0/40** | 40/40 | 9/10 |
| after 75 seconds | **40/40** | 40/40 | 9/10 |

Nothing else moved: all ten retention answers are identical to the base, item for item. The one the base already
failed is the seven-digit addition, a known operand-copying limit, and it fails the same way after.

## The part worth reading: it took three tries

The first two runs taught the year perfectly and broke something else each time. Both were mix problems, and neither
announced itself. The loss curve looked fine in all three runs.

| run | mix | year | kept | what broke |
|---|---|---|---|---|
| 1 | weekday 6, arithmetic 3, no knowledge rows | 40/40 | 8/10 | "the capital of Japan" → **135** |
| 2 | added knowledge rows at 3 | 40/40 | 7/10 | Japan fixed; subtraction and multiplication broke |
| 3 | knowledge 3, arithmetic raised 3 → 6 | 40/40 | **9/10** | nothing |

Run 1 had no open-knowledge rows at all, so open knowledge went. Adding them fixed that and pushed arithmetic's
share of the corpus down from 4,545 rows to 3,945, which was enough to lose subtraction and multiplication. Run 3
raised arithmetic to match.

The lesson is not "use these weights". It is that **every row you add for the new skill is a row not spent on an old
one**, and the old one fails silently in whatever you forgot to measure. Keep a retention check of things the model
already does well, run it every time, and raise whatever you broke.

## Reproducing

Both checkpoints, the three corpora and the evaluation script are on the pod recipe above; the corpus and the
evaluation are deterministic given `--seed`. `check.py` passes on all three corpora. The failures here were about
what was in the mix, never about how the rows were encoded.
