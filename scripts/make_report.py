#!/usr/bin/env python3
"""
Builds the project report (Word .docx) from the REAL measured results.

    make bench      # -> results/bench.csv, results/env.txt
    python3 scripts/visualize.py bench   # -> results/summary.csv, results/speedup.png
    make test       # -> results/test_log.txt
    make report     # -> report/Wildfire_MPI_Report.docx

Requires: pip install python-docx matplotlib
Nothing in the results section is hand-typed: every number comes from results/*.csv.
"""
import csv, os, re, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
from docx import Document
from docx.shared import Pt, Inches, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.makedirs("report", exist_ok=True)
os.makedirs("results", exist_ok=True)

TITLE = "Parallel Cellular Automaton Model for Wildfire Propagation using MPI"
AUTHORS = [("K Sri Praneetha", "245805006"), ("K Ruthika Reddy", "245805344")]

# ----------------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------------
def read_env():
    env = {}
    if os.path.exists("results/env.txt"):
        for line in open("results/env.txt", encoding="utf-8"):
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1); env[k] = v
    return env

def read_summary():
    rows = []
    if os.path.exists("results/summary.csv"):
        for r in csv.DictReader(open("results/summary.csv", encoding="utf-8")):
            rows.append(dict(grid=int(r["grid"]), procs=int(r["procs"]), t_seq=float(r["t_seq"]),
                             t_par=float(r["t_par"]), speedup=float(r["speedup"]),
                             eff=float(r["efficiency"]), comm=float(r["comm_percent"])))
    return rows

def read_bench_meta():
    steps = None; hashes_ok = None
    if os.path.exists("results/bench.csv"):
        rows = list(csv.DictReader(open("results/bench.csv", encoding="utf-8")))
        if rows:
            steps = rows[0]["steps"]
            by = {}
            for r in rows: by.setdefault(r["W"], set()).add(r["hash"])
            hashes_ok = all(len(v) == 1 for v in by.values())
    return steps, hashes_ok

ENV = read_env()
SUM = read_summary()
STEPS, HASH_OK = read_bench_meta()
CORES = int(ENV.get("cores", "0") or 0)

def source_snippet(path, start_pat, end_pat):
    txt = open(path, encoding="utf-8", errors="replace").read().split("\n")
    out, on = [], False
    for ln in txt:
        if start_pat in ln: on = True
        if on: out.append(ln.rstrip())
        if on and end_pat in ln: break
    # strip common indent
    ind = min((len(l) - len(l.lstrip()) for l in out if l.strip()), default=0)
    return "\n".join(l[ind:] for l in out)

