# Draft model

![SHADOW 50M drafting for Qwen3-32B in llama.cpp: 19.7 tokens a second alone, 28.5 with the draft, same greedy rule](shadow_draft.gif)

SHADOW proposes the next few tokens, a large model checks them in one batched step and keeps the ones it would have
chosen itself. The large model still decides every token; the small one saves it steps. Speculative decoding, greedy on
both sides, with the two models sharing nothing: proposals cross into the target's vocabulary through a table built once
from the two tokenizers.

    python examples/draft/shadow_draft.py --target Qwen3-32B-Q8_0.gguf --tokenizer Qwen/Qwen3-32B --prompts prompts.txt --k 4 --gpu-layers 99

Needs llama-cpp-python (with CUDA for a target this size), the target's tokenizer from Hugging Face, and the release's
kernel, which runs in server mode: one process, the model loaded once, the hot cache kept from one round to the next, about
5 ms a round on a laptop CPU. The target runs in llama.cpp, so it can be any dense GGUF.

## Measured

One L40 (46 GB), Qwen3-32B in Q8_0 (34.8 GB) with all layers on the GPU, llama-cpp-python 0.3.35, six prompts of 128
tokens each, greedy. "Alone" is the target stepping one token at a time; "drafted" is the same target with SHADOW
proposing k tokens a step.

| prompts | k | alone | drafted | speedup | accepted per proposal | tokens per target step |
|---|---|---|---|---|---|---|
| six paragraphs of a nineteenth-century novel | 2 | 19.7 tok/s | 25.5 tok/s | 1.30x | 0.216 | 1.42 |
| same | 4 | 19.7 tok/s | 25.6 tok/s | 1.30x | 0.132 | 1.51 |
| same | 6 | 19.7 tok/s | 25.4 tok/s | 1.29x | 0.097 | 1.56 |
| six plain openings (a recipe, a letter, a weather note) | 4 | 19.7 tok/s | 28.5 tok/s | 1.44x | 0.177 | 1.68 |

Per prompt the drafted rate ranged from 24.2 to 35.0 tokens a second. The gain comes from the target being bound by
memory traffic on a GPU: checking five tokens in one step costs about what one token costs, so every accepted token is a
step saved. On a CPU the same loop gave no gain with a 0.6B target (a batched step there costs about as much as the
single steps it replaces), so this harness is for a large target on a GPU.

## What the text looks like

A proposal is kept only where the target's own argmax equals it, so the target chooses every token. The text is still not
always the same as the target running alone: llama.cpp evaluates one token and a batch of tokens through different
kernels, which differ in the last bits, and at a near tie the two can pick different tokens. After one such flip the two
texts part. The script counts these by stepping the target one token at a time over the drafted text and noting where it
disagrees: 7 positions in 768 tokens on the novel, 11 in 768 on the plain prompts. llama.cpp's own speculative example
has the same property. The alone run and the drafted run were identical on one prompt in six in each set.

## What did not work

- Qwen3.8-27B, the first target tried, is a hybrid model: a recurrent state plus full attention on every fourth layer.
  llama.cpp cannot roll a recurrent state back to an earlier position, so a rejected proposal cannot be undone, and
  speculative decoding through it is not possible. The target has to be dense (Qwen3-32B is).
- The first loop evaluated the target's own token in a step of its own after each check, two target steps a round, and
  came out slower than the target alone (13.6 tok/s). That token now goes into the next round's batch.
- The kernel's one-shot mode drops the first generated token from its id stream (a chat prompt's first token is a
  symbol, so it was never missed). Server mode emits it; acceptance had been zero without it.

## Files

- `shadow_draft.py`: the loop; the `Draft` class is the kernel's server mode and can be lifted on its own (ids in,
  ids out, one line each way).
- `shadow_draft.gif`: the plain-prompt run above, as it printed.
