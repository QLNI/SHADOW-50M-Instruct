# Adapters: a bookkeeping domain, measured

The first adapter for SHADOW 50M, and the machinery to make more. The ternary weights never change; a low-rank path
sits beside them, trained on the domain, shipped as one file, loaded with an environment variable, and gated through
the kernel like everything else. This page says what works, what does not yet, and the two things learned about the
base model on the way.

## What an adapter is here

Each of a block's projections (query, key, value, output, and the second feed-forward matrix) gets a side path
`y = W x + B (A x)`, rank 8 or 16, in float, on the same input the ternary matmul sees. The first feed-forward matrix
is left out because the kernel fuses its activation. Training freezes every base parameter and updates only A and B;
merging into the ternary weights is never done, because requantising would flip cells and change the published
behaviour. The kernel loads the file with `LORA=<file>`; without one, the side path does not run and the kernel is
the shipped kernel (30 of 30 prompts identical, one-shot, on Windows; with an all-zero adapter loaded, also 30 of 30,
and `GOLDEN 8/8` on Windows and Linux). Cost with rank 8 loaded, measured: 0.69 ms a token against 0.52 without.

    python finetune/bookkeeping_corpus.py --out book.u32 --n 44000
    python finetune/replay_rows.py --out replay.u32 --n 600                   # the base's own answers, kept in the mix
    python finetune/train.py --ckpt shadow50_instruct.pt --rows mix.u32 --out book.pt --lora 16 --lr 2e-4 --steps 3000 --lora-out book.bin
    python finetune/bookkeeping_suite.py --lora book.bin --topk 4              # the domain, through the kernel
    python finetune/samples_gate.py --lora book.bin                            # the 37 published prompts, adapter against base

The `.pt` holds A and B; the `.bin` is the kernel's format (magic, rank, per layer per target the two matrices, B
carrying the scale). Rank 8 is 1.9 MB, rank 16 is 3.8 MB. Two are in `finetune/adapters/`.

## The domain

Invoices as records on disk, four lines each, `INV-2041 amount: 1250.`, `INV-2041 due: April 14, 2026.`, customer and
status. Four question shapes: read an attribute; a percentage of the amount (tax, late fee, discount); the amount left
after a part payment; the days until the due date from a stated date. The last three are a shape the shipped model
never writes: a record read, then a circuit span, in one working. Forty invoices in the archive, one question of each
shape per invoice, ten invoices that are not there, and ten circuit or chat prompts asked with the archive attached.

| | read | percent | balance | days | absent | circuits with archive | total |
|---|---|---|---|---|---|---|---|
| base, one record per fetch | 40/40 | 29/40 | 2/40 | 0/39 | 6/10 | 7/10 | 84/179 |
| base, four records per fetch | 40/40 | 5/40 | 2/40 | 0/39 | 6/10 | 7/10 | 60/179 |
| adapter rank 8, four per fetch | 40/40 | 21/40 | 11/40 | 5/39 | 5/10 | 8/10 | 90/179 |
| adapter rank 16, four per fetch | 40/40 | 25/40 | 14/40 | 6/39 | 6/10 | 7/10 | 98/179 |

Both adapters: 3,000 steps, learning rate 2e-4, the domain rows with the kit's retention rows and 610 replay rows,
one RTX 3080 laptop GPU, about five minutes each. The published-samples gate, adapter against base on the 37 prompts
of SAMPLES.md: rank 8 changes 16 traces (13 answers), rank 16 changes 17 (15 answers). Some changes are rewordings,
several are wrong numbers (the two-turn arithmetic, a seven-digit sum). Neither adapter should be loaded for general
use; they are domain files, and the numbers above are what they do.

So: reading is solid with or without the adapter; the composite shapes are learned in form (the traces show need,
quote, span, answer in order) but not in substance. The failure is copying a number from the question into the span
after four frames of records: a payment of 400 became 4000 or 4760, a due date became today's date twice. The rows
already put that number last in the question, nearest the span, which took balance from 2 to 14 of 40. Days is worse
because the answer sentence after a correct span often falls into the "no record" form the absent rows teach.

## Two things about the base, found on the way

**With an archive attached, the kernel fetches for any prompt that carries a number.** Amount and date pieces match
the index, a record is handed to the model, and the base sometimes reads it instead of computing: on a 160-record
invoice archive, 15 percent of 240 came back as "240", a weekday as a due date, a seven-digit sum wrong. Turning the
pre-fetch off (a temporary switch, not shipped) fixed every circuit and broke every record answer, because the fetch
at the model's need line only re-selects among frames already present. The rows now carry the kit's own retention
prompts with an invoice's four frames in front of the working, so an adapter learns to ignore a frame the question
did not ask for. This is the first measurement of the effect and it belongs in the runtime's own notes.

**Four records under one identifier need four records per fetch.** At one record per fetch the index hands over one of
the four by its trail, often the wrong attribute (a "due" question got the amount record). `AX_TOPK=4` brings all four
and the model's need line picks among them; training rows carry four frames in random order to match. The eleven
full fine-tunes of the vocabulary work were gated the same way; nothing here changes their result.

## Rules kept

Every number came through the kernel on the shipped container, one fresh process per question. The base binaries are
the same source as before plus the side path; the gates above are the receipt. Records and names in the corpus are
made up.

## Next

The composite shapes need either more capacity at the copy (a longer run, or rank 32 on query and value only, both
untested) or a shape that does not copy: ask the amount, then ask the arithmetic, two calls, both inside what the base
already measures. A harness built that way needs no adapter for the arithmetic and would be honest about what the
adapter adds, which today is the answer style and the frame-ignoring rows.
