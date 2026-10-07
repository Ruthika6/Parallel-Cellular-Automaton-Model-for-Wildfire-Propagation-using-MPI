# Source this file. Sets $MPIRUN for either OpenMPI or MPICH.
if [ -z "$MPIRUN" ]; then
  if mpirun --version 2>&1 | grep -qi "open mpi"; then
    MPIRUN="mpirun --oversubscribe"
    [ "$(id -u)" = "0" ] && MPIRUN="$MPIRUN --allow-run-as-root"
  else
    MPIRUN="mpirun"
  fi
fi
export MPIRUN