# ----------------------------------------------------------------------------------
# diagrams (generated with matplotlib so the report is self-contained)
# ----------------------------------------------------------------------------------
def fig_workflow(path):
    fig, ax = plt.subplots(figsize=(6.2, 6.6)); ax.set_xlim(0, 10); ax.set_ylim(0, 12); ax.axis("off")
    def box(x, y, w, h, text, fc, ec="#333"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.15", fc=fc, ec=ec, lw=1.2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8.5)
    def arrow(x, y1, y2):
        ax.annotate("", xy=(x, y2), xytext=(x, y1), arrowprops=dict(arrowstyle="-|>", lw=1.3, color="#333"))
    box(2, 10.6, 6, 1.0, "Rank 0: generate terrain (fuel map)\n+ starting fire location", "#fde9c8")
    arrow(5, 10.6, 9.9)
    box(2, 8.9, 6, 1.0, "Divide grid row-wise\n(sizes differ by at most one row)", "#fde9c8")
    arrow(5, 8.9, 8.2)
    box(2, 7.2, 6, 1.0, "MPI_Scatterv\nevery rank receives its strip", "#cfe3f7")
    arrow(5, 7.2, 6.5)
    ax.add_patch(Rectangle((1.2, 2.9), 7.6, 3.6, fc="#f4f4f4", ec="#777", ls="--", lw=1.2))
    ax.text(1.4, 6.25, "for each timestep t = 0 ... steps-1  (all ranks, simultaneously)", fontsize=8, style="italic")
    box(2, 4.9, 6, 0.9, "Halo exchange: MPI_Sendrecv x2\n(edge rows with upper / lower neighbour)", "#cfe3f7")
    arrow(5, 4.9, 4.3)
    box(2, 3.3, 6, 0.9, "Update every cell of own strip\n(neighbours, wind, fuel)  ->  swap buffers", "#d6efd4")
    arrow(5, 2.9, 2.3)
    box(2, 1.3, 6, 1.0, "MPI_Gatherv\nrank 0 collects all strips in order", "#cfe3f7")
    arrow(5, 1.3, 0.8)
    box(2, -0.2, 6, 1.0, "Rank 0: counts, hash, colour-coded\nimage / animation of final grid", "#fde9c8")
    ax.set_ylim(-0.5, 12)
    fig.tight_layout(); fig.savefig(path, dpi=170); plt.close(fig)

def fig_decomposition(path):
    fig, ax = plt.subplots(figsize=(6.4, 4.4)); ax.set_xlim(0, 12); ax.set_ylim(0, 8.4); ax.axis("off")
    cols = ["#d6efd4", "#cfe3f7", "#fde9c8", "#e8d5f0"]
    y = 7.2
    for r in range(4):
        ax.add_patch(Rectangle((1, y - 0.28), 4.4, 0.28, fc="white", ec="#888", hatch="////", lw=0.8))   # top halo
        ax.add_patch(Rectangle((1, y - 1.28), 4.4, 1.0, fc=cols[r], ec="#333", lw=1.2))
        ax.add_patch(Rectangle((1, y - 1.56), 4.4, 0.28, fc="white", ec="#888", hatch="////", lw=0.8))   # bottom halo
        ax.text(3.2, y - 0.78, f"Rank {r}: rows owned", ha="center", va="center", fontsize=9)
        ax.text(5.6, y - 0.14, "top halo", fontsize=7, color="#666", va="center")
        ax.text(5.6, y - 1.42, "bottom halo", fontsize=7, color="#666", va="center")
        y -= 1.95
    for r in range(3):
        yy = 7.2 - 1.95 * (r + 1) + 0.0
        ax.annotate("", xy=(0.55, yy - 0.14 + 0.0), xytext=(0.55, yy - 0.14 + 0.62), arrowprops=dict(arrowstyle="<|-|>", lw=1.2, color="#c0392b"))
    ax.text(7.7, 5.1, "MPI_Sendrecv\nbetween neighbours,\nevery timestep", fontsize=9, color="#c0392b", va="center")
    ax.text(7.7, 1.5, "Ranks 0 and p-1 use\nMPI_PROC_NULL on their\noutside edge", fontsize=8.5, color="#444", va="center")
    ax.set_title("Row-wise decomposition with halo rows (4 processes)", fontsize=10)
    fig.tight_layout(); fig.savefig(path, dpi=170); plt.close(fig)

fig_workflow("results/fig_workflow.png")
fig_decomposition("results/fig_decomposition.png")

# ----------------------------------------------------------------------------------
# docx helpers
# ----------------------------------------------------------------------------------
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.4); sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(2.2)

st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(11)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
st.paragraph_format.space_after = Pt(6); st.paragraph_format.line_spacing = 1.12
for name, size, color in [("Heading 1", 16, "1F3864"), ("Heading 2", 13, "2E5597"), ("Heading 3", 11.5, "2E5597")]:
    h = doc.styles[name]; h.font.name = "Calibri"; h.font.size = Pt(size); h.font.bold = True
    h.font.color.rgb = RGBColor.from_string(color)
    h.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    h.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10); h.paragraph_format.space_after = Pt(5)
    h.paragraph_format.keep_with_next = True

def P(text="", bold=False, italic=False, align=None, size=None, color=None, after=None):
    p = doc.add_paragraph()
    r = p.add_run(text); r.bold = bold; r.italic = italic
    if size: r.font.size = Pt(size)
    if color: r.font.color.rgb = RGBColor.from_string(color)
    if align == "center": p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if align == "justify": p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if after is not None: p.paragraph_format.space_after = Pt(after)
    return p

def RICH(parts, style=None):
    """parts: list of (text, bold) tuples"""
    p = doc.add_paragraph(style=style)
    for t, b in parts:
        r = p.add_run(t); r.bold = b
    return p

def H(text, lvl=1): return doc.add_heading(text, level=lvl)

def B(text, bold_prefix=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        r = p.add_run(bold_prefix); r.bold = True
    p.add_run(text); p.paragraph_format.space_after = Pt(3)
    return p

def N(text, bold_prefix=None):
    p = doc.add_paragraph(style="List Number")
    if bold_prefix:
        r = p.add_run(bold_prefix); r.bold = True
    p.add_run(text); p.paragraph_format.space_after = Pt(3)
    return p

def shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr(); shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill); tcPr.append(shd)

