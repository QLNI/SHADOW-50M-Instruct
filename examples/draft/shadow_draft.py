"""SHADOW 50M as the draft model in front of a llama.cpp target: same text, fewer target steps.

    python examples/draft/shadow_draft.py --target Qwen3.8-27B-Q8_0.gguf --tokenizer Qwen/Qwen3.8-27B --prompts prompts.txt [--k 5] [--gpu-layers 99]

Speculative decoding, greedy on both sides. SHADOW proposes k tokens per round through the kernel's server mode (one process,
the model loaded once, the hot cache kept across rounds); the target verifies them in one batched step through llama.cpp and
keeps the longest agreeing prefix plus one token of its own. The target's output is identical to running it alone, token for
token, because a proposal is only kept where the target's own argmax equals it. The two models share nothing: proposals are
carried into the target's vocabulary through a table built once from the two tokenizers (a string lookup; where no single
counterpart exists the string's own tokenization is used).

Needs: llama-cpp-python (with CUDA for a large target), the release's kernel and container, and the target's Hugging Face
tokenizer for the cross-vocabulary table. Prints, per prompt and overall: target alone tok/s, with the draft tok/s, the
acceptance rate, the mean accepted run, how many tokens of the two texts differ and at how many positions the target's one-token step disagrees with
its batched step (llama.cpp's two paths differ in the last bits, so a near tie can go either way; after one, the texts part).
"""
import argparse, os, re, subprocess, sys, time, pathlib, platform
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tokenizer")); from enc_v2 import get, SP
E = get(); OFF = 32


