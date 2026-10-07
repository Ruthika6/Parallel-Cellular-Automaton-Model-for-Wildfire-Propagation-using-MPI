/*
 * fire_common.h -- code shared by the sequential and the MPI program.
 *
 * Keeping the terrain generator, the random numbers and the cell-update rule
 * in ONE place guarantees that both programs simulate exactly the same model,
 * so their final grids can be compared bit-for-bit.
 *
 * Cell states : 0 = UNBURNED, 1 = BURNING, 2 = BURNT
 * Terrain     : fuel[] holds one byte per cell (0 = non-flammable water/rock,
 *               1..255 = amount of vegetation / fuel).
 * Grid layout : a block of `rows` rows is stored with one extra HALO row above
 *               and below, i.e. (rows + 2) * W bytes. Row 0 and row rows+1 are
 *               halo rows (copies of neighbouring rows, or all-zero at the
 *               edge of the landscape). Real rows are 1..rows.
 */
#ifndef FIRE_COMMON_H
#define FIRE_COMMON_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* portable "create directory" (Linux/macOS: mkdir with mode, Windows: _mkdir) */
#ifdef _WIN32
  #include <direct.h>
  #define MAKE_DIR(p) _mkdir(p)
#else
  #include <sys/stat.h>
  #define MAKE_DIR(p) mkdir((p), 0755)
#endif

#define UNBURNED 0
#define BURNING  1
#define BURNT    2

#define SALT_IGNITE 0x1111u
#define SALT_BURNOUT 0x2222u
#define SALT_TERRAIN 0x3333u

/* ------------------------------------------------------------------ */
/* Parameters                                                          */
/* ------------------------------------------------------------------ */
typedef struct {
    int      W, H, steps;
    uint32_t seed;
    float    wind_deg;      /* direction the wind blows TOWARD, degrees clockwise from North */
    float    wind_k;        /* wind strength: 0 = no wind                                    */
    float    base_ignite;   /* ignition probability of a full-fuel cell next to ONE fire     */
    int      snap_every;    /* write a snapshot every N steps (0 = only first and last)      */
    int      write_output;  /* 0 = benchmark mode, no files                                  */
    char     outdir[256];
    /* derived tables */
    float    wf[8];         /* wind factor for each of the 8 neighbours                      */
    float    p_ign[256];    /* per-fuel ignition probability (before wind)                   */
    float    p_out[256];    /* per-fuel probability that a burning cell burns out this step  */
} FireParams;

/* neighbour offsets (dr, dc); order is fixed so results are reproducible */
static const int NB_DR[8] = {-1,-1,-1, 0, 0, 1, 1, 1};
static const int NB_DC[8] = {-1, 0, 1,-1, 1,-1, 0, 1};

static void params_defaults(FireParams *P)
{
    memset(P, 0, sizeof *P);
    P->W = 1000; P->H = 1000; P->steps = 500;
    P->seed = 12345u;
    P->wind_deg = 90.0f;    /* blowing toward East */
    P->wind_k   = 1.5f;
    P->base_ignite = 0.30f;
    P->snap_every = 0;
    P->write_output = 1;
    strcpy(P->outdir, "out");
}

/* Build the derived lookup tables. Called identically by both programs. */
static void params_finalize(FireParams *P)
{
    const float PI = 3.14159265f;
    float a  = P->wind_deg * PI / 180.0f;
    float wr = -cosf(a);    /* wind vector in (row, col) space; row grows southward */
    float wc =  sinf(a);
    for (int k = 0; k < 8; k++) {
        /* direction the fire travels when it jumps from the neighbour INTO the
           centre cell is the reverse of the neighbour offset */
        float dr = (float)(-NB_DR[k]), dc = (float)(-NB_DC[k]);
        float len = sqrtf(dr * dr + dc * dc);
        float cosang = (dr * wr + dc * wc) / len;       /* -1 (against wind) .. +1 (with wind) */
        P->wf[k] = expf(P->wind_k * cosang);            /* >1 downwind, <1 upwind */
    }
    for (int f = 0; f < 256; f++) {
        float fuel = (float)f / 255.0f;
        P->p_ign[f] = P->base_ignite * fuel;
        P->p_out[f] = 0.06f + 0.30f * (1.0f - fuel);    /* rich fuel burns longer */
    }
}

/* ------------------------------------------------------------------ */
/* Deterministic hash-based random numbers                             */
/* ------------------------------------------------------------------ */
/* The random number depends ONLY on (global row, column, timestep, salt),
 * never on which process computes the cell or in what order. This is what
 * makes the MPI result identical to the sequential one. */
static inline uint32_t mix32(uint32_t x)
{
    x ^= x >> 16; x *= 0x7feb352dU;
    x ^= x >> 15; x *= 0x846ca68bU;
    x ^= x >> 16;
    return x;
}
static inline float rnd(uint32_t r, uint32_t c, uint32_t t, uint32_t salt)
{
    uint32_t h = mix32(salt ^ mix32(r + mix32(c + mix32(t))));
    return (float)(h >> 8) * (1.0f / 16777216.0f);      /* uniform in [0,1) */
}