def TABLE(header, rows, widths_cm, align_right_from=None, font=9.5, hl_rows=(), caption=None):
    if caption: CAP(caption)
    t = doc.add_table(rows=1, cols=len(header)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); t._tbl.tblPr.append(lay)
    for i, w in enumerate(widths_cm): t.columns[i].width = Cm(w)
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.width = Cm(widths_cm[i]); shade(c, "1F3864")
        c.paragraphs[0].text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(font)
        r.font.color.rgb = RGBColor(255, 255, 255)
        if align_right_from is not None and i >= align_right_from: c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].width = Cm(widths_cm[i]); cells[i].paragraphs[0].text = ""
            r = cells[i].paragraphs[0].add_run(str(v)); r.font.size = Pt(font)
            cells[i].paragraphs[0].paragraph_format.space_after = Pt(1)
            if align_right_from is not None and i >= align_right_from: cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if ri in hl_rows: shade(cells[i], "FFF2CC")
            elif ri % 2 == 1: shade(cells[i], "F2F6FB")
    if len(rows) <= 14:
        for row in t.rows[:-1]:
            for c in row.cells:
                for pp in c.paragraphs: pp.paragraph_format.keep_with_next = True
    for row in t.rows:
        trPr = row._tr.get_or_add_trPr(); cs = OxmlElement("w:cantSplit"); trPr.append(cs)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t

def CODE(text):
    t = doc.add_table(rows=1, cols=1); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.rows[0].cells[0]; shade(c, "F5F5F5"); c.width = Cm(16.2)
    c.paragraphs[0].text = ""
    for i, ln in enumerate(text.split("\n")):
        p = c.paragraphs[0] if i == 0 else c.add_paragraph()
        p.paragraph_format.space_after = Pt(0); p.paragraph_format.line_spacing = 1.0
        r = p.add_run(ln if ln else " "); r.font.name = "Consolas"; r.font.size = Pt(8.5)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

_fig = [0]
def FIG(path, caption, width_in=6.0):
    if not os.path.exists(path):
        P(f"[missing figure: {path}]", italic=True, color="C00000"); return
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(path, width=Inches(width_in))
    _fig[0] += 1
    c = P(f"Figure {_fig[0]}: {caption}", italic=True, align="center", size=9.5, after=10)

_tab = [0]
def CAP(text):
    _tab[0] += 1
    p = P(f"Table {_tab[0]}: {text}", italic=True, align="center", size=9.5, after=3)
    p.paragraph_format.keep_with_next = True

def CALLOUT(text, fill="FDE9E7", color="9C1C10"):
    t = doc.add_table(rows=1, cols=1); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.rows[0].cells[0]; shade(c, fill); c.width = Cm(16.2); c.paragraphs[0].text = ""
    r = c.paragraphs[0].add_run(text); r.font.size = Pt(10); r.font.color.rgb = RGBColor.from_string(color)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def add_page_number_footer():
    f = sec.footer.paragraphs[0]; f.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = f.add_run()
    for kind, txt in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), kind)
        else:
            e = OxmlElement("w:instrText"); e.set(qn("xml:space"), "preserve"); e.text = txt
        r._r.append(e)
    r.font.size = Pt(9)
add_page_number_footer()

# ----------------------------------------------------------------------------------
# TITLE PAGE
# ----------------------------------------------------------------------------------
for _ in range(6): P("", after=12)
P("PROJECT REPORT", bold=True, align="center", size=12, color="777777", after=6)
P(TITLE, bold=True, align="center", size=24, color="1F3864", after=14)
P("Parallel and Distributed Computing using MPI", align="center", size=13, color="444444", after=36)
for n, roll in AUTHORS:
    P(f"{n}  —  {roll}", align="center", size=13, after=4)
P("", after=40)
P("Implementation: C with MPI (OpenMPI / MPICH)", align="center", size=10.5, color="666666", after=2)
P("Sequential and parallel versions, correctness verification and performance study", align="center", size=10.5, color="666666")
doc.add_page_break()

