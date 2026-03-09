BUILD_DIR := build
HEADERS := $(wildcard *.hpp)

CXX := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -pedantic

.DEFAULT_GOAL := all

.PHONY: all clean

all: $(BUILD_DIR)/hops

$(BUILD_DIR)/hops: hops.cpp $(HEADERS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) hops.cpp -o $(BUILD_DIR)/hops

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
