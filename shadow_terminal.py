"""SHADOW 50M terminal: chat with the model, watch the chip work.

    python shadow_terminal.py                          # the model from this repository
    python shadow_terminal.py --archive my_notes       # with memory on disk (built with shadow_archive.py)

A diagram of the SHADOW chip lights up the parts each answer used (the ternary body, a circuit lane, the program
machine, the archive fetch), and a panel shows what the kernel measured for that answer: tokens, speed, resident RAM,
the microseconds per token in each stage, the hot window, and the memory on disk. Every number comes from the kernel's
own report for the turn; nothing is estimated. With an archive attached, a second panel reads the engram index back
from disk after every turn: records as nodes, the key n-grams that point at them as links, the weight on each link,
and in yellow the link a confirmed fetch just made heavier (the kernel writes that into index.bin itself).

The hot window keeps the last 10 exchanges by default, as the browser page does, so "what is my name?" works turns
later. It has a cost, measured on a ten-turn script with an archive on: a question shaped like the one before it can
reuse that answer (a sort right after a weekday question came back "Saturday"), and "no record" for an absent key
held only with the window empty. `/remember 0` makes every message standalone.

Best at 120 columns or wider. Keys: Enter sends, Ctrl+T shows or hides the working trace, Ctrl+L clears, Ctrl+Q quits.
Commands: /archive <dir>  /remember <n>  /clear  /quit
"""
import argparse, os, re, sys, time, pathlib
from rich.text import Text
from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static
from textual import work

HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
from shadow_runtime import Engine, SP
from shadow_runtime.index_view import IndexView

LANES = ("calc", "cal", "dow", "unit", "pct", "count", "cmp")
IDLE, LIT, HOT = "grey50", "bold bright_green", "bold yellow"

# the chip, row by row: plain text and (text, stage) pieces; a stage lights when the turn used it
CHIP = [
    [" ", ("TOKENIZER", "tok"), " ─▶ ", ("EMBED", "embed"), " ─▶ ┌ ", ("BODY ×6", "body"), " ──────────────────────┐ ─▶ ", ("READOUT", "readout"), " ─▶ answer"],
    [" 73,880 pcs   512-bit  │ ", ("ATTN 14q·2kv·hd64", "attn"), " │ ", ("FFN 2464", "ffn"), " │    + unigram prior"],
    ["              frozen   │ ternary 1.58 b/w  │ SiLU     │"],
    ["                       └────────┬──────────┴──────────┘"],
    ["                ", ("HOT KV, RAM", "hot"), " ◀───┴───▶ ", ("COLD KV 1-bit, disk, 288 B/token", "cold")],
    [" ", ("CIRCUITS", "circuits"), " ", ("[calc]", "calc"), ("[cal]", "cal"), ("[dow]", "dow"), ("[unit]", "unit"), ("[pct]", "pct"), ("[count]", "count"), ("[cmp]", "cmp"),
     "  ", ("SASM VM", "vm"), "  ", ("ARCHIVE", "archive"), " ─▶ fetch"],
]


def render_chip(lit, hot):
    t = Text(no_wrap=True, overflow="crop")
    for row in CHIP:
        for piece in row:
            if isinstance(piece, str): t.append(piece, style="grey35")
            else:
                s, k = piece; t.append(s, style=HOT if k in hot else LIT if k in lit else IDLE)
        t.append("\n")
    return t


def stages_of(trace, fetches):
    """which parts of the chip an answer used, read off the trace the model wrote"""
    lit = {"tok", "embed", "body", "attn", "ffn", "readout", "hot"}; hot = set()
    m = re.search(r"\[calc\]([a-z]+):", trace)
    if "[calc]" in trace: hot |= {"circuits", m.group(1) if m and m.group(1) in LANES else "calc"}
    if "[vm]" in trace or "[run]" in trace: hot.add("vm")
    if "[quote]" in trace or "[need]" in trace: hot |= {"archive", "cold"}     # the model asked its memory (the kernel probes the index on every prompt; that alone is not a use)
    return lit, hot


def archive_files(d):
    out = {}
    for f in ("tokens.bin", "index.bin", "kv.bin"):
        p = os.path.join(d, f); out[f] = os.path.getsize(p) if os.path.exists(p) else 0
    return out