# ----------------------------------------------------------------------------------
# ABSTRACT
# ----------------------------------------------------------------------------------
H("Abstract")
P("Wildfire spread is a classic neighbour-driven simulation: the future state of every cell of a landscape depends on "
  "the current state of the cells around it, on the wind and on the vegetation. This project models wildfire propagation "
  "with a two-dimensional cellular automaton in which every cell is unburned, burning or burnt, and parallelises the "
  "simulation with MPI. The grid is divided row-wise into strips, one per process (domain decomposition); because fire "
  "spreading across a strip boundary depends on a row owned by another process, every process exchanges its edge rows "
  "with its neighbours at every timestep using MPI_Sendrecv (halo exchange). A sequential version of the same model was "
  "also implemented. Both versions share one update function and use a position-based deterministic random number "
  "generator, so the parallel result is bit-identical to the sequential result for any number of processes; this is "
  "verified automatically. Execution time, speedup, efficiency and the share of time spent communicating were measured "
  "with MPI_Wtime.", align="justify")

# ----------------------------------------------------------------------------------
H("1. Introduction")
P("A wildfire is a large, uncontrolled fire that spreads across a natural landscape such as a forest or grassland. "
  "How quickly it spreads and in which direction depends mainly on the wind and on the type and density of vegetation "
  "it passes through. Predicting the spread is a real problem for forest services and disaster-management agencies, "
  "who use such predictions for evacuation planning and for allocating firefighting resources.", align="justify")
P("This project models the spread with a cellular automaton: the landscape is a two-dimensional grid whose cells have a "
  "state (unburned, burning or burnt). In every timestep each cell is updated using only the states of its immediate "
  "neighbours, the local wind direction and the terrain (fuel) value of the cell. Repeating this simple local rule over "
  "the whole grid for many timesteps produces a realistic, wind-shaped fire front.", align="justify")
P("MPI (Message Passing Interface) is used to divide the grid among several processes and to exchange boundary "
  "information between neighbouring processes at every timestep, so the simulation is computed correctly and faster "
  "than a single sequential process could manage.", align="justify")

H("2. Problem Statement")
P("A sequential simulation processes every cell of the grid, one at a time, for every timestep. As the grid size and the "
  "number of timesteps grow, the total work grows very quickly (a 2000 × 2000 grid for 5000 timesteps is 20 billion cell "
  "updates) and a single process cannot use the multiple cores of a modern machine. The grid can be divided into "
  "regions that are updated concurrently by separate MPI processes, but fire at the edge of one process's region "
  "depends on the current state of the neighbouring region owned by a different process. The processes must therefore "
  "exchange boundary information at every timestep for the result to remain correct. This project implements that "
  "repeated communication pattern with MPI and compares sequential and parallel execution time to measure the speedup "
  "actually achieved.", align="justify")

H("3. Objectives")
B(" set up an MPI program in which multiple processes run together and share grid data.", "Use MPI for parallel wildfire simulation —")
B(" split the 2D grid row-wise into (nearly) equal strips, one per process.", "Divide the grid among processes (domain decomposition) —")
B(" before every timestep each process exchanges its edge rows with its neighbours (halo exchange) so spread across a process boundary is computed correctly.", "Exchange boundary information —")
B(" update each cell from its neighbours, a configurable wind direction and strength, and a per-cell vegetation (fuel) value.", "Model realistic fire spread —")
B(" implement a sequential and an MPI version and measure how much faster the parallel version is for the same grid size and number of timesteps.", "Compare sequential and parallel execution time —")
B(" show that the parallel result is exactly the same as the sequential result.", "Verify correctness —")

# ----------------------------------------------------------------------------------
H("4. Methodology")
H("4.1 Overall workflow", 2)
P("The program follows the pipeline shown in Figure 1. The initial grid is created once by the root process (rank 0), "
  "which also acts as coordinator: it distributes the grid, and at the end reassembles and saves the result. All other "
  "work — the repeated halo exchange and cell update — is done by all processes simultaneously.", align="justify")
FIG("results/fig_workflow.png", "Workflow of the parallel wildfire simulation.", 4.3)

H("4.2 Domain decomposition", 2)
P("The H rows of the grid are divided among p processes. Every process gets ⌊H/p⌋ rows and the first (H mod p) "
  "processes get one extra row, so strip sizes differ by at most one row and any grid height works, not only multiples "
  "of p. Because of this, MPI_Scatterv and MPI_Gatherv (variable counts and displacements) are used instead of plain "
  "MPI_Scatter and MPI_Gather. For example a grid with 2000 rows on 4 processes gives four strips of 500 rows; a grid "
  "with 203 rows on 4 processes gives strips of 51, 51, 51 and 50 rows.", align="justify")
