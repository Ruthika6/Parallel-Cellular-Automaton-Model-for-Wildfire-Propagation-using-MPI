/*
 * fire_mpi.c -- PARALLEL wildfire cellular automaton using MPI.
 *
 *   rank 0 builds terrain + initial fire
 *   MPI_Scatterv  : each process receives a strip of rows (row-wise decomposition)
 *   every step    : halo exchange with MPI_Sendrecv, then update own strip
 *   MPI_Gatherv   : rank 0 reassembles the final grid
 *
 * Scatterv/Gatherv (instead of Scatter/Gather) are used so the grid height
 * does NOT have to be divisible by the number of processes.
 */
#include <mpi.h>
#include <sys/stat.h>
#include "fire_common.h"

/* Gather the current strips of all ranks into `full` on rank 0 (H*W bytes). */
static void gather_grid(const uint8_t *cur, uint8_t *full, int rows, int W,
                        const int *counts, const int *displs, MPI_Comm comm)
{
    MPI_Gatherv(cur + W, rows * W, MPI_UNSIGNED_CHAR,
                full, counts, displs, MPI_UNSIGNED_CHAR, 0, comm);
}

int main(int argc, char **argv)
{
    MPI_Init(&argc, &argv);
    MPI_Comm comm = MPI_COMM_WORLD;
    int rank, size;
    MPI_Comm_rank(comm, &rank);
    MPI_Comm_size(comm, &size);

    FireParams P;
    int ok = (rank == 0) ? parse_args(argc, argv, &P) : 1;
    MPI_Bcast(&ok, 1, MPI_INT, 0, comm);
    if (!ok) { MPI_Finalize(); return 1; }
    MPI_Bcast(&P, sizeof P, MPI_BYTE, 0, comm);      /* every rank gets identical params + tables */

    int W = P.W, H = P.H;
    if (H < size) {
        if (rank == 0) fprintf(stderr, "grid height (%d) must be >= number of processes (%d)\n", H, size);
        MPI_Finalize(); return 1;
    }

    /* ---- domain decomposition: first (H % size) ranks get one extra row ---- */
    int *counts = malloc(size * sizeof(int));     /* bytes per rank */
    int *displs = malloc(size * sizeof(int));     /* byte offset per rank */
    int *rowsOf = malloc(size * sizeof(int));
    int *rowOff = malloc(size * sizeof(int));
    int base = H / size, rem = H % size, off = 0;
    for (int r = 0; r < size; r++) {
        rowsOf[r] = base + (r < rem ? 1 : 0);
        rowOff[r] = off;
        counts[r] = rowsOf[r] * W;
        displs[r] = off * W;
        off += rowsOf[r];
    }
    int  rows  = rowsOf[rank];
    long grow0 = rowOff[rank];            /* global index of my first row */

    /* ---- rank 0 builds the landscape ---- */
    uint8_t *fullFuel = NULL, *fullGrid = NULL;
    size_t cells = (size_t)W * H;
    if (rank == 0) {
        fullFuel = malloc(cells);
        fullGrid = malloc(cells);
        generate_landscape(&P, fullFuel, fullGrid);
    }

    /* local blocks: rows + 2 halo rows, zero-initialised (zero halo = "no fire outside the map") */
    uint8_t *cur  = calloc((size_t)(rows + 2) * W, 1);
    uint8_t *nxt  = calloc((size_t)(rows + 2) * W, 1);
    uint8_t *fuel = malloc((size_t)rows * W);

    /* ---- distribute strips ---- */
    MPI_Scatterv(fullGrid, counts, displs, MPI_UNSIGNED_CHAR,
                 cur + W, rows * W, MPI_UNSIGNED_CHAR, 0, comm);
    MPI_Scatterv(fullFuel, counts, displs, MPI_UNSIGNED_CHAR,
                 fuel, rows * W, MPI_UNSIGNED_CHAR, 0, comm);

    FILE *stats = NULL;
    char path[512];
    if (rank == 0 && P.write_output) {
        mkdir(P.outdir, 0755);
        snprintf(path, sizeof path, "%s/mpi_p%d_stats.csv", P.outdir, size);
        stats = fopen(path, "w");
        fprintf(stats, "step,unburned,burning,burnt\n");
    }

    /* snapshot helper: gather + write (NOT included in the timed region) */
    #define SNAPSHOT(T) do {                                                         \
        if (P.write_output) {                                                        \
            gather_grid(cur, fullGrid, rows, W, counts, displs, comm);               \
            if (rank == 0) {                                                         \
                long un, bu, bt; grid_counts(fullGrid, cells, &un, &bu, &bt);        \
                fprintf(stats, "%d,%ld,%ld,%ld\n", (T), un, bu, bt);                 \
                snprintf(path, sizeof path, "%s/mpi_p%d_t%06d.ppm", P.outdir, size, (T)); \
                write_ppm(path, fullGrid, fullFuel, H, W);                           \
            }                                                                        \
        } } while (0)

    SNAPSHOT(0);

    int up   = (rank == 0)        ? MPI_PROC_NULL : rank - 1;
    int down = (rank == size - 1) ? MPI_PROC_NULL : rank + 1;

    /* ---------------- timed simulation loop ---------------- */
    double t_comm = 0.0, t_comp = 0.0;
    MPI_Barrier(comm);

    for (int t = 0; t < P.steps; t++) {
        double a = MPI_Wtime();

        /* HALO EXCHANGE: send first real row up / receive bottom halo from below */
        MPI_Sendrecv(cur + (size_t)1 * W,        W, MPI_UNSIGNED_CHAR, up,   0,
                     cur + (size_t)(rows + 1) * W, W, MPI_UNSIGNED_CHAR, down, 0,
                     comm, MPI_STATUS_IGNORE);
        /* send last real row down / receive top halo from above */
        MPI_Sendrecv(cur + (size_t)rows * W,     W, MPI_UNSIGNED_CHAR, down, 1,
                     cur,                        W, MPI_UNSIGNED_CHAR, up,   1,
                     comm, MPI_STATUS_IGNORE);

        double b = MPI_Wtime();

        /* UPDATE CELLS of my strip */
        fire_step(cur, nxt, fuel, W, rows, grow0, t, &P);
        uint8_t *tmp = cur; cur = nxt; nxt = tmp;

        double c = MPI_Wtime();
        t_comm += b - a;
        t_comp += c - b;

        if (P.snap_every > 0 && (t + 1) % P.snap_every == 0 && t + 1 != P.steps) {
            SNAPSHOT(t + 1);
        }
    }
    /* ------------------------------------------------------- */

    /* slowest process determines the parallel time */
    double mine[3] = { t_comm + t_comp, t_comm, t_comp }, worst[3];
    MPI_Reduce(mine, worst, 3, MPI_DOUBLE, MPI_MAX, 0, comm);

    /* final gather (always needed for the correctness hash) */
    if (rank == 0 && !fullGrid) fullGrid = malloc(cells);
    gather_grid(cur, fullGrid, rows, W, counts, displs, comm);

    if (rank == 0) {
        long un, bu, bt;
        grid_counts(fullGrid, cells, &un, &bu, &bt);
        uint64_t hash = grid_hash(fullGrid, cells);
        if (P.write_output) {
            fprintf(stats, "%d,%ld,%ld,%ld\n", P.steps, un, bu, bt);
            fclose(stats);
            snprintf(path, sizeof path, "%s/mpi_p%d_final.bin", P.outdir, size);
            write_bin(path, fullGrid, cells);
            snprintf(path, sizeof path, "%s/mpi_p%d_final.ppm", P.outdir, size);
            write_ppm(path, fullGrid, fullFuel, H, W);
        }
        printf("RESULT impl=mpi procs=%d W=%d H=%d steps=%d time=%.6f comm=%.6f hash=%016llx "
               "unburned=%ld burning=%ld burnt=%ld\n",
               size, W, H, P.steps, worst[0], worst[1], (unsigned long long)hash, un, bu, bt);
    }

    free(cur); free(nxt); free(fuel); free(counts); free(displs); free(rowsOf); free(rowOff);
    if (rank == 0) { free(fullGrid); free(fullFuel); }
    MPI_Finalize();
    return 0;
}
