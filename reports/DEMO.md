# SHADOW 50M: the demo set, measured (2026-09-10)

Three files, every number from a run today, nothing estimated:
- `SUITE_kernel_2026-09-10.md`, 37 prompts through the kernel on the laptop: identity, chat, knowledge, creativity, coding, arithmetic, every tool, programs, archive, multi-turn. Each with tokens per second and the process's resident memory, full transcripts.
- `CONVO_kernel_2026-09-10.md`, eight personal facts told once, asked again when the archive holds 100k, 1M, 50M and 100M tokens, every question twice, with fetch time, decode speed and memory (pod).

## 1. How retrieval works and why it is fast

1. Before the model writes a token, the kernel looks the question's words up in the index: 1.4 microseconds per key at 100M tokens.
2. The winning record's 1-bit K/V (288 bytes per token) is copied out of the on-disk store: a memcpy, 0.03 ms including the mapped-file access. No forward pass. The 4-token cold prefix is cached in the store too, so a fresh process pays nothing either.
3. The model reads that record with its 1-bit attention; the reading head points at the record and the quote is copied verbatim.
4. Every need line the model writes repeats steps 1 to 3, so chains resolve hop by hop.

## 2. The archive at each scale (pod; text + index + store all memory-mapped, nothing loaded)

| tokens | records | index build | index on disk | 1-bit K/V store | store build | index lookup / key | fetch, 1st ask | fetch, repeat | decode | own RAM |
|---|---|---|---|---|---|---|---|---|---|---|
| 100k | 4,264 | 0.00 s | 2 MB | 29 MB | 43 s | 0.4 us | 0.02-0.15 ms | 0.03 ms | 2,046-2,086 tok/s | 28 MB |
| 1M | 42,656 | 0.03 s | 29 MB | 288 MB | 7 min | 0.6 us | 0.03-0.04 ms | 0.03 ms | 2,049-2,084 | 28 MB |
| 50M | 2,080,799 | 2.6 s | 1,093 MB | 14.4 GB | built off the laptop | 1.3 us | 0.03 ms | 0.03 ms | 2,042-2,106 | 28 MB |
| 100M | 4,124,620 | 5.3 s | 2,196 MB | 28.8 GB | built off the laptop | 1.4 us | 0.03 ms | 0.03 ms | 2,048-2,086 | 28 MB |

Wall clock per answer, process start to exit, prompt to `[eot]`: 41 to 49 ms at every scale. Process-owned memory is 28 MB at 100k and at 100M; file-backed resident pages (the OS cache of the mapped files, droppable) 3 MB at 100k, 10 to 17 MB at 100M.

## 3. The prompt suite (laptop, 8 threads, greedy)

37 prompts, all transcripts in `SUITE_kernel_2026-09-10.md`. Resident memory 37 to 41 MB for every prompt.

| area | result |
|---|---|
| identity, chat (5) | all clean, 1,941-2,125 tok/s |
| general knowledge (5) | all correct, 1,750-1,857 tok/s |
| arithmetic (4), 7-digit sums, 4-op chain | all exact through the circuits, 1,931-2,300 tok/s |
| tools (11): units, temperature, percent, average, date across year end, weekday, letter count, word count, largest, sort | all exact, 1,571-2,143 tok/s |
| programs (2): Fibonacci 20, is 97 prime | both correct through the VM, 1,450-1,498 tok/s |
| archive (3): lookup, absent key, lookup then unit conversion | all correct, 814-1,333 tok/s |
| multi-turn (1) | correct (168) |
| creativity (3) | thin: a flat "poem", a non-answer for the story opening, one real joke |
| coding (3) | poor: it does not write a Python function on request (answers with a number), and misreads the printed value of a 3-line program (4 instead of 13). Its code ability is the VM programs it writes for itself, not code for a user. |

## 4. The long-memory demo (pod)

Facts stored early in the session, as records under the key `User SK`: name Sai Kiran, dog name Bruno, condition type 2 diabetes, advice avoid chocolate and sugary drinks, city Sydney, birthday March 14, coffee limit, project. The session then grows to 100k, 1M, 50M, 100M tokens of other records. Eleven questions at each scale, each asked twice.

Result: 5 of 11 at every scale, the same five, the same wrong answers, the same speed. Scale does not change anything; that is the point of the archive design and it is measured.

| question | 100k .. 100M | what happened |
|---|---|---|
| dog name, condition, city, birthday of User SK | correct | index finds the record by attribute + key, quote copied, answer stated |
| name of User ZZ (never mentioned) | correct abstain | "There is no record of User ZZ." |
| name of User SK | wrong: "Bruno" | "name" also appears in the dog-name record; the tie goes to the dog record |
| advice of User SK | wrong: "to use chocolate and sugary drinks" | the right record is fetched and quoted verbatim ("avoid chocolate"), then the model inverts it. The same negation defect as on 2026-09-09. |
| "User SK is planning to eat chocolates tonight. Is that a good idea?" | wrong: answers from knowledge, no lookup | a statement, not the trained lookup form; the model never writes a need line |
| "Does User SK have any health condition I should know about before dinner?" | wrong: "Yes, User SK has a health condition that is not indicated by a doctor." | natural phrasing; no lookup |
| weekday of the birthday; letters in the dog name | wrong at top-1 in this run: "no record" | the composite worked in an earlier run of the same day ("[quote] birthday March 14. [calc]dow:Mar14[eq]Saturday") and flips with the need line's wording |

Reading: the archive machinery holds at 100M (fetch 0.03 ms, 2,000 tok/s, 28 MB); what fails is the model on the record in front of it. Every failure above is a supervised fine-tuning item: negation, "name" vs "dog name" under one key, conversational phrasing that should trigger a lookup, composite wording. None is a kernel or index defect, and none changes with scale.

Also measured and rejected: several candidate records with the same key into attention at once (top-4, top-8) makes the model treat the archive as irrelevant and answer from knowledge (2 of 11). Keep one record per fetch.