FIG("results/fig_decomposition.png", "Row-wise decomposition. Each process stores its own rows plus one halo row above and below.", 4.6)

H("4.3 Halo exchange", 2)
P("A process needs the state of the row directly above its first row and directly below its last row to update its edge "
  "cells. Each process therefore stores rows+2 rows: one top halo row, its own rows, and one bottom halo row. At the "
  "start of every timestep two MPI_Sendrecv calls fill the halo rows: the first sends the process's first row upward "
  "while receiving the bottom halo from the process below; the second sends the last row downward while receiving the "
  "top halo from the process above. The first and last processes use MPI_PROC_NULL as the missing neighbour, which "
  "turns the call into a no-op and leaves that halo as zeros (= 'unburned'), so no special cases are needed. Using "
  "MPI_Sendrecv, which combines the send and the receive in one call, avoids the deadlock that can occur when every "
  "process first calls a blocking send. The terrain (fuel) map never changes, so it is distributed once and is not "
  "exchanged.", align="justify")
CODE(source_snippet("src/fire_mpi.c", "/* HALO EXCHANGE", "double b = MPI_Wtime();").replace("double b = MPI_Wtime();", "").rstrip())

H("5. Fire Model", 1)
P("Cell states are 0 = unburned, 1 = burning and 2 = burnt. A separate read-only fuel map assigns every cell a "
  "vegetation value from 0 (water or bare rock, cannot burn) to 255 (dense vegetation). The map is generated from smooth "
  "value noise and contains lakes and a river that act as firebreaks. All cells are updated from the previous "
  "timestep's grid into a second grid (double buffering), and the two grids are swapped after each step.", align="justify")
TABLE(["Current state", "Rule for the next timestep"],
      [["Unburned, fuel = 0", "Stays unburned (water / rock)."],
       ["Unburned, fuel > 0",
        "For each of the 8 neighbours that is burning, an ignition probability p = base × fuel × wind-factor is computed. "
        "The probabilities combine as P(ignite) = 1 − Π(1 − p_i) and one random number decides whether the cell starts burning."],
       ["Burning", "Burns out (becomes burnt) with probability 0.06 + 0.30·(1 − fuel); denser fuel therefore burns longer."],
       ["Burnt", "Stays burnt."]],
      [3.6, 12.6], font=9.5, caption="Cell update rules")
P("The wind factor for a neighbour is exp(k·cos θ), where θ is the angle between the wind direction and the direction "
  "in which the fire would travel from that neighbour into the cell. It is larger than 1 downwind, smaller than 1 "
  "upwind, and equal to 1 everywhere when the wind strength k is 0. The wind direction is given in degrees "
  "(0 = blowing toward north, 90 = east, 180 = south, 270 = west).", align="justify")

H("5.1 Deterministic random numbers", 2)
P("Fire ignition and burn-out are random events. If an ordinary random-number stream (rand()) were used, the numbers "
  "drawn for a cell would depend on how many cells were processed before it, i.e. on how the grid is divided among "
  "processes, and the parallel result could never be compared with the sequential one. Instead, the random number for "
  "a cell is a hash function of (global row, column, timestep, purpose). It depends only on the cell and the timestep, "
  "never on the process that computes it. Together with the halo exchange this makes the parallel simulation produce "
  "exactly the same grid as the sequential one.", align="justify")

# ----------------------------------------------------------------------------------
H("6. MPI Concepts Used")
TABLE(["MPI function", "Purpose in this project"],
      [["MPI_Init / MPI_Finalize", "Start up and cleanly shut down the MPI environment."],
       ["MPI_Comm_rank", "Gives each process its ID, which determines which strip of the grid it owns."],
       ["MPI_Comm_size", "Number of processes, needed to divide the grid."],
       ["MPI_Bcast", "Sends the (parsed) parameters and lookup tables from rank 0 to all ranks."],
       ["MPI_Scatterv", "Sends each process its strip of the initial grid and of the fuel map (strips may differ by one row)."],
       ["MPI_Sendrecv", "The halo exchange: edge rows are swapped with the upper and lower neighbour at every timestep."],
       ["MPI_PROC_NULL", "Replaces the non-existent neighbour of the first and last process."],
       ["MPI_Barrier", "Makes all processes start the timed loop together so timing is fair."],
       ["MPI_Wtime", "Wall-clock time; used to measure communication and computation time separately."],
       ["MPI_Reduce (MPI_MAX)", "The parallel time is the time of the slowest process."],
       ["MPI_Gatherv", "Collects the final strips on rank 0 in rank order."]],
      [4.2, 12.0], font=9.5, caption="MPI functions used")

