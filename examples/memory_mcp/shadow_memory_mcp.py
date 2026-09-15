"""SHADOW 50M as a memory server for another model: an MCP server with two tools, remember and recall.

    python examples/memory_mcp/shadow_memory_mcp.py --store ~/shadow_memory            # stdio MCP server

Any client that speaks MCP can manage this memory: a CLI agent, an editor, or the Qwen loop in agent.py next to this
file. `remember` writes one record into SHADOW's archive on disk; `recall` asks SHADOW, which finds the record, quotes it
with its position and answers, or says there is no record. Nothing leaves the machine: the archive is three files in
--store, the kernel runs on the CPU in about 40 MB.

Records work best in the shape the index finds: an identifier and an attribute word, "User A1 city: Sydney." The agent
is told so in the tool description, and most models write it that way when asked.
"""
import argparse, os, pathlib, subprocess, sys, threading
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tokenizer"))
from shadow_runtime import Engine                    # imported here, before the server starts: a first import inside a tool call stalled on Windows


class Store:
    """the records file and the archive built from it; rebuilt after every remember (fast: 0.4 ms a token)"""
    def __init__(self, path):
        self.dir = pathlib.Path(path).expanduser(); self.dir.mkdir(parents=True, exist_ok=True)
        self.notes = self.dir / "records.txt"; self.arch = self.dir / "archive"; self.lock = threading.Lock(); self.engine = None
        if self.notes.exists() and not (self.arch / "kv.bin").exists(): self.rebuild()

    def rebuild(self):
        if self.notes.exists() and self.notes.stat().st_size:
            subprocess.run([sys.executable, str(ROOT / "shadow_archive.py"), "build", str(self.notes), str(self.arch)], capture_output=True, check=True, stdin=subprocess.DEVNULL)
        self.engine = None

    def remember(self, text):
        line = " ".join(text.split()).rstrip(".") + "."
        with self.lock:
            with self.notes.open("a", encoding="utf-8") as f: f.write(line + "\n")
            self.rebuild(); n = sum(1 for _ in self.notes.open(encoding="utf-8"))
        return f"remembered ({n} records on disk): {line}"

    def recall(self, question):
        with self.lock:
            if not (self.arch / "kv.bin").exists(): return "no records yet"
            if self.engine is None:
                self.engine = Engine(archive=str(self.arch), topk=3)   # three candidate records into attention: 5 of 6 attributes under one key, against 2 to 4 with one (measured)
            a = self.engine.chat(question, remember=False); tr = self.engine.last["trace"].split("[sol]")[0].strip()
            quote = next((l for l in tr.splitlines() if l.startswith("[quote]")), "")
            return a + (f"\n({quote.replace('[quote]', 'record ')})" if quote else "") + f"\n[{self.engine.stats()}]"

    def list(self):
        return self.notes.read_text(encoding="utf-8") if self.notes.exists() else ""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--store", default="~/shadow_memory"); a = ap.parse_args()
    from mcp.server.fastmcp import FastMCP
    store = Store(a.store); mcp = FastMCP("shadow-memory")

    @mcp.tool()
    def remember(fact: str) -> str:
        """Store one fact in long-term memory on disk. Write it as one line with an identifier and ONE attribute word, like
        'User A1 city: Sydney.', 'User A1 dog: Bruno.', 'User A1 condition: peanut allergy.' or 'Order 4471 status: shipped.', so it
        can be found later by that identifier and attribute. Use 'User A1' for the person you are talking to. One call per fact."""
        return store.remember(fact)

    @mcp.tool()
    def recall(question: str) -> str:
        """Ask long-term memory a question that names the identifier and the attribute, like 'What is the city of User A1?'.
        Returns the answer with the record it was read from, or 'no record' if nothing was stored about it."""
        return store.recall(question)

    @mcp.tool()
    def list_records() -> str:
        """Return every record in long-term memory, one per line."""
        return store.list() or "(empty)"

    mcp.run(transport="stdio")


if __name__ == "__main__": main()
