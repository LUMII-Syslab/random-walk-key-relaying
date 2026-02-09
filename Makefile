CXX ?= g++
CXXFLAGS ?= -std=c++20 -O2 -Wall -Wextra -pedantic

BUILD_DIR := build
BIN := $(BUILD_DIR)/simulate
SRC := simulate/simulate.cpp

# Default edge list (override: `make run EDGE=graphs/nsfnet/nsfnet_edges.csv`)
EDGE ?= graphs/secoqc/edges.csv

.PHONY: all run clean

all: $(BIN)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BIN): $(SRC) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -o $@ $<

run: $(BIN)
	./$(BIN) "$(EDGE)"

clean:
	rm -rf $(BUILD_DIR)

