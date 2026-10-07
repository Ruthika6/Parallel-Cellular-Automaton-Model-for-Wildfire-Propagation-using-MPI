CC      = gcc
MPICC   = mpicc
CFLAGS  = -O2 -std=gnu99 -Wall -Wextra -ffp-contract=off
LDLIBS  = -lm
MPILIBS =
# Windows (MSYS2 + MS-MPI):  make MPICC=gcc MPILIBS=-lmsmpi

all: fire_seq fire_mpi

fire_seq: src/fire_seq.c src/fire_common.h
	$(CC) $(CFLAGS) -o $@ src/fire_seq.c $(LDLIBS)

fire_mpi: src/fire_mpi.c src/fire_common.h
	$(MPICC) $(CFLAGS) -o $@ src/fire_mpi.c $(LDLIBS) $(MPILIBS)

test: all
	@mkdir -p results
	bash scripts/run_tests.sh | tee results/test_log.txt

bench: all
	bash scripts/run_bench.sh

report:
	python3 scripts/make_report.py

clean:
	rm -rf fire_seq fire_seq.exe fire_mpi fire_mpi.exe out out_test

.PHONY: all test bench report clean