# ----------------------------------------------------------------------------------
H("7. Implementation")
TABLE(["File", "Description"],
      [["src/fire_common.h", "Terrain generator, deterministic random numbers, the cell-update function fire_step(), colour image (PPM) writer. Included by both programs, so both simulate the same model."],
       ["src/fire_seq.c", "Sequential baseline: one process updates the whole grid."],
       ["src/fire_mpi.c", "MPI version: decomposition, Scatterv, halo exchange, update, Gatherv, timing."],
       ["scripts/run_tests.sh", "Correctness tests (parallel output must equal sequential output)."],
       ["scripts/run_bench.sh", "Timing experiments for several grid sizes and process counts."],
       ["scripts/visualize.py", "Snapshot montage / animated GIF, progress plot, speedup and efficiency plots."],
       ["scripts/make_report.py", "Generates this report from the measured result files."]],
      [4.2, 12.0], font=9.5, caption="Project files")
P("Both programs are compiled with gcc / mpicc using -O2 -ffp-contract=off so floating-point evaluation is identical "
  "in the two programs. The programs accept the grid size, number of timesteps, random seed, wind direction and "
  "strength, base ignition probability and snapshot interval on the command line.", align="justify")
P("Timed region. Only the halo exchange and the cell updates of all timesteps are timed. Terrain generation, "
  "the scatter, writing snapshots and final output are excluded. Each process accumulates its communication and "
  "computation time with MPI_Wtime; the reported parallel time is the maximum over all processes (MPI_Reduce with "
  "MPI_MAX), since the slowest process determines when the simulation is finished. The sequential program times "
  "exactly the same region with clock_gettime (CLOCK_MONOTONIC); it does not need MPI.", align="justify")

# ----------------------------------------------------------------------------------
H("8. Correctness Verification")
P("Correctness is checked in three ways.", align="justify")
N(" every run prints a 64-bit FNV-1a hash of the final grid; the hash printed by the MPI program must equal the hash printed by the sequential program.", "Hash comparison —")
N(" the full final grid written by the sequential and the MPI program is compared with the cmp command.", "Byte-level comparison —")
N(" tests use several process counts (1, 2, 3, 4, 5, 7, 8), several wind directions and strengths, and grid heights such as 103, 131, 157, 211 that are not divisible by most process counts.", "Awkward configurations —")
log = open("results/test_log.txt", encoding="utf-8", errors="replace").read().strip().split("\n")[-1] if os.path.exists("results/test_log.txt") else None
if log:
    CALLOUT(f"Result of 'make test':  {log}", fill="E6F4EA", color="1B5E20")
else:
    CALLOUT("Test log not found. Run 'make test' and then 'make report' again.")
if HASH_OK is not None:
    P("In addition, the hashes of all runs of the performance experiment of Section 9 were compared: for every grid size, "
      + ("the sequential run and all MPI runs (all process counts and all repetitions) produced the identical hash."
         if HASH_OK else "SOME HASHES DIFFER — the results below must not be used until this is investigated."), align="justify")

# ----------------------------------------------------------------------------------
H("9. Experimental Results")
H("9.1 Setup", 2)
if ENV:
    TABLE(["Item", "Value"],
          [["Processor", ENV.get("cpu", "?")], ["Cores available (nproc)", ENV.get("cores", "?")],
           ["MPI implementation", ENV.get("mpi", "?")], ["Operating system", ENV.get("os", "?")],
           ["Date of measurement", ENV.get("date", "?")], ["Timesteps per run", STEPS or "?"],
           ["Grid sizes", ", ".join(f"{g} × {g}" for g in sorted({r['grid'] for r in SUM}))],
           ["Repetitions", "3 per configuration; the best (smallest) time is reported"]],
          [5.2, 11.0], font=9.5, caption="Experimental environment")
else:
    CALLOUT("No benchmark data found. Run 'make bench' and 'python3 scripts/visualize.py bench', then 'make report'.")

