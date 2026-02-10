CXX ?= g++
CXXFLAGS ?= -std=c++20 -O2 -Wall -Wextra -pedantic

BUILD_DIR := build
BIN := $(BUILD_DIR)/simulate
SRC := simulate/simulate.cpp

# Default edge list (override: `make run EDGE=graphs/nsfnet/nsfnet_edges.csv`)
EDGE ?= graphs/geant/edges.csv

# Walk variant (REQUIRED, no default). Use: `make run WALK=R` (or NB, LRV)
WALK ?=

.PHONY: all run clean

all: $(BIN)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BIN): $(SRC) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -o $@ $<

run: $(BIN)
	@if [ -z "$(WALK)" ]; then echo "ERROR: WALK not set. Use: make run WALK=R|NB|LRV [EDGE=...]" >&2; exit 2; fi
	./$(BIN) "$(WALK)" "$(EDGE)"

clean:
	rm -rf $(BUILD_DIR)

