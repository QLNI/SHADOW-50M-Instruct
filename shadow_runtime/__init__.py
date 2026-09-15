"""shadow_runtime: a thin Python wrapper around the SHADOW 50M kernel binary.

    from shadow_runtime import Engine
    eng = Engine()                                   # model + kernel from this repository
    print(eng.chat("What is 347 times 86?"))         # -> "29842"
    eng = Engine(archive="path/to/archive")          # an archive built with shadow_archive.py
    print(eng.chat("What is the count of Vault-418?"))

Everything the model does happens inside the kernel binary: the ternary body, the frozen circuits, the program machine,
the 1-bit archive attention. This module only encodes the prompt, runs the binary, and decodes the ids it prints.
"""
import os, re, sys, platform, subprocess, tempfile, pathlib
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tokenizer"))
from enc_v2 import get as _get_encoder, SP, OFF   # noqa: E402


def default_kernel():
    osname = platform.system()
    if osname == "Windows": return HERE / "deployment" / "bin" / "windows" / "shadow50.exe"
    if osname == "Linux":
        k = HERE / "deployment" / "bin" / "linux" / "shadow50"; os.chmod(k, 0o755); return k
    sys.exit("macOS build available on request: saikiranbathula1@gmail.com")


class Engine:
    def __init__(self, model=None, kernel=None, archive=None, topk=1, read_head=4, sparse=2, workdir=None, remember=0):
        self.model = str(model or HERE / "deployment" / "shadow50_instruct.shdw"); self.kernel = str(kernel or default_kernel())
        self.archive = os.path.abspath(archive) if archive else None; self.topk = topk; self.read_head = read_head; self.sparse = sparse; self.remember = remember
        self.enc = _get_encoder(); self.history = []
        self.workdir = workdir or tempfile.mkdtemp(prefix="shadow50_"); self.prompt_path = os.path.join(self.workdir, "prompt.bin"); self.last = {}

    def prompt_ids(self, message, history=(), chunks=()):
        conv = [{"u": u, "a": a} for u, a in history] + [{"u": message, "a": ""}]
        ids, _ = self.enc.turns(conv, chunks=list(chunks), strict=False)
        cut = len(ids) - 1 - ids[::-1].index(SP["sot"])            # turns() closes with an empty model turn:
        return ids[:cut] + [SP["sot"]] + self.enc.plain("model\n")   # cut at the last [sot], else it doubles

    def run(self, ids, gen=220, cold=False):
        np.array(ids, dtype=np.int32).tofile(self.prompt_path)
        env = dict(os.environ, SHADOW_PROMPT=self.prompt_path, READ_HEAD=str(self.read_head), SPARSE=str(self.sparse), AX_TOPK=str(self.topk))
        env.pop("COLD", None); env.pop("ARCHIVE", None)
        if cold: env["COLD"] = "1"
        if self.archive: env["ARCHIVE"] = self.archive
        out = subprocess.run([self.kernel, self.model, str(gen)], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL).stdout
        gids = [int(x) for x in re.search(r"IDS:(.*)", out).group(1).split()] if "IDS:" in out else []
        g = lambda pat: (re.search(pat, out) or [None, None])[1]
        self.last = {"ids": gids, "trace": self.enc.dec(gids), "tok_s": float(g(r"-> ([\d.]+) tok/s") or 0), "fetch_ms": float(g(r"FETCH n=\d+ mean ([\d.]+) ms") or 0),
                     "fetches": int(g(r"FETCH n=(\d+)") or 0), "rss_mb": float(g(r"PEAK_RSS ([\d.]+) MB") or 0) or (int(g(r"MEM VmRSS:\s+(\d+) kB") or 0) / 1024), "raw": out}
        return gids

    @staticmethod
    def answer_of(ids, dec):
        if SP["sol"] in ids:
            s = ids.index(SP["sol"]) + 1; e = ids.index(SP["endsol"]) if SP["endsol"] in ids else len(ids)
            return dec([t for t in ids[s:e] if t >= OFF]).strip()
        return dec([t for t in ids if t >= OFF]).strip()

    def chat(self, message, gen=220, remember=None, chunks=()):
        """one turn. With remember=N the last N exchanges stay in the hot window ("now multiply that by 4"); the default is
        standalone messages, because earlier operands in the window can be reused by mistake (measured)."""
        n = self.remember if remember is None else remember
        ids = self.prompt_ids(message, self.history[-n:] if n else (), chunks); gids = self.run(ids, gen, cold=bool(chunks))
        ans = self.answer_of(gids, self.enc.dec)
        self.history.append((message, ans)); self.history = self.history[-max(n, 6):]   # keep at least what --remember asks for
        return ans

    def stats(self):
        L = self.last; s = f"{L.get('tok_s', 0):.0f} tok/s, {L.get('rss_mb', 0):.0f} MB RSS"
        if self.archive: s += f", fetch {L.get('fetch_ms', 0):.2f} ms x{L.get('fetches', 0)}"
        return s
