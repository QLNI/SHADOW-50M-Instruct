# Memory from a disk archive: a fact told once, answered later (2026-09-09, laptop)

All of this runs on one laptop CPU with the archive on the hard disk. Nothing is loaded into memory.

## The archive is genuinely on disk

The index and the token stream are memory-mapped, so a question faults in the pages it touches and nothing else.

| archive | open time | resident memory |
|---|---|---|
| 100k tokens | 0.00 s | 39.0 MB |
| 1M tokens | 0.00 s | 39.0 MB |
| 50M tokens | 0.00 s | 39.0 MB |
| 100M tokens | 0.00 s | **39.0 MB** |
| 100M tokens, read into RAM instead | 0.83 s | 2,417.9 MB |

A hundred million tokens of archive costs the same resident memory as no archive at all.

## Sanity check: retrieval through the kernel, end to end

Twelve questions per scale, each one answered from the on-disk archive with the record quoted.

| archive | answer top-1 | index and fetch | decode |
|---|---|---|---|
| 100k tokens | 0.833 | 12.7 ms | 1,481 tok/s |
| 1M tokens | 0.750 | 12.3 ms | 1,453 tok/s |
| 50M tokens | 0.833 | 14.2 ms | 1,408 tok/s |
| 100M tokens | 0.583 | 14.2 ms | 1,301 tok/s |

## The demo: told once, out of the window, answered anyway

Eight notes are written into a notebook that also holds 200,000 tokens of unrelated records. Every question is then asked in a
fresh context, so nothing that was said earlier is in the window.

| question | answer | |
|---|---|---|
| medication of Prescription P-8843 | "Metformin twice daily." | correct |
| allergy of Card A-5107 | "penicillin." | correct |
| doctor of Appointment C-3320 | "Herrera." | correct |
| blood sugar of Meter M-7714 | "142." | correct |
| advice of Plan D-6605 | "to eat chocolate and sugary drinks." | **wrong: the record says avoid** |
| condition of Patient R-2291 | "Positive." | wrong, the record says type 2 diabetes |

Five of six retrieved the right record. Two answers are wrong, and one of them matters more than a score: the note reads
*avoid chocolate and sugary drinks* and the model answered *to eat chocolate and sugary drinks*. It dropped the negation while
quoting the right record. In a health setting that is worse than failing to answer, and it belongs at the top of the fix list.

Retrieval runs at 10 to 13 ms a question with the archive on disk, and decoding stays at 1,400 to 1,630 tokens a second, close
to the 1,790 of a pure hot-window turn.

## The Hebbian trail: what it does and what it does not

The trail is real and it persists. The index is mapped writable, a confirmed fetch makes that record heavier under the
question's own n-grams, and the index file on disk changes after every question. A short-circuit was added so that a record
already confirmed for a question is returned without the ranking rescan.

**It does not make a repeated question faster, and the measurement says why.** Asking the same question five times:

| | ask 1 | ask 2 | ask 3 | ask 4 | ask 5 |
|---|---|---|---|---|---|
| index and fetch | 10.0 ms | 12.0 ms | 11.0 ms | 10.0 ms | 10.0 ms |

The index lookup itself is **1.3 microseconds**. The other ten milliseconds are encoding the fetched record into 1-bit keys and
values, and a trail cannot skip that: the record still has to be turned into something the attention can read. Within one
process the kernel already avoids re-fetching the same record; across separate processes, as measured here, nothing is reused.

So the honest statement is: the index finds a repeated question instantly, and the model still pays to read the record. Making
a repeat free needs the encoded record cached, which is a session-level change and not a property of the trail.

## What this leaves on the fix list

1. **The dropped negation.** Right record, inverted meaning. First priority.
2. **Two facts under one key.** Asking for the medication of a patient whose record also carries a condition returns the
   condition. Distinct keys work; the same key with several attributes is the known weak spot.
3. **Natural phrasing does not reach the archive at all.** "What condition do I have?" is answered from the model's own
   knowledge, with no need line and no lookup. Retrieval fires for the entity-and-attribute form it was trained on. Teaching
   the conversational form is a supervised fine-tuning line item, not a kernel change.
4. **A cached encoded record**, so a repeated question costs the index lookup alone.