/* ------------------------------------------------------------------ */
/* Terrain + initial fire (built once, by the root process / sequential) */
/* ------------------------------------------------------------------ */
static inline float lattice(int x, int y, uint32_t seed)
{
    return (float)(mix32((uint32_t)x * 374761393u + (uint32_t)y * 668265263u + seed) >> 8)
           * (1.0f / 16777216.0f);
}
/* smooth value noise at a given cell size */
static float vnoise(int r, int c, int cell, uint32_t seed)
{
    int   r0 = r / cell, c0 = c / cell;
    float fr = (float)(r % cell) / cell, fc = (float)(c % cell) / cell;
    fr = fr * fr * (3.0f - 2.0f * fr);
    fc = fc * fc * (3.0f - 2.0f * fc);
    float a = lattice(r0, c0, seed),     b = lattice(r0, c0 + 1, seed);
    float d = lattice(r0 + 1, c0, seed), e = lattice(r0 + 1, c0 + 1, seed);
    float top = a + (b - a) * fc, bot = d + (e - d) * fc;
    return top + (bot - top) * fr;
}

/* fuel: H*W bytes.  grid: H*W bytes (initial states, no halo). */
static void generate_landscape(const FireParams *P, uint8_t *fuel, uint8_t *grid)
{
    int H = P->H, W = P->W;
    int big = (H < W ? H : W) / 6;  if (big < 4) big = 4;
    int sm  = big / 4;              if (sm  < 2) sm  = 2;
    for (int r = 0; r < H; r++) {
        for (int c = 0; c < W; c++) {
            float n = 0.65f * vnoise(r, c, big, P->seed ^ SALT_TERRAIN)
                    + 0.35f * vnoise(r, c, sm,  P->seed ^ (SALT_TERRAIN + 1));
            float f = 0.15f + 0.85f * n;                    /* vegetation density */
            /* lakes where the low-frequency noise is very low */
            if (vnoise(r, c, big, P->seed + 77u) < 0.17f) f = 0.0f;
            /* a winding river across the map */
            float rc = 0.70f * H + 0.06f * H * sinf(6.2831853f * (float)c / (float)W * 1.5f);
            if (fabsf((float)r - rc) < 0.008f * H + 1.0f) f = 0.0f;
            int v = (int)(f * 255.0f);
            if (f > 0.0f && v < 1) v = 1;
            fuel[(size_t)r * W + c] = (uint8_t)v;
            grid[(size_t)r * W + c] = UNBURNED;
        }
    }
    /* ignition: a small patch of dense forest on the middle row, left quarter */
    int ir = H / 2, ic = W / 4, rad = 3;
    for (int r = ir - rad; r <= ir + rad; r++)
        for (int c = ic - rad; c <= ic + rad; c++)
            if (r >= 0 && r < H && c >= 0 && c < W) {
                fuel[(size_t)r * W + c] = 220;
                grid[(size_t)r * W + c] = BURNING;
            }
}

/* ------------------------------------------------------------------ */
/* THE cell-update rule (one timestep for a block of rows)             */
/* ------------------------------------------------------------------ */
/*  old, nw : (rows+2)*W blocks with halo rows
 *  fuel    : rows*W (no halo)
 *  grow0   : global index of the first real row (row 1 of the block)
 *  t       : timestep number (used for the random numbers)           */
static void fire_step(const uint8_t *old, uint8_t *nw, const uint8_t *fuel,
                      int W, int rows, long grow0, int t, const FireParams *P)
{
    for (int i = 1; i <= rows; i++) {
        const uint8_t *orow = old + (size_t)i * W;
        uint8_t       *nrow = nw  + (size_t)i * W;
        const uint8_t *frow = fuel + (size_t)(i - 1) * W;
        uint32_t gr = (uint32_t)(grow0 + (i - 1));

        for (int c = 0; c < W; c++) {
            uint8_t s = orow[c];

            if (s == BURNT) { nrow[c] = BURNT; continue; }

            if (s == BURNING) {
                float u = rnd(gr, (uint32_t)c, (uint32_t)t, SALT_BURNOUT);
                nrow[c] = (u < P->p_out[frow[c]]) ? BURNT : BURNING;
                continue;
            }

            /* UNBURNED cell: can it catch fire from burning neighbours? */
            uint8_t f = frow[c];
            if (f == 0) { nrow[c] = UNBURNED; continue; }       /* water / bare rock */

            float q = 1.0f;     /* probability that NO neighbour ignites it */
            int   any = 0;
            for (int k = 0; k < 8; k++) {
                int cc = c + NB_DC[k];
                if (cc < 0 || cc >= W) continue;
                if (old[(size_t)(i + NB_DR[k]) * W + cc] == BURNING) {
                    float p = P->p_ign[f] * P->wf[k];
                    if (p > 1.0f) p = 1.0f;
                    q *= (1.0f - p);
                    any = 1;
                }
            }
            if (any && rnd(gr, (uint32_t)c, (uint32_t)t, SALT_IGNITE) < 1.0f - q)
                nrow[c] = BURNING;
            else
                nrow[c] = UNBURNED;
        }
    }
}

