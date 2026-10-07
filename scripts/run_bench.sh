#!/bin/bash
# Benchmark: sequential vs MPI for several grid sizes and process counts.
# Override with env vars, e.g.:
#   SIZES="1000 2000" STEPS=1000 PROCS="1 2 4 8" REPEATS=3 bash scripts/run_bench.sh
cd "$(dirname "$0")/.." || exit 1
. scripts/mpi_env.sh

NCORES=$(nproc)
if [ -z "$PROCS" ]; then
  PROCS="1"; p=2; while [ $p -le $NCORES ]; do PROCS+=" $p"; p=$((p*2)); done
fi
SIZES="${SIZES:-500 1000 2000}"
STEPS="${STEPS:-500}"
REPEATS="${REPEATS:-3}"

mkdir -p results
OUT=results/bench.csv
echo "impl,procs,W,H,steps,repeat,time,comm,hash" > $OUT
{
  echo "cores=$NCORES"
  echo "cpu=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//')"
  echo "mpi=$($MPIRUN --version 2>&1 | head -1)"
  echo "os=$(uname -sr)"
  echo "date=$(date +%F)"
} > results/env.txt
echo "cores=$NCORES  sizes=[$SIZES]  steps=$STEPS  procs=[$PROCS]  repeats=$REPEATS"

parse() { sed -n 's/.*impl=\([a-z]*\) procs=\([0-9]*\) W=\([0-9]*\) H=\([0-9]*\) steps=\([0-9]*\) time=\([0-9.]*\) comm=\([0-9.]*\) hash=\([0-9a-f]*\).*/\1,\2,\3,\4,\5,'"$1"',\6,\7,\8/p'; }

for N in $SIZES; do
  for r in $(seq 1 $REPEATS); do
    ./fire_seq -w $N -h $N -t $STEPS -n | parse $r | tee -a $OUT
    for p in $PROCS; do
      $MPIRUN -np $p ./fire_mpi -w $N -h $N -t $STEPS -n | parse $r | tee -a $OUT
    done
  done
done
echo "saved $OUT   ->  now run: python3 scripts/visualize.py bench"
