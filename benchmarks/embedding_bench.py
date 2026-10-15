"""Benchmark the frozen binary vocabulary on word similarity (WordSim-353).

Every token carries a fixed 512-bit code, and those codes are not trained: they are the same
frozen table the model was built on. If they carry meaning, similar words should have nearby
codes. This reads the table straight out of the shipped container, scores each human-rated word
pair by Hamming similarity between the two words' codes, and reports the Spearman correlation
with the human ratings. Random codes score about zero. Runs offline on the files in this
repository.

    python benchmarks/embedding_bench.py
"""
import struct, sys, pathlib
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tokenizer"))
from enc_v2 import get

CONTAINER = ROOT / "deployment" / "shadow50_instruct.shdw"


def blob(path, want):
    """pull one named blob out of the .shdw: 16-byte header, then name[56] + u64 offset + u64 size"""
    b = path.read_bytes()
    for i in range(struct.unpack_from("<Q", b, 8)[0]):
        o = 16 + i * 72
        if b[o:o + 56].split(b"\0")[0].decode() == want:
            off, size = struct.unpack_from("<QQ", b, o + 56)
            return np.frombuffer(b, dtype=np.uint8, count=size, offset=off)
    raise KeyError(want)


E = get()
fp = np.unpackbits(blob(CONTAINER, "table_packed.bin").reshape(-1, 64), axis=1)[:, :512]
rows = [l.split(",") for l in open(HERE / "wordsim353.csv", encoding="utf-8").read().splitlines() if l]
rand = np.random.default_rng(0).integers(0, 2, size=fp.shape).astype(np.uint8)


def score(table):
    xs, ys = [], []
    for w1, w2, human in rows:
        i1 = E.plain(" " + w1.lower(), strict=False); i2 = E.plain(" " + w2.lower(), strict=False)
        if len(i1) != 1 or len(i2) != 1: continue
        xs.append(1 - np.mean(table[i1[0]] != table[i2[0]])); ys.append(float(human))
    from scipy.stats import spearmanr
    return spearmanr(xs, ys).statistic, len(xs)


if __name__ == "__main__":
    print(f"vocabulary table read from {CONTAINER.name}: {fp.shape[0]:,} tokens x {fp.shape[1]} bits")
    r, n = score(fp); r0, _ = score(rand)
    print(f"WordSim-353, single-token pairs (n={n})")
    print(f"  frozen vocabulary codes : Spearman {r:.3f}")
    print(f"  random codes (baseline) : Spearman {r0:.3f}")
