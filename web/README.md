# SHADOW 50M in a browser

The same C kernel, compiled to WebAssembly, and a chat page around it. Bit-exact: on load the page runs the container's
own self-test and prints `GOLDEN 8/8`, the same check the desktop kernel makes. Everything happens in the tab: the
model is fetched once, the question is tokenised in the page, the kernel runs, the digits after `[eq]` come out of the
circuits in the model. No server, nothing sent anywhere.

```
python web/serve.py          # from the repository root
open http://localhost:8000/web/
```

Or put the repository on any static host and open `web/`. The page carries a small service worker that turns on
cross-origin isolation where the host does not, so threads work on GitHub Pages too. Without isolation it falls back
to the single-thread build by itself.

| file | what it is |
|---|---|
| `index.html` | the chat page: tokeniser, prompt layout, kernel, decoding. `?q=...` asks on load, `?st=1` forces one thread |
| `shadow50_web.js` + `.wasm` | the kernel, 7 threads |
| `shadow50_st.js` + `.wasm` | the kernel, one thread, for pages that cannot be cross-origin isolated |
| `transformers.min.js` | the tokeniser (Hugging Face transformers.js 4.2.0, Apache 2.0), checked token for token against the Python encoder on 4,480 lines |
| `coi-serviceworker.min.js` | cross-origin isolation on static hosts (MIT) |
| `serve.py` | a local server that sets the isolation headers |
| `f16shim.h` | software half-precision, since WebAssembly has no F16C instructions |

The page reads the container from `../deployment/` and the tokeniser files from `../tokenizer/`, so nothing is copied.

Measured on this laptop in Chrome, 2026-09-12, standalone questions (a conversation with history in the window is
slower, since the prompt is longer):

| build | threads | decode |
|---|---|---|
| native C | 8 | 2,000 tokens/s |
| WebAssembly | 7 | 450 to 530 tokens/s |
| WebAssembly | 1 | 175 to 195 tokens/s |

Ten prompts through the page gave the same token ids as the desktop kernel, all ten. Each turn runs in a fresh
instance of the module, about 50 ms of overhead. "Remember this conversation" is on by default, so the last ten exchanges
ride along in the window (measured: six loses the name by the ninth turn, ten keeps it); untick it for standalone questions. The wasm module is 155 KB. Everything else is the model.
