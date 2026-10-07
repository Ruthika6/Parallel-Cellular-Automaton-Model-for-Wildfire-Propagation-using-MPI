#!/usr/bin/env python3
"""
Visualisation + benchmark analysis for the wildfire project.

  python3 scripts/visualize.py frames  [out_dir] [prefix]   snapshots -> montage.png + fire.gif
  python3 scripts/visualize.py progress [out_dir] [stats.csv]  burning/burnt cells over time
  python3 scripts/visualize.py bench   [results/bench.csv]  speedup / efficiency plots + table
"""
import sys, glob, os, csv
from collections import defaultdict
from statistics import median

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image


def cmd_frames(out="out", prefix="seq"):
    files = sorted(f for f in glob.glob(f"{out}/{prefix}_t*.ppm"))
    if not files:
        sys.exit(f"no snapshots like {out}/{prefix}_t*.ppm - run with -i <interval> first")
    imgs = [Image.open(f).convert("RGB") for f in files]
    steps = [int(os.path.basename(f).split("_t")[-1].split(".")[0]) for f in files]

    # montage of up to 6 evenly spaced frames
    idx = np.unique(np.linspace(0, len(files) - 1, min(6, len(files))).astype(int))
    cols = min(3, len(idx)); rows = (len(idx) + cols - 1) // cols
    fig, axs = plt.subplots(rows, cols, figsize=(5 * cols, 5 * rows), squeeze=False)
    for ax in axs.ravel():
        ax.axis("off")
    for ax, i in zip(axs.ravel(), idx):
        ax.imshow(imgs[i]); ax.set_title(f"timestep {steps[i]}")
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color="#146e19", label="unburned forest"),
                        Patch(color="#3270c8", label="water (no fuel)"),
                        Patch(color="#ff5a00", label="burning"),
                        Patch(color="#2d2828", label="burnt")],
               loc="lower center", ncol=4, frameon=False)
    fig.suptitle("Wildfire spread (cellular automaton)")
    fig.tight_layout(rect=[0, 0.04, 1, 0.97])
    fig.savefig(f"{out}/montage.png", dpi=110); plt.close(fig)

    imgs[0].save(f"{out}/fire.gif", save_all=True, append_images=imgs[1:], duration=350, loop=0)
    print(f"wrote {out}/montage.png and {out}/fire.gif ({len(files)} frames)")


def cmd_progress(out="out", name="seq_stats.csv"):
    d = np.genfromtxt(f"{out}/{name}", delimiter=",", names=True)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(d["step"], d["burning"], color="#ff5a00", label="burning")
    ax.plot(d["step"], d["burnt"], color="#2d2828", label="burnt")
    ax.set_xlabel("timestep"); ax.set_ylabel("number of cells"); ax.legend()
    ax.set_title("Fire progress over time"); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(f"{out}/progress.png", dpi=120)
    print(f"wrote {out}/progress.png")


def cmd_bench(path="results/bench.csv"):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    runs = defaultdict(list)            # (size, impl, procs) -> [(time, comm)]
    hashes = defaultdict(set)           # size -> set(hash)
    for r in rows:
        key = (int(r["W"]), r["impl"], int(r["procs"]))
        runs[key].append((float(r["time"]), float(r["comm"])))
        hashes[int(r["W"])].add(r["hash"])
    sizes = sorted({k[0] for k in runs})

    ok = all(len(h) == 1 for h in hashes.values())
    print("Correctness across all benchmark runs (all hashes identical per grid size):", "YES" if ok else "NO  <-- investigate")

    best = lambda key: min(t for t, _ in runs[key])           # best of N repeats
    tab = []
    for n in sizes:
        t_seq = best((n, "seq", 1))
        for p in sorted({k[2] for k in runs if k[0] == n and k[1] == "mpi"}):
            tp = best((n, "mpi", p))
            comm = median(c for t, c in runs[(n, "mpi", p)] )
            tab.append((n, p, t_seq, tp, t_seq / tp, t_seq / tp / p, 100 * comm / tp))

    print(f"\n{'grid':>6} {'procs':>5} {'T_seq(s)':>10} {'T_par(s)':>10} {'speedup':>8} {'effic.':>7} {'comm%':>6}")
    for n, p, ts, tp, s, e, c in tab:
        print(f"{n:>6} {p:>5} {ts:>10.3f} {tp:>10.3f} {s:>8.2f} {e:>7.2f} {c:>6.1f}")
    os.makedirs("results", exist_ok=True)
    with open("results/summary.csv", "w", encoding="utf-8") as f:
        f.write("grid,procs,t_seq,t_par,speedup,efficiency,comm_percent\n")
        for row in tab: f.write(",".join(f"{x:.4f}" if isinstance(x, float) else str(x) for x in row) + "\n")

    procs = sorted({t[1] for t in tab})
    fig, axs = plt.subplots(1, 3, figsize=(16, 4.5))
    for n in sizes:
        pts = [(t[1], t[4], t[5], t[6]) for t in tab if t[0] == n]
        axs[0].plot(*zip(*[(p, s) for p, s, _, _ in pts]), "o-", label=f"{n}x{n}")
        axs[1].plot(*zip(*[(p, e) for p, _, e, _ in pts]), "o-", label=f"{n}x{n}")
        axs[2].plot(*zip(*[(p, c) for p, _, _, c in pts]), "o-", label=f"{n}x{n}")
    axs[0].plot(procs, procs, "k--", label="ideal"); axs[0].set_title("Speedup = T_seq / T_par")
    axs[1].axhline(1, color="k", ls="--"); axs[1].set_title("Efficiency = speedup / p")
    axs[2].set_title("Time spent in halo exchange (% of run)")
    for ax, yl in zip(axs, ["speedup", "efficiency", "% communication"]):
        ax.set_xlabel("MPI processes"); ax.set_ylabel(yl); ax.set_xticks(procs); ax.grid(alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig("results/speedup.png", dpi=120)
    print("\nwrote results/speedup.png and results/summary.csv")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("frames", "progress", "bench"):
        sys.exit(__doc__)
    globals()["cmd_" + sys.argv[1]](*sys.argv[2:])
