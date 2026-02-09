CXX ?= g++
CXXFLAGS ?= -std=c++20 -O2 -Wall -Wextra -pedantic

BUILD_DIR := build
BIN := $(BUILD_DIR)/simulate
SRC := simulate/simulate.cpp

# Default edge list (override: `make run EDGE=graphs/nsfnet/nsfnet_edges.csv`)
EDGE ?= graphs/geant/edges.csv
SRC_NODE ?= MIL
TGT_NODE ?= COP

.PHONY: all run clean

all: $(BIN)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BIN): $(SRC) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -o $@ $<

run: $(BIN)
	./$(BIN) "$(EDGE)" "$(SRC_NODE)" "$(TGT_NODE)"

clean:
	rm -rf $(BUILD_DIR)

