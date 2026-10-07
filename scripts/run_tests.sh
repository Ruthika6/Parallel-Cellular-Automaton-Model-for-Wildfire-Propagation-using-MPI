#!/bin/bash
# Correctness test: the MPI result must be IDENTICAL to the sequential result
# for every process count, wind setting and grid shape (incl. rows not divisible by p).
cd "$(dirname "$0")/.." || exit 1
. scripts/mpi_env.sh

PROCS="${PROCS:-1 2 3 4 5 7 8}"
# cases:  "W H steps seed wind_deg wind_k"
CASES=(
  "120 120 200 1  90  1.5"     # east wind
  "200 103 300 7 225  2.0"     # SW wind, 103 rows (prime -> never divisible)
  "150 157 250 42  0  0.0"     # no wind
  "97  211 400 5 135  3.0"     # strong SE wind, narrow grid
)
fail=0; total=0
for c in "${CASES[@]}"; do
  set -- $c
  W=$1; H=$2; T=$3; S=$4; A=$5; K=$6
  ref=$(./fire_seq -w $W -h $H -t $T -s $S -a $A -k $K -n | sed -n 's/.*hash=\([0-9a-f]*\).*/\1/p')
  line="grid ${W}x${H} t=$T wind=${A}deg k=$K  seq=$ref  "
  for p in $PROCS; do
    [ "$p" -gt "$H" ] && continue
    got=$($MPIRUN -np $p ./fire_mpi -w $W -h $H -t $T -s $S -a $A -k $K -n | sed -n 's/.*hash=\([0-9a-f]*\).*/\1/p')
    total=$((total+1))
    if [ "$got" == "$ref" ]; then line+="p$p:OK "; else line+="p$p:FAIL($got) "; fail=$((fail+1)); fi
  done
  echo "$line"
done

# byte-for-byte comparison of the full output grid
echo
echo "Byte-level comparison of final grids (cmp):"
rm -rf out_test; ./fire_seq -w 160 -h 131 -t 250 -o out_test >/dev/null
for p in 2 3 5; do
  $MPIRUN -np $p ./fire_mpi -w 160 -h 131 -t 250 -o out_test >/dev/null
  if cmp -s out_test/seq_final.bin out_test/mpi_p${p}_final.bin; then echo "  p=$p identical"; else echo "  p=$p DIFFERENT"; fail=$((fail+1)); fi
done
rm -rf out_test

echo
if [ $fail -eq 0 ]; then echo "ALL $total CHECKS PASSED: parallel output == sequential output"; else echo "$fail FAILURES"; exit 1; fi
