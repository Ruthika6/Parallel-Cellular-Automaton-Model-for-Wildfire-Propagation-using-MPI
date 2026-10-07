# Source this file. Sets $MPIRUN for OpenMPI, MPICH or MS-MPI (Windows).
if [ -z "$MPIRUN" ]; then
  if command -v mpirun >/dev/null 2>&1; then
    if mpirun --version 2>&1 | grep -qi "open mpi"; then
      MPIRUN="mpirun --oversubscribe"
      [ "$(id -u)" = "0" ] && MPIRUN="$MPIRUN --allow-run-as-root"
    else
      MPIRUN="mpirun"
    fi
  else
    MPIRUN="mpiexec"        # MS-MPI on Windows
  fi
fi
export MPIRUN
