"""Does the index scale linearly? Build it at four sizes and look."""
import os, time, subprocess, numpy as np, json
tok = np.fromfile("/root/arch1e8/tokens.bin", dtype=np.int32)
rows = []
for n in (12_500_000, 25_000_000, 50_000_000, len(tok)):
    t = tok[:n]; c = np.flatnonzero(t == 6); t = t[:c[-1] + 1]
    t.tofile("/root/sl.bin")
    nrec = int((t == 5).sum())
    t0 = time.time()
    subprocess.run(["./deployment/bin/linux/shadow_index", "build", "/root/sl.bin",
                    "deployment/fold.bin", "/root/sl_idx.bin"], check=True, capture_output=True)
    dt = time.time() - t0; sz = os.path.getsize("/root/sl_idx.bin")
    rows.append((len(t), nrec, dt, sz))
    print(f"  {len(t):>12,} tokens  {nrec:>10,} records   build {dt:6.2f} s   index {sz/1e9:5.2f} GB   {sz/len(t):4.1f} B/token   {len(t)/dt/1e6:5.1f} M tok/s")
for f in ("/root/sl.bin", "/root/sl_idx.bin"):
    if os.path.exists(f): os.remove(f)
json.dump(rows, open("/root/scale.json", "w"))
# extrapolate to 100 million documents at this archive's record length
TPR = rows[-1][0] / rows[-1][1]
big_tok = 100e6 * TPR
bps = rows[-1][3] / rows[-1][0]; tps = rows[-1][0] / rows[-1][2]
print(f"\n  100,000,000 documents at {TPR:.1f} tokens each = {big_tok/1e9:.2f}B tokens")
print(f"    index          {big_tok*bps/1e9:6.1f} GB, built in {big_tok/tps/60:5.1f} min on this CPU")
print(f"    token stream   {big_tok*4/1e9:6.1f} GB")
print(f"    BGE-M3 vectors {100e6*1024*2/1e9:6.1f} GB, {100e6/1051/3600:5.1f} h on the 3090")
