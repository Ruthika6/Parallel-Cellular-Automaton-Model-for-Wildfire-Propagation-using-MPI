# Parallel Cellular Automaton Model for Wildfire Propagation using MPI

K Sri Praneetha (245805006) · K Ruthika Reddy (245805344)

A 2-D cellular automaton (unburned / burning / burnt) simulates wildfire spread under wind and
varying vegetation. A sequential C version and an MPI version are provided; the MPI version
splits the grid row-wise and exchanges halo rows with `MPI_Sendrecv` at **every** timestep.
Both versions produce **bit-identical** results, which is checked automatically.

## 1. Build and run

```bash
# Ubuntu/Debian prerequisites
sudo apt install build-essential mpich python3-numpy python3-matplotlib python3-pil   # or openmpi-bin libopenmpi-dev

make                                   # builds ./fire_seq and ./fire_mpi
make test                              # correctness: MPI output == sequential output

./fire_seq -w 600 -h 600 -t 1500 -i 300 -o out           # sequential, with snapshots
mpirun -np 4 ./fire_mpi -w 600 -h 600 -t 1500 -i 300 -o out   # parallel, 4 processes
python3 scripts/visualize.py frames out mpi_p4           # montage.png + fire.gif
python3 scripts/visualize.py progress out mpi_p4_stats.csv

make bench                             # timing runs -> results/bench.csv
python3 scripts/visualize.py bench     # speedup / efficiency table + results/speedup.png
make report                            # rebuild report/Wildfire_MPI_Report.docx from results (needs: pip install python-docx matplotlib)
```
(OpenMPI users running as root need `--allow-run-as-root`; the scripts detect this automatically.
On a laptop with fewer cores than processes use OpenMPI's `--oversubscribe`.)

Command-line options (both programs): `-w width -h height -t steps -s seed -a wind_deg -k wind_strength -p base_ignition_prob -i snapshot_every -o outdir -n` (`-n` = no output files; use it for timing).
Wind direction `-a` is where the wind blows **toward**: 0=N, 90=E, 180=S, 270=W.

## 2. Files

| File | Purpose |
|---|---|
| `src/fire_common.h` | Terrain generator, deterministic random numbers, **the cell-update rule**, PPM writer. Included by both programs. |
| `src/fire_seq.c` | Sequential baseline. |
| `src/fire_mpi.c` | MPI version (decomposition, halo exchange, gather, timing). |
| `scripts/run_tests.sh` | 28 correctness checks + byte-level `cmp` of final grids. |
| `scripts/run_bench.sh` | Timing experiments → `results/bench.csv`. |
| `scripts/visualize.py` | Snapshot montage/GIF, progress plot, speedup/efficiency plots. |
| `scripts/make_report.py` | Builds the Word report `report/Wildfire_MPI_Report.docx` from the measured results (`make report`). |
| `report/` | The project report (.docx and .pdf). |
| `sample_output/` | Example montage, GIF and progress curve (4-process MPI run). |

## 3. Model

* **States:** 0 unburned, 1 burning, 2 burnt. A separate read-only **fuel map** (0 = water/rock, 1–255 = vegetation density) is generated with smooth noise, plus lakes and a river that act as firebreaks.
* **Unburned cell:** for every burning neighbour among its 8 neighbours, ignition probability is `p = base_ignite × fuel × wind_factor(direction)`. The probabilities combine as `P(ignite) = 1 − Π(1 − p_i)`, then one random draw decides.
* **Wind factor:** `exp(k · cosθ)` where θ is the angle between the wind and the direction the fire would travel into the cell, so fire spreads faster downwind and slower upwind (`k = 0` → no wind).
* **Burning cell:** burns out with probability `0.06 + 0.30·(1 − fuel)` per step (dense fuel burns longer), becoming burnt.
* **Burnt cell:** stays burnt. Outside the map is treated as unburned.
* Double buffering (`cur` → `nxt`, then swap): all cells of step *t+1* depend only on step *t*.

## 4. Parallel design

1. **Rank 0** generates fuel map and initial fire (the ignition patch is at the middle row, so it sits on or near a process boundary and exercises the halo exchange immediately).
2. **Row-wise decomposition.** Rows are split so sizes differ by at most one (`H/p`, first `H mod p` ranks get one extra). `MPI_Scatterv` / `MPI_Gatherv` are used instead of plain `MPI_Scatter` / `MPI_Gather` so any grid height works, not only multiples of *p*.
3. Each rank stores `rows + 2` rows: row 0 = top halo, row `rows+1` = bottom halo.
4. **Every timestep:** two `MPI_Sendrecv` calls (send first row up / receive bottom halo; send last row down / receive top halo). The top and bottom ranks use `MPI_PROC_NULL`, so there are no special cases and no deadlock. Only the *state* grid is exchanged, the fuel map never changes so it is scattered once.
5. Update the local strip with the same `fire_step()` the sequential program uses.
6. **Final `MPI_Gatherv`** to rank 0, which computes counts and a hash and writes the output image.

### Why the MPI result is identical to the sequential one
The random number for a cell is a hash of `(global_row, column, timestep, salt)`, **not** a stream
from `rand()`. It therefore does not depend on which process handles the cell or in what order.
Together with the halo exchange this makes the parallel grid exactly equal to the sequential
grid, verified by an FNV-1a hash (printed on every run as `hash=...`) and by `cmp` on the output files.

### Timing method
* Timed region = halo exchange + cell update for all steps. Terrain generation, scatter, snapshots and file output are **excluded**.
* Each rank accumulates `MPI_Wtime()` for communication and computation separately; the program reports the **maximum over ranks** (`MPI_Reduce(MPI_MAX)`) because the slowest rank determines the parallel time. `MPI_Barrier` precedes the loop so all ranks start together.
* The sequential program times the same region with `clock_gettime(CLOCK_MONOTONIC)` (it does not link MPI).
* `run_bench.sh` repeats each run and `visualize.py bench` reports the best of the repeats.
* Speedup = T_seq / T_par, efficiency = speedup / p, comm % = halo-exchange time / total.

## 5. The report

`report/Wildfire_MPI_Report.docx` is generated by `make report` from `results/*.csv`; no number in the results section is typed by hand. **The copy shipped in this folder was built on a 1-core machine**, so its speedup table is marked as oversubscribed and shows correctness only. **Before submitting: run `make bench` on a multi-core machine, then `python3 scripts/visualize.py bench`, `make test` and `make report`** - the results section, table, graphs and analysis text are rebuilt automatically.

## 5b. Notes on the numbers (be honest)

* The proposal's "~8 minutes" figure was an estimate. **Replace it with your measured T_seq** from `make bench`. (On the development sandbox the code ran ≈ 6 ns per cell update, so 2000×2000×5000 is roughly 2 minutes sequentially. Measure on your machine.)
* Run benchmarks on a machine with ≥ 4 physical cores and quote the core count. Using more processes than physical cores (oversubscription) makes the program slower, and the numbers will not show real speedup.
* Expect speedup below *p*. Communication per step is `O(W)` bytes while computation per step is `O(W·H/p)`, so larger grids give better efficiency. The size sweep in `run_bench.sh` is there to demonstrate this.

## 6. Limitations / future work
* 1-D row decomposition: each rank exchanges two rows of length W regardless of *p*. A 2-D block decomposition reduces halo volume per rank at high *p*.
* Every cell is scanned every step. The fire front is a small part of the map, so skipping inactive regions would help, but would create load imbalance that needs dynamic balancing.
* Communication and computation are not overlapped. Interior rows could be computed while `MPI_Isend/Irecv` exchange the halo, then the two border rows finished afterwards.
* Fire cannot jump a firebreak wider than a cell (no "spotting"/embers), and there is no terrain slope, humidity or fuel moisture.
* MPI is not the only tool for a single machine (OpenMP would also work); MPI is chosen because it scales to distributed-memory clusters and because the project is about message passing.

## 7. Likely viva questions

| Question | Answer |
|---|---|
| Why is MPI really needed here? | Fire at a strip edge depends on neighbouring rows owned by another process, so data must be exchanged every timestep (halo exchange), not only once. |
| Why `MPI_Sendrecv`? | Combines send and receive in one deadlock-free call; with plain blocking `MPI_Send` followed by `MPI_Recv` on every rank, the exchange can deadlock. |
| Why `MPI_PROC_NULL`? | Edge ranks have only one neighbour; sending to/receiving from `MPI_PROC_NULL` is a no-op, which removes special cases. The untouched halo stays zero = "unburned". |
| What if the rows don't divide evenly? | `Scatterv/Gatherv` with per-rank counts and displacements; tested with 103, 131, 157, 203, 211 rows. |
| How do you know the parallel version is correct? | Hash-based RNG + identical update function → outputs are bit-identical; `make test` checks 28 combinations and `cmp`s the files. |
| Why is speedup < p? | Halo-exchange cost every step, memory bandwidth limits, rank 0's extra work outside the loop, and OS jitter. |
| Why does bigger grid give better efficiency? | Compute grows as W·H, communication only as W. |
| Why row-wise and not 2-D blocks? | Rows are contiguous in memory, so no packing is needed; simpler and adequate here. |
| Why not `rand()`? | A shared stream makes the result depend on process count/order, so parallel ≠ sequential and correctness cannot be shown. |