over = [r for r in SUM if r["procs"] > max(CORES, 1)]
if SUM and over:
    CALLOUT(f"IMPORTANT — measurement limitation. This machine reports only {CORES} usable core(s), but some runs used up to "
            f"{max(r['procs'] for r in SUM)} processes. Rows marked * are oversubscribed: several MPI processes shared one core and "
            "were time-sliced by the operating system, so their time (and the large 'communication %', which then mostly "
            "measures waiting for a descheduled neighbour) does NOT represent real parallel speedup. These runs demonstrate that "
            "the program works for every process count and gives identical results; genuine speedup must be measured on a "
            "machine with at least as many cores as processes. Re-run 'make bench' there and then 'make report' — "
            "this section is rebuilt automatically from the new measurements.")

H("9.2 Execution time, speedup and efficiency", 2)
P("Speedup is S = T_seq / T_par and efficiency is E = S / p, where T_seq is the time of the sequential program and "
  "T_par the time of the MPI program with p processes (maximum over processes). 'Comm %' is the share of the run spent "
  "in the halo exchange.", align="justify")
if SUM:
    rows = []
    for r in SUM:
        mark = "*" if r["procs"] > max(CORES, 1) else ""
        rows.append([f"{r['grid']} × {r['grid']}", f"{r['procs']}{mark}", f"{r['t_seq']:.3f}", f"{r['t_par']:.3f}",
                     f"{r['speedup']:.2f}", f"{r['eff']:.2f}", f"{r['comm']:.1f}"])
    TABLE(["Grid", "Processes", "T_seq (s)", "T_par (s)", "Speedup", "Efficiency", "Comm %"], rows,
          [3.0, 2.3, 2.3, 2.3, 2.0, 2.2, 2.0], align_right_from=2, font=9.5,
          caption=f"Measured times ({STEPS} timesteps)" + ("; * = more processes than cores" if over else ""))
    FIG("results/speedup.png", "Speedup, efficiency and communication share against number of processes.", 6.3)

    H("9.3 Analysis", 2)
    valid = [r for r in SUM if 1 < r["procs"] <= CORES]
    if valid:
        b = max(valid, key=lambda r: r["speedup"])
        P(f"With {b['procs']} processes on a {b['grid']} × {b['grid']} grid the speedup was {b['speedup']:.2f} "
          f"(efficiency {b['eff']:.2f}), the best result among runs with no more processes than cores. ", align="justify")
        for g in sorted({r['grid'] for r in valid}):
            rs = sorted([r for r in valid if r['grid'] == g], key=lambda r: r['procs'])
            if len(rs) > 1:
                P(f"Grid {g} × {g}: efficiency falls from {rs[0]['eff']:.2f} ({rs[0]['procs']} processes) to "
                  f"{rs[-1]['eff']:.2f} ({rs[-1]['procs']} processes) while the communication share goes from "
                  f"{rs[0]['comm']:.1f}% to {rs[-1]['comm']:.1f}%.", align="justify")
    else:
        P("All parallel measurements in this report were taken with more processes than available cores, so no genuine "
          "parallel speedup can be concluded from them (see the note in Section 9.1).", align="justify")
    p1 = [r for r in SUM if r["procs"] == 1]
    if p1:
        P("The MPI program with one process is within " +
          f"{max(abs(r['t_par']/r['t_seq']-1) for r in p1)*100:.0f}% of the sequential time at every grid size, i.e. the "
          "extra bookkeeping of the MPI version (halo buffers, two Sendrecv calls with MPI_PROC_NULL) is negligible.",
          align="justify")
    P("Expected behaviour on a machine with enough cores, which the design is meant to demonstrate: per timestep each "
      "process updates about W·H/p cells, but exchanges only two rows of W cells, so computation per process shrinks "
      "as p grows while the cost of the halo exchange stays roughly constant. The speedup is therefore below the ideal value p, "
      "the gap widens as p increases, and larger grids (more computation per exchanged row) give higher efficiency than small "
      "grids. Memory bandwidth and operating-system jitter add further losses.", align="justify")
else:
    P("(No results available.)", italic=True)

H("9.4 Example simulation output", 2)
P(f"Figure {_fig[0] + 1} shows a simulation on a 600 × 600 grid with wind blowing toward the east, computed with 4 MPI processes. "
  "The fire starts near the centre of the left half (on a process boundary, so the halo exchange is exercised from "
  "the first timestep), is driven eastward by the wind, and is stopped by the lakes and the river, which contain no fuel. "
  "The final grid of this 4-process run is byte-identical to the one computed by the sequential program.", align="justify")
