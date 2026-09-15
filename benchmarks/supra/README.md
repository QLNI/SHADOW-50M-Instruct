# SHADOW 50M against Supra-50M-Reasoning

[SupraLabs/Supra-50M-Reasoning](https://huggingface.co/SupraLabs/Supra-50M-Reasoning): 51.8M parameters, Llama
architecture, 12 layers, hidden 512, vocabulary 32,000, context 1,024, bf16, trained from scratch on 20B tokens of
fineweb-edu, then fine-tuned on 500 synthetic thinking samples. Apache 2.0. Measured here on 2026-09-15 on one machine,
a GPU for scoring and the CPU for speed. Each script downloads the model from the Hub.

| script | what it measures | result |
|---|---|---|
| `mc_supra.py` | ARC-Easy, PIQA, HellaSwag, WinoGrande; the same 400-item samples and the same continuation scorer as SHADOW's numbers in BENCHMARKS.md | `mc_supra.json` |
| `ppl_supra.py` | WikiText-2 raw test, 1,024 windows, token perplexity on its own tokenizer (293,782 tokens; SHADOW's tokenizer gives about 295k on the same text) | `ppl_supra.json` |
| `quant_ppl.py` | the same perplexity with every Linear quantised: int8 per channel, int4 group 64, ternary absmean | `quant_ppl.json` |
| `gen_supra.py` | the twenty README questions through its own prompt format; greedy with its repetition penalty, and again with its own sampling settings (`--sample`); records given in the prompt | `gen_supra.json`, `gen_supra_sample.json` |

Sizes and speed: the shipped safetensors is 103,584,616 bytes. Converted with llama.cpp's converter (its tokenizer is
not in the converter's list, so the byte-level BPE fallback was used; this affects tokenisation, not the weights or the
speed), the GGUF is 104,740,704 bytes at f16 and 56,203,104 at q8_0. Speed through llama-cpp-python on the CPU,
8 threads, greedy, 256 tokens: 261 tokens a second at f16, 415 at q8_0; through PyTorch on the same CPU, 64.
SHADOW's kernel on the same machine the same day: 1,833 and 1,889 tokens a second on two prompts, 41 MB resident.

Results:

| | acc | acc_norm |
|---|---|---|
| ARC-Easy | 0.435 | 0.385 |
| PIQA | 0.600 | 0.578 |
| HellaSwag | 0.237 | 0.282 |
| WinoGrande | 0.482 | 0.495 |

| weights | WikiText-2 perplexity at 1,024 |
|---|---|
| bf16 | 165.0 |
| int8 per channel | 164.5 |
| int4 group 64 | 192.8 |
| ternary absmean | 27,944 |

Its model card reports PIQA 59.5 and WikiText-2 166.3, which the runs here agree with.

Of the twenty questions it answered one, the capital of Japan. Every arithmetic, date, unit, count and sort question
got fluent text with no answer in it, and the four record questions got text about asthma whether or not the record
existed. The full traces are in the two JSON files.