class Draft:
    """the kernel in server mode: prompt ids in, k greedy ids out, about 5 ms a round on a laptop"""
    def __init__(self, exe, shdw):
        self.p = subprocess.Popen([exe, shdw, "0"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, env=dict(os.environ, SERVER="1", NOPIN="1"))
    def propose(self, ids, k):
        self.p.stdin.write(f"{k} {len(ids)} " + " ".join(map(str, ids)) + "\n"); self.p.stdin.flush(); out = []
        while True:
            l = self.p.stdout.readline()
            if not l: raise RuntimeError("draft kernel exited")
            if l.startswith("IDS:"): out = [int(x) for x in l[4:].split()]
            if l.startswith("END"): return out
    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception: pass


def cross_map(tok):
    """our id -> the target's ids for the same string (one, or the string's own tokenization); built once, a few seconds"""
    inv = {}
    for s, i in tok.get_vocab().items(): inv.setdefault(tok.convert_tokens_to_string([s]), i)
    out = [None] * (len(E.n2o) + OFF); exact = 0
    for t in range(OFF, len(out)):
        s = E.dec([t])
        if not s: out[t] = []; continue
        if s in inv: out[t] = [inv[s]]; exact += 1
        else: out[t] = tok(s, add_special_tokens=False).input_ids
    return out, exact


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--target", required=True); ap.add_argument("--tokenizer", required=True); ap.add_argument("--prompts", default=None)
    ap.add_argument("--k", type=int, default=5); ap.add_argument("--tokens", type=int, default=128); ap.add_argument("--gpu-layers", type=int, default=0); ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--exe", default=None); ap.add_argument("--shdw", default=str(ROOT / "deployment" / "shadow50_instruct.shdw")); ap.add_argument("--threads", type=int, default=None)
    a = ap.parse_args()
    import llama_cpp; from llama_cpp import Llama
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    exe = a.exe or str(ROOT / "deployment" / "bin" / ("windows/shadow50.exe" if platform.system() == "Windows" else "linux/shadow50"))
    print(f"target {os.path.basename(a.target)}, {a.gpu_layers} layers on the GPU; draft {os.path.basename(exe)} + {os.path.basename(a.shdw)}", flush=True)
    llm = Llama(model_path=a.target, n_ctx=a.ctx, n_gpu_layers=a.gpu_layers, logits_all=True, verbose=False, n_threads=a.threads, swa_full=True)   # a full cache for sliding-window layers, so a rejected proposal can be rolled back
    cross, exact = cross_map(tok); print(f"cross-vocabulary table: {exact} of {len(cross) - OFF} tokens one-to-one", flush=True)
    draft = Draft(exe, a.shdw)
    prompts = [l.strip() for l in open(a.prompts, encoding="utf-8") if l.strip()] if a.prompts else ["The capital of France is", "Once upon a time, in a small village,", "The three laws of thermodynamics are"]

    def logits_at(pos): return np.asarray(llm.scores[pos], dtype=np.float32)

    def fresh():
        """an empty context: position counter to zero and the cache cleared (reset() alone leaves the cells occupied on a GPU)"""
        llm.n_tokens = 0; llama_cpp.llama_memory_clear(llama_cpp.llama_get_memory(llm._ctx.ctx), True)

    def run_alone(t_ids, n):
        fresh(); llm.eval(t_ids); out = []; t0 = time.perf_counter()
        for _ in range(n):
            nxt = int(np.argmax(logits_at(llm.n_tokens - 1))); out.append(nxt); llm.eval([nxt])
            if nxt == tok.eos_token_id: break
        return out, time.perf_counter() - t0

    def run_drafted(t_ids, n):
        fresh(); llm.eval(t_ids); out = []; t0 = time.perf_counter(); rounds = 0; accepted = 0; proposed = 0; runs = []
        cache_text = ""; cache_ours = []; pending = []                         # the target's own last token, not yet in its cache: it goes in with the next proposal, one target step per round
        while len(out) < n:
            # our view of the sequence: through text, the prefix re-encoded only when the text stops extending it
            text = tok.decode(t_ids + out)
            if cache_text and text.startswith(cache_text): ours = cache_ours + (E.plain(text[len(cache_text):], strict=False) if len(text) > len(cache_text) else [])
            else: ours = E.plain(text, strict=False)
            cache_text, cache_ours = text, ours
            prop_ours = draft.propose([SP["bos"]] + ours[-1000:], a.k)         # plain text after [bos], the form pretraining saw; the kernel's prompt holds 1024 ids
            cand = []
            for o in prop_ours:
                if o < OFF: break                                              # a symbol (end of turn, a span) ends the proposal
                cand += cross[o]
                if len(cand) >= a.k: break
            cand = cand[:a.k]; rounds += 1; proposed += len(cand)
            base = llm.n_tokens; off = len(pending)                             # logits at base+off-1 predict the first candidate
            llm.eval(pending + cand)
            keep = 0; nxt = None
            for j in range(len(cand) + 1):
                pred = int(np.argmax(logits_at(base + off - 1 + j)))
                if j < len(cand) and pred == cand[j]: keep += 1
                else: nxt = pred; break
            accepted += keep; runs.append(keep)
            llm.n_tokens = base + off + keep                                    # roll the cache back to the accepted prefix (sequence 0, positions from n_tokens on)
            llama_cpp.llama_memory_seq_rm(llama_cpp.llama_get_memory(llm._ctx.ctx), 0, llm.n_tokens, -1)
            out += cand[:keep] + [nxt]; pending = [nxt]
            if tok.eos_token_id in out: out = out[:out.index(tok.eos_token_id) + 1]; break
        return out[:n], time.perf_counter() - t0, rounds, accepted, proposed, runs

    def flips(t_ids, o2):
        """positions where the target, stepping one token at a time over the drafted text, would have chosen differently:
        llama.cpp's one-token and batched paths differ in the last bits, so a near tie can go either way (its own speculative example has the same property)"""
        fresh(); llm.eval(t_ids); k = 0
        for t in o2:
            k += int(np.argmax(logits_at(llm.n_tokens - 1))) != t; llm.eval([t])
        return k

    tot_alone = tot_draft = 0.0; n_alone = n_draft = 0; same = 0; diff_tok = 0; n_flip = 0; acc = 0; prop = 0; all_runs = []; rounds_all = 0
    for p in prompts:
        t_ids = tok(p, add_special_tokens=False).input_ids
        o1, dt1 = run_alone(t_ids, a.tokens); o2, dt2, rounds, accepted, proposed, runs = run_drafted(t_ids, a.tokens)
        o2 = o2[:len(o1)]; nd = sum(x != y for x, y in zip(o1, o2)) + abs(len(o1) - len(o2)); same += nd == 0; diff_tok += nd; fl = flips(t_ids, o2); n_flip += fl
        tot_alone += dt1; tot_draft += dt2; n_alone += len(o1); n_draft += len(o2); acc += accepted; prop += proposed; all_runs += runs; rounds_all += rounds
        print(f"  {p[:40]!r:44} alone {len(o1) / dt1:6.1f} tok/s | drafted {len(o2) / dt2:6.1f} tok/s | {len(o2)} tokens in {rounds} target steps | {nd} tokens differ, {fl} near-tie flips", flush=True)
    print(f"\ntarget alone: {n_alone / tot_alone:.1f} tok/s;  with SHADOW drafting: {n_draft / tot_draft:.1f} tok/s;  speedup {tot_alone / n_alone / (tot_draft / n_draft):.2f}x")
    print(f"acceptance {acc / max(1, prop):.3f} ({acc} of {prop} proposed), mean accepted run {np.mean(all_runs):.2f}, tokens per target step {n_draft / max(1, rounds_all):.2f}; identical text on {same}/{len(prompts)} prompts, {diff_tok} of {n_alone} tokens differ after {n_flip} near-tie flips")
    draft.close()


if __name__ == "__main__": main()