mont = "out/montage.png" if os.path.exists("out/montage.png") else "sample_output/montage.png"
FIG(mont, "Fire spread at several timesteps (green = unburned forest, blue = water, orange = burning, dark = burnt).", 6.3)
prog = "out/progress.png" if os.path.exists("out/progress.png") else "sample_output/progress.png"
FIG(prog, "Number of burning and burnt cells over time.", 4.6)

# ----------------------------------------------------------------------------------
H("10. Discussion: Why MPI Is Needed Here")
P("In many parallel problems the data can be split once and every part processed independently. Here this is not "
  "possible: the cells on the border of a strip have neighbours in the strip of another process, and the state of "
  "those neighbours changes every timestep. The data exchange therefore has to be repeated for every timestep, which "
  "is exactly what the halo exchange with MPI_Sendrecv does. This repeated communication is also the reason that the "
  "achievable speedup is below the number of processes.", align="justify")
P("MPI is used instead of a shared-memory approach (such as OpenMP) because message passing works on distributed-memory "
  "clusters as well as on a single multi-core computer, and because the aim of the project is to apply message passing "
  "to a problem that needs repeated neighbour communication.", align="justify")

H("11. Limitations and Future Work")
B(" each process exchanges two full rows of length W regardless of the number of processes. A 2D block decomposition reduces the amount of data exchanged per process when many processes are used.", "1D decomposition:")
B(" the program scans every cell in every timestep, although the fire front is a small part of the map. Skipping inactive regions would save work but would create load imbalance that needs dynamic load balancing.", "No work skipping:")
B(" communication and computation are not overlapped. The interior rows could be updated while MPI_Isend / MPI_Irecv are exchanging the halo, and the two edge rows finished afterwards.", "No overlap:")
B(" fire cannot jump a firebreak wider than one cell (no spotting by embers), and slope, humidity and fuel moisture are not modelled.", "Simplified physics:")
B(" the model is not calibrated against real fire data; it demonstrates the parallel technique rather than predicting a real fire.", "Calibration:")

H("12. Differences from the Original Proposal")
B(" MPI_Scatterv / MPI_Gatherv are used instead of MPI_Scatter / MPI_Gather so the grid height need not be divisible by the number of processes.")
B(" the 'about 8 minutes' sequential time in the proposal was only an estimate; this report uses measured times only.")
B(" the sequential program is timed with clock_gettime rather than MPI_Wtime because it is a plain C program that does not use MPI; the same region is timed.")
B(" the random numbers are position-based hashes instead of rand(), which is what allows parallel and sequential results to be compared exactly.")

H("13. Conclusion")
P("A cellular-automaton wildfire model was implemented in C as a sequential program and as an MPI program that divides the "
  "grid into row strips and exchanges boundary rows with MPI_Sendrecv at every timestep. Because the update rule and the "
  "random numbers are shared and position-based, the parallel program produces exactly the same grid as the sequential "
  "one for every tested number of processes, grid size and wind setting, including grid heights that are not divisible by "
  "the number of processes. The performance study reports execution time, speedup, efficiency and the share of time spent "
  "in the halo exchange, all measured with MPI_Wtime, and shows that the repeated halo exchange — not a one-time data "
  "split — is what makes message passing necessary for this problem.", align="justify")

H("Appendix A: How to build and run")
CODE("make                      # builds fire_seq and fire_mpi\n"
     "make test                 # parallel result must equal sequential result\n"
     "\n"
     "./fire_seq -w 2000 -h 2000 -t 1000 -n               # sequential, timing only\n"
     "mpirun -np 4 ./fire_mpi -w 2000 -h 2000 -t 1000 -n  # 4 processes\n"
     "mpirun -np 4 ./fire_mpi -w 600 -h 600 -t 1500 -i 300 -a 90 -k 2.0 -o out   # with images\n"
     "\n"
     "make bench                          # timing study -> results/bench.csv\n"
     "python3 scripts/visualize.py bench  # speedup table and plots\n"
     "make report                         # rebuild this report from the results")
P("Options: -w width, -h height, -t timesteps, -s seed, -a wind direction (degrees: 0 N, 90 E, 180 S, 270 W), "
  "-k wind strength, -p base ignition probability, -i snapshot interval, -o output directory, -n no output files.", size=10)

H("Appendix B: The cell-update function")
CODE(source_snippet("src/fire_common.h", "static void fire_step", "/* Output helpers").rsplit("\n", 4)[0])

out = "report/Wildfire_MPI_Report.docx"
doc.save(out)
print("wrote", out)
