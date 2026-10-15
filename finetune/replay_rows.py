"""Replay rows: the shipped model's own answers, through the kernel, as training rows, so an adapter keeps what the base does.

    python finetune/replay_rows.py --out replay.u32 [--n 600] [--exe kernel]

The prompts are the shapes the published samples cover (identity, small talk, knowledge, arithmetic, chained arithmetic,
units, percent, average, dates, weekdays, letters, words, largest, sort, days between, count above, programs, records, one
two-turn exchange), with fresh numbers each time. Each row is the prompt plus what the kernel generated; a record prompt
gets the frame the runtime injected, rebuilt from the quote line. The trainer's weighting then zeroes the forced tokens.
Rows whose trace has no answer block are dropped.
"""
import argparse, os, sys, random, subprocess, tempfile, pathlib, re
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tokenizer"))
from shadow_runtime import Engine
from enc_v2 import get, SP
E = get(); MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
NOTES = [l.strip() for l in open(ROOT / "examples_notes.txt", encoding="utf-8") if l.strip()]


def prompts(r):
    d1, d2 = r.randrange(10 ** 5, 10 ** 7), r.randrange(10 ** 5, 10 ** 7); a, b = r.randrange(100, 999), r.randrange(10, 99)
    xs = r.sample(range(3, 20000), 6); ys = r.sample(range(3, 600), 8); m1, m2 = sorted(r.sample(range(1, 13), 2))
    return [
        r.choice(["Who are you?", "What can you do?", "Are you connected to the internet?", "Hello.", "Thank you.", "I feel tired today.", "Tell me a short joke about computers."]),
        r.choice(["What is the capital of Japan?", "What is the largest planet in the solar system?", "Who wrote Romeo and Juliet?", "What is the capital of France?", "Who painted the Mona Lisa?"]),
        f"What is {d1} + {d2}?", f"Compute {max(d1, d2)} - {min(d1, d2)}.", f"What is {a} times {b}?", f"What is {a * b} divided by {b}?",
        f"Take {r.randrange(50, 500)}, add {r.randrange(10, 99)}, subtract {r.randrange(5, 40)}, multiply by {r.randrange(2, 5)}, then add {r.randrange(1, 20)}. What do you get?",
        f"Convert {r.randrange(5, 300)} kg to lb.", f"How many miles are {r.randrange(10, 900)} km?", f"How many minutes are in {r.randrange(2, 30)} hours?",
        f"Convert {r.randrange(-20, 45)} degrees Celsius to Fahrenheit.", f"What is {r.choice([5, 10, 15, 20, 25, 50])} percent of {20 * r.randrange(2, 200)}?",
        f"What is the average of {ys[0]}, {ys[1]} and {ys[2]}?", f"What date is {r.randrange(5, 120)} days after {MON[m1 - 1]} {r.randrange(1, 28)}, 2026?",
        f"What day of the week is {MON[m2 - 1]} {r.randrange(1, 28)}, 2026?", f"How many times does the letter {r.choice('aeinrst')} appear in the word {r.choice(['mississippi', 'strawberry', 'banana', 'committee', 'assessment'])}?",
        f"How many words are in the sentence \"{r.choice(['the quick brown fox jumps over the lazy dog', 'she sells sea shells', 'a stitch in time saves nine', 'all that glitters is not gold'])}\"?",
        f"Which is the largest: {', '.join(map(str, xs))}?", f"Sort these from smallest to largest: {', '.join(map(str, ys))}.",
        f"How many days are there between {MON[m1 - 1]} {r.randrange(1, 28)} and {MON[m2 - 1]} {r.randrange(1, 28)}?",
        f"How many letters are in the word {r.choice(['strawberry', 'bookkeeper', 'committee', 'umbrella', 'rhythm'])}?",
        f"How many of these numbers are greater than 50: {', '.join(map(str, r.sample(range(1, 100), 5)))}?",
        r.choice([f"What is the {r.randrange(8, 25)}th Fibonacci number, counting 1, 1, 2, 3, ...?", f"What is the greatest common divisor of {12 * r.randrange(2, 12)} and {12 * r.randrange(2, 12)}?",
                  f"Is {r.choice([89, 91, 97, 101, 111, 113, 121, 127])} a prime number? Answer yes or no.", f"What is the smallest prime number greater than {r.randrange(20, 120)}?",
                  f"How many prime numbers are there below {r.randrange(20, 80)}?"]),
        r.choice(["What is the count of Vault-418?", "What is the temperature in C of Sample C-2048?", "What is the count of Tank-777?", "Look up the weight of Parcel H240915 and give it in pounds.",
                  "What is the dog name of User SK?", "What is the condition of User SK?"]),
    ]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--n", type=int, default=600); ap.add_argument("--exe", default=None); ap.add_argument("--seed", type=int, default=5)
    a = ap.parse_args(); r = random.Random(a.seed); os.environ.pop("LORA", None)
    arch = os.path.join(tempfile.mkdtemp(prefix="replay_"), "archive")
    subprocess.run([sys.executable, str(ROOT / "shadow_archive.py"), "build", str(ROOT / "examples_notes.txt"), arch], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    e = Engine(kernel=a.exe, archive=arch); buf = []; kept = 0; dropped = 0
    while kept < a.n:
        for q in prompts(r):
            e.history = []; ans = e.chat(q); ids = e.last["ids"]
            if not ids or (SP["sol"] not in ids and SP["endsol"] not in ids): dropped += 1; continue
            if ids.count(SP["calc"]) != ids.count(SP["ecalc"]) or ids.count(SP["vm"]) != ids.count(SP["evm"]): dropped += 1; continue   # cut off at the generation limit
            if ids[0] not in (SP["think"], SP["sol"]): ids = [SP["think"] if SP["endthink"] in ids else SP["sol"]] + ids   # the one-shot stream drops the first generated token
            pids = e.prompt_ids(q); frame = []
            m = re.search(r"\[quote\]pos=(\d+): ([^\n]*)", e.last["trace"])
            if m: frame = [SP["copen"]] + E.plain(f"pos={m.group(1)}\n{m.group(2).strip()}", strict=False) + [SP["cclose"]]
            if SP["think"] in ids and frame: k = ids.index(SP["think"]) + 1; ids = ids[:k] + frame + ids[k:]
            elif frame: ids = [SP["think"]] + frame + ids
            row = pids + ids
            if row[-1] != SP["eot"]: row.append(SP["eot"])
            buf += row; kept += 1
        # the two-turn exchange
        x, y, z = r.randrange(10, 60), r.randrange(10, 60), r.randrange(2, 6); e.history = []; e.chat(f"What is {x} + {y}?"); e.chat(f"Now multiply that by {z}.", remember=1)
        ids = e.last["ids"]
        if ids and ids[0] not in (SP["think"], SP["sol"]): ids = [SP["think"] if SP["endthink"] in ids else SP["sol"]] + ids
        if ids: pids = e.prompt_ids(f"Now multiply that by {z}.", e.history[-2:-1]); buf += pids + ids + ([SP["eot"]] if ids[-1] != SP["eot"] else []); kept += 1
    np.array(buf, dtype=np.uint32).tofile(a.out); print(f"{kept} replay rows, {dropped} dropped, {len(buf)} tokens -> {a.out}")


if __name__ == "__main__": main()
