# Version 1.1: the vocabulary extended, the weights unchanged (2026-09-13)

The first release's table held 65,280 tokens and could not spell every English word piece. A piece it lacked was dropped
before the model read the message, so "fitzgerald" arrived as "fitz" and a lowercase place name could lose its tail.

Version 1.1 adds the 8,600 English word pieces that were missing, as frozen 512-bit rows placed in the same geometry as
the rest of the table, and sets their prior to the 75th percentile of the existing rows. The weights are the same file
as v1.0. Nothing was trained. The kernel now reads the table size from the container.

v1.1.1 (same day): the first v1.1 container was packed without the three small archive blobs (identifier flags, case-fold
map, stop list) that the v1.0 container carried, so an archive on disk was loaded but never fetched from. Repacked with the
blobs extended to the new rows; the archive path re-verified (records fetched, quoted, absent keys reported); every one of the
37 sample answers unchanged. The sample suite injects records into the prompt, which is why it did not catch this; the gate
now includes a fetch from disk.

## What changed, measured through the kernel on the shipped container

Every family is scored the same way on v1.0 and v1.1, one fresh process per question, greedy decoding.

| family | v1.0 | v1.1 |
|---|---|---|
| add 3 digits | 40/40 | 40/40 |
| add 4 digits | 39/40 | 38/40 |
| add 5 digits | 38/40 | 39/40 |
| add 6 digits | 26/40 | 25/40 |
| add 7 digits | 32/40 | 31/40 |
| add 8 digits | 11/40 | 11/40 |
| subtract 3-6 digits | 28/30 | 28/30 |
| multiply | 30/30 | 30/30 |
| divide | 30/30 | 30/30 |
| largest of 4 | 29/30 | 29/30 |
| sort 4 | 26/30 | 25/30 |
| units | 30/30 | 30/30 |
| temperature | 16/20 | 16/20 |
| percent | 20/20 | 20/20 |
| calendar | 16/20 | 16/20 |
| weekday | 20/20 | 20/20 |
| letters | 19/20 | 19/20 |
| programs | 19/25 | 19/25 |
| facts | 9/10 | 9/10 |
| recall, gate words | 0/60 | 46/60 |
| recall, fresh words | 0/60 | 49/60 |
| conversation | 8/8 | 8/8 |

"recall" is "my name is <word>" then "what is my name" on 60 lowercase words the v1.0 table could not spell; the gate
set was used while choosing the prior, the fresh set never was. The 34 published sample prompts give the same answers on
both containers, 34 of 34 (SAMPLES.md). All 30 lowercase place names in a test list now arrive whole, against 25 before;
across the repository's own documents 0.064% of tokens still fall outside the table, all of them markup fragments.

## What was tried and not shipped

Fine-tuning the model to copy the new rows reaches 58 to 60 of 60 on recall in about two minutes of training, and every
such run lost something else through the kernel: the program machine stopped being called, or eight-item sorts broke, or
seven-digit operands were mis-copied, depending on the mix. Scaling the update down to 0.7 and replaying the model's own
verified answers narrowed the damage but never to zero on the published samples. The rule of this repository is no
regression on a published number, so the shipped v1.1 is the raised prior alone. The fine-tune kit gained 32-bit rows,
a data-order seed and a parameter filter along the way.
