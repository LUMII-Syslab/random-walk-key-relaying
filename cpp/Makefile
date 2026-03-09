BUILD_DIR := build
CACHE_DIR := cache
HEADERS := $(wildcard *.hpp)

CXX := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -pedantic -pthread

.DEFAULT_GOAL := all

.PHONY: all clean

all: $(BUILD_DIR)/hops $(BUILD_DIR)/tput

$(BUILD_DIR)/hops: hops.cpp $(HEADERS) | $(BUILD_DIR)
	rm -rf $(CACHE_DIR)
	$(CXX) $(CXXFLAGS) hops.cpp -o $(BUILD_DIR)/hops

$(BUILD_DIR)/tput: tput.cpp $(HEADERS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) tput.cpp -o $(BUILD_DIR)/tput

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
