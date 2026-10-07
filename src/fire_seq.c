/*
 * fire_seq.c -- SEQUENTIAL wildfire cellular automaton (baseline).
 * One process updates the whole grid every timestep.
 */
#ifndef _WIN32
#define _POSIX_C_SOURCE 199309L
#endif
#include <time.h>
#include "fire_common.h"

#ifdef _WIN32
#include <windows.h>
static double now(void)             /* high-resolution timer on Windows */
{
    LARGE_INTEGER f, c;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return (double)c.QuadPart / (double)f.QuadPart;
}
#else
static double now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}
#endif

static void snapshot(const FireParams *P, const uint8_t *real, const uint8_t *fuel, int t, FILE *stats)
{
    long un, bu, bt;
    grid_counts(real, (size_t)P->W * P->H, &un, &bu, &bt);
    fprintf(stats, "%d,%ld,%ld,%ld\n", t, un, bu, bt);
    char path[512];
    snprintf(path, sizeof path, "%s/seq_t%06d.ppm", P->outdir, t);
    write_ppm(path, real, fuel, P->H, P->W);
}

int main(int argc, char **argv)
{
    FireParams P;
    if (!parse_args(argc, argv, &P)) return 1;
    int W = P.W, H = P.H;
    size_t cells = (size_t)W * H;

    /* grid with halo rows (row 0 and H+1 stay UNBURNED forever) */
    uint8_t *cur  = calloc((size_t)(H + 2) * W, 1);
    uint8_t *nxt  = calloc((size_t)(H + 2) * W, 1);
    uint8_t *fuel = malloc(cells);
    uint8_t *init = malloc(cells);
    if (!cur || !nxt || !fuel || !init) { fprintf(stderr, "out of memory\n"); return 1; }

    generate_landscape(&P, fuel, init);
    memcpy(cur + W, init, cells);
    free(init);

    FILE *stats = NULL;
    if (P.write_output) {
        MAKE_DIR(P.outdir);
        char path[512];
        snprintf(path, sizeof path, "%s/seq_stats.csv", P.outdir);
        stats = fopen(path, "w");
        fprintf(stats, "step,unburned,burning,burnt\n");
        snapshot(&P, cur + W, fuel, 0, stats);
    }

    double timed = 0.0;
    for (int t = 0; t < P.steps; t++) {
        double t0 = now();
        fire_step(cur, nxt, fuel, W, H, 0, t, &P);
        uint8_t *tmp = cur; cur = nxt; nxt = tmp;
        timed += now() - t0;

        if (P.write_output && P.snap_every > 0 && (t + 1) % P.snap_every == 0 && t + 1 != P.steps)
            snapshot(&P, cur + W, fuel, t + 1, stats);
    }

    uint64_t hash = grid_hash(cur + W, cells);
    long un, bu, bt;
    grid_counts(cur + W, cells, &un, &bu, &bt);

    if (P.write_output) {
        snapshot(&P, cur + W, fuel, P.steps, stats);
        fclose(stats);
        char path[512];
        snprintf(path, sizeof path, "%s/seq_final.bin", P.outdir);
        write_bin(path, cur + W, cells);
        snprintf(path, sizeof path, "%s/seq_final.ppm", P.outdir);
        write_ppm(path, cur + W, fuel, H, W);
    }

    printf("RESULT impl=seq procs=1 W=%d H=%d steps=%d time=%.6f comm=0.000000 hash=%016llx "
           "unburned=%ld burning=%ld burnt=%ld\n",
           W, H, P.steps, timed, (unsigned long long)hash, un, bu, bt);
    free(cur); free(nxt); free(fuel);
    return 0;
}
