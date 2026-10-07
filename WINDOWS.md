# Running the project natively on Windows (no WSL)

Uses MSYS2 (gcc + make + bash) and Microsoft MPI (MS-MPI). No restart needed.

## 1. Install (once)
1. **MS-MPI runtime** - download and run `msmpisetup.exe` from Microsoft
   (search "Microsoft MPI download"), or in PowerShell: `winget install Microsoft.msmpi`
2. **MSYS2** - `winget install MSYS2.MSYS2`  (or the installer from msys2.org)
3. Open **"MSYS2 UCRT64"** from the Start menu (NOT PowerShell) and run:
   ```bash
   pacman -Syu                       # if the window closes, open MSYS2 UCRT64 again
   pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-msmpi make git
   export PATH="$PATH:/c/Program Files/Microsoft MPI/Bin"
   mpiexec -n 2 hostname             # must print the computer name twice
   ```
   (Put the `export PATH=...` line into `~/.bashrc` so you don't repeat it.)

## 2. Build and test (in the MSYS2 UCRT64 window)
```bash
cd /c/Users/Admin
git clone https://github.com/Ruthika6/Parallel-Cellular-Automaton-Model-for-Wildfire-Propagation-using-MPI.git
cd Parallel-Cellular-Automaton-Model-for-Wildfire-Propagation-using-MPI
make MPICC=gcc MPILIBS=-lmsmpi
make test MPICC=gcc MPILIBS=-lmsmpi          # expect: ALL 28 CHECKS PASSED
```
If Windows Firewall asks about mpiexec / smpd, click **Allow**.
If bash complains about `\r`, run: `sed -i 's/\r$//' scripts/*.sh`

## 3. Benchmark (still in MSYS2)
```bash
nproc                                          # logical cores
SIZES="500 1000 2000" STEPS=500 PROCS="1 2 4" REPEATS=3 bash scripts/run_bench.sh
```
Use at most as many processes as you have PHYSICAL cores (often nproc / 2).
Close other programs while it runs.

## 4. Plots and report (in PowerShell, normal Windows Python)
```powershell
cd C:\Users\Admin\Parallel-Cellular-Automaton-Model-for-Wildfire-Propagation-using-MPI
py -m pip install numpy matplotlib pillow python-docx
py scripts\visualize.py bench
py scripts\make_report.py
```
(No Python? `winget install Python.Python.3.12`, then reopen PowerShell.)
Result: `results\speedup.png`, `results\summary.csv`, `report\Wildfire_MPI_Report.docx`.

## 5. Upload results
Upload the `results` and `report` folders to GitHub (Add file -> Upload files).