/* ------------------------------------------------------------------ */
/* Output helpers (called only by sequential program / MPI root)       */
/* ------------------------------------------------------------------ */
static uint64_t grid_hash(const uint8_t *g, size_t n)      /* FNV-1a 64-bit */
{
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < n; i++) { h ^= g[i]; h *= 1099511628211ULL; }
    return h;
}

static void grid_counts(const uint8_t *g, size_t n, long *un, long *bu, long *bt)
{
    long a = 0, b = 0, c = 0;
    for (size_t i = 0; i < n; i++) { if (g[i] == UNBURNED) a++; else if (g[i] == BURNING) b++; else c++; }
    *un = a; *bu = b; *bt = c;
}

/* Colour-coded PPM (P6). Large grids are down-sampled so files stay small;
 * a block that contains any burning cell is drawn as burning. */
static void write_ppm(const char *path, const uint8_t *g, const uint8_t *fuel, int H, int W)
{
    int ds = 1;
    while (H / ds > 700 || W / ds > 700) ds++;
    int oh = H / ds, ow = W / ds;
    FILE *fp = fopen(path, "wb");
    if (!fp) { perror(path); return; }
    fprintf(fp, "P6\n%d %d\n255\n", ow, oh);
    for (int orow = 0; orow < oh; orow++) {
        for (int ocol = 0; ocol < ow; ocol++) {
            int burning = 0;
            for (int dr = 0; dr < ds && !burning; dr++)
                for (int dc = 0; dc < ds; dc++)
                    if (g[(size_t)(orow * ds + dr) * W + ocol * ds + dc] == BURNING) { burning = 1; break; }
            size_t idx = (size_t)(orow * ds + ds / 2) * W + (ocol * ds + ds / 2);
            uint8_t rgb[3];
            if (burning)                { rgb[0] = 255; rgb[1] = 90;  rgb[2] = 0;   }
            else if (g[idx] == BURNT)   { rgb[0] = 45;  rgb[1] = 40;  rgb[2] = 40;  }
            else if (fuel[idx] == 0)    { rgb[0] = 50;  rgb[1] = 110; rgb[2] = 200; }
            else { rgb[0] = 20; rgb[1] = (uint8_t)(70 + fuel[idx] * 0.55); rgb[2] = 25; }
            fwrite(rgb, 1, 3, fp);
        }
    }
    fclose(fp);
}

static void write_bin(const char *path, const uint8_t *g, size_t n)
{
    FILE *fp = fopen(path, "wb");
    if (!fp) { perror(path); return; }
    fwrite(g, 1, n, fp);
    fclose(fp);
}

/* Command-line parsing shared by both programs */
static int parse_args(int argc, char **argv, FireParams *P)
{
    params_defaults(P);
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        #define NEXT() (i + 1 < argc ? argv[++i] : (fprintf(stderr, "missing value for %s\n", a), exit(1), (char *)0))
        if      (!strcmp(a, "-w")) P->W = atoi(NEXT());
        else if (!strcmp(a, "-h")) P->H = atoi(NEXT());
        else if (!strcmp(a, "-t")) P->steps = atoi(NEXT());
        else if (!strcmp(a, "-s")) P->seed = (uint32_t)strtoul(NEXT(), 0, 10);
        else if (!strcmp(a, "-a")) P->wind_deg = (float)atof(NEXT());
        else if (!strcmp(a, "-k")) P->wind_k = (float)atof(NEXT());
        else if (!strcmp(a, "-p")) P->base_ignite = (float)atof(NEXT());
        else if (!strcmp(a, "-i")) P->snap_every = atoi(NEXT());
        else if (!strcmp(a, "-o")) { strncpy(P->outdir, NEXT(), sizeof P->outdir - 1); }
        else if (!strcmp(a, "-n")) P->write_output = 0;
        else {
            fprintf(stderr,
              "Usage: %s [-w width] [-h height] [-t steps] [-s seed]\n"
              "          [-a wind_deg (0=N,90=E,180=S,270=W)] [-k wind_strength]\n"
              "          [-p base_ignite_prob] [-i snapshot_every] [-o outdir] [-n (no output files)]\n",
              argv[0]);
            return 0;
        }
        #undef NEXT
    }
    if (P->W < 8 || P->H < 8 || P->steps < 1) { fprintf(stderr, "grid must be >= 8x8 and steps >= 1\n"); return 0; }
    params_finalize(P);
    return 1;
}

#endif