class ShadowTerminal(App):
    CSS = """
    #chip { height: 8; border: round $secondary; padding: 0 1; }
    #index { height: 9; border: round $warning; padding: 0 1; }
    #log { border: round $primary; }
    #panel { width: 40; border: round $accent; padding: 0 1; }
    #ask { dock: bottom; }
    """
    BINDINGS = [("ctrl+t", "trace", "trace"), ("ctrl+l", "clear", "clear"), ("ctrl+q", "quit", "quit")]

    def __init__(self, engine, gen, remember):
        super().__init__(); self.eng = engine; self.gen = gen; self.remember = remember; self.show_trace = False
        self.turns = 0; self.tokens = 0; self.seconds = 0.0; self.busy = False; self.lit = set(); self.hot = set(); self.last_prompt = 0; self.view = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical():
                yield Static(render_chip(set(), set()), id="chip")
                yield Static(Text(" engram index: no archive. /archive <dir> attaches memory on disk; every confirmed fetch adds one to the link the question took.", style="grey50"), id="index")
                yield RichLog(id="log", wrap=True, markup=False, highlight=False)
                yield Input(placeholder="ask SHADOW  (/archive <dir>, /remember <n>, /clear, /quit)", id="ask")
            yield Static(id="panel")
        yield Footer()

    def on_mount(self):
        self.title = "SHADOW 50M"; self.sub_title = os.path.basename(self.eng.kernel) + "  ·  " + os.path.basename(self.eng.model)
        self.query_one("#ask", Input).focus(); self.refresh_panel(); self.refresh_index(first=True)
        self.log_line("SHADOW 50M, a small model. Ask something; the chip above shows what each answer used.", "grey62")

    def log_line(self, text, style=""):
        self.query_one("#log", RichLog).write(Text(text, style=style))

    def refresh_panel(self):
        L = self.eng.last; t = Table.grid(padding=(0, 1)); t.add_column(style="grey62", no_wrap=True); t.add_column(justify="right", no_wrap=True)
        state = "● running" if self.busy else "○ idle"; t.add_row("state", Text(state, style="bright_green" if self.busy else "grey50"))
        t.add_row("turns", str(self.turns)); t.add_row("prompt tokens", f"{self.last_prompt:,}"); t.add_row("answer tokens", f"{len(L.get('ids', [])):,}")
        t.add_row("session tokens", f"{self.tokens:,}")
        t.add_row("speed, last", f"{L.get('tok_s', 0):,.0f} tok/s"); t.add_row("speed, session", f"{self.tokens / self.seconds:,.0f} tok/s" if self.seconds else "")
        t.add_row("resident RAM", f"{L.get('rss_mb', 0):.1f} MB")
        t.add_row("", ""); t.add_row(Text("per token, µs", style="bold"), "")
        prof = L.get("profile", {}); tot = sum(prof.values()) or 1
        for k in ("tern", "att", "readout", "quant", "other"):
            v = prof.get(k, 0); t.add_row(f"  {k}", Text(f"{'█' * int(round(8 * v / tot)):<8} {v:4.0f}", style="bright_green"))
        t.add_row("", ""); t.add_row(Text("hot window, RAM", style="bold"), "")
        t.add_row("  exchanges kept", str(min(self.remember, len(self.eng.history)))); t.add_row("  tokens in prompt", f"{self.last_prompt:,}")
        t.add_row("  1-bit state", f"{self.last_prompt * 288 / 1024:,.1f} KB"); t.add_row("  capacity", "8,192 tokens")
        t.add_row("", ""); t.add_row(Text("memory on disk", style="bold"), "")
        if self.eng.archive:
            f = archive_files(self.eng.archive); n = f["tokens.bin"] // 4
            t.add_row("  archive", os.path.basename(self.eng.archive)); t.add_row("  tokens", f"{n:,}")
            t.add_row("  kv.bin, 1-bit", f"{f['kv.bin'] / 1e6:,.2f} MB"); t.add_row("  index.bin", f"{f['index.bin'] / 1e6:,.2f} MB")
            t.add_row("  fetches, last", f"{L.get('fetches', 0)} × {L.get('fetch_ms', 0):.2f} ms")
        else: t.add_row("  none", Text("/archive <dir>", style="grey50"))
        self.query_one("#panel", Static).update(t)

    def refresh_index(self, first=False):
        """the engram index read back from disk: the links the kernel just nudged, then the most trodden records"""
        if not self.eng.archive: return
        try:
            if self.view is None or self.view.dir != self.eng.archive: self.view = IndexView(self.eng.archive, self.eng.enc, os.path.dirname(self.eng.model))
            if not first: self.view.turn()
            self.query_one("#index", Static).update(self.view.render(rows=7))
        except Exception as ex: self.query_one("#index", Static).update(Text(f" engram index: {ex}", style="red"))

    def action_trace(self):
        self.show_trace = not self.show_trace; self.log_line(f"trace {'shown' if self.show_trace else 'hidden'}", "grey50")

    def action_clear(self):
        self.query_one("#log", RichLog).clear(); self.eng.history = []; self.lit = self.hot = set(); self.query_one("#chip", Static).update(render_chip(set(), set()))

    def on_input_submitted(self, ev: Input.Submitted):
        q = ev.value.strip(); ev.input.value = ""
        if not q or self.busy: return
        if q.startswith("/"):
            cmd, _, arg = q[1:].partition(" ")
            if cmd == "quit": self.exit()
            elif cmd == "clear": self.action_clear()
            elif cmd == "remember" and arg.isdigit(): self.remember = int(arg); self.log_line(f"remember {arg} exchanges", "grey50")
            elif cmd == "archive":
                d = os.path.abspath(os.path.expanduser(arg))
                if os.path.exists(os.path.join(d, "kv.bin")): self.eng.archive = d; self.log_line(f"archive {d}", "grey50"); self.view = None; self.refresh_index(first=True)
                else: self.log_line(f"no kv.bin in {d}", "red")
            else: self.log_line("commands: /archive <dir>  /remember <n>  /clear  /quit", "grey50")
            self.refresh_panel(); return
        self.log_line("you> " + q, "bold"); self.busy = True; self.refresh_panel(); self.ask(q)

    @work(thread=True)
    def ask(self, q):
        t0 = time.perf_counter()
        ids = self.eng.prompt_ids(q, self.eng.history[-self.remember:] if self.remember else ())
        ans = self.eng.chat(q, gen=self.gen, remember=self.remember); dt = time.perf_counter() - t0
        L = self.eng.last; m = re.search(r"PROFILE per-tok us: tern (\d+) \| att (\d+) \| readout (\d+) \| quant (\d+) \| other (\d+)", L.get("raw", ""))
        L["profile"] = dict(zip(("tern", "att", "readout", "quant", "other"), map(int, m.groups()))) if m else {}
        self.call_from_thread(self.done, q, ans, ids, dt)

    def done(self, q, ans, ids, dt):
        L = self.eng.last; n = len(L.get("ids", [])); gen_s = n / L["tok_s"] if L.get("tok_s") else 0
        self.turns += 1; self.tokens += n; self.seconds += gen_s; self.last_prompt = len(ids); self.busy = False
        self.lit, self.hot = stages_of(L.get("trace", ""), L.get("fetches", 0))
        self.query_one("#chip", Static).update(render_chip(self.lit, self.hot))
        if self.show_trace:
            tr = L.get("trace", ""); tr = tr.split("[sol]")[0] if "[sol]" in tr else tr.split("[endthink]")[0] if "[endthink]" in tr else ""   # the one-shot stream drops the leading [sol] of a plain answer
            tr = tr.replace("[endthink]", "").strip()
            if tr: self.log_line("     " + tr, "grey50")
        used = ", ".join(sorted(self.hot - {"circuits", "cold"})) or "body only"
        self.log_line("shadow> " + (ans or "(no answer)"), "bright_green")
        self.log_line(f"        {n} tokens · {L.get('tok_s', 0):,.0f} tok/s · {L.get('rss_mb', 0):.0f} MB · {used} · {dt * 1000:.0f} ms wall", "grey50")
        self.refresh_panel(); self.refresh_index()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--archive", default=None); ap.add_argument("--remember", type=int, default=10, help="exchanges kept in the hot window")
    ap.add_argument("--gen", type=int, default=220); ap.add_argument("--topk", type=int, default=1); a = ap.parse_args()
    eng = Engine(archive=a.archive, topk=a.topk); ShadowTerminal(eng, a.gen, a.remember).run()


if __name__ == "__main__": main()
