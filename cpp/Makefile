BUILD_DIR := build
CACHE_DIR ?= /tmp/random-walk-key-relaying-cache
HEADERS := $(wildcard *.hpp)

CXX := g++

# Set DEBUG=0 for optimized builds.
DEBUG ?= 1

CXXFLAGS := -std=c++17 -Wall -Wextra -pedantic -pthread
ifeq ($(DEBUG),1)
	CXXFLAGS += -Og -g -fno-omit-frame-pointer
else
	CXXFLAGS += -O2
endif

.DEFAULT_GOAL := all

.PHONY: all clean

all: $(BUILD_DIR)/hops $(BUILD_DIR)/tput $(BUILD_DIR)/proactive

$(BUILD_DIR)/hops: hops.cpp $(HEADERS) | $(BUILD_DIR)
	rm -rf $(CACHE_DIR)
	$(CXX) $(CXXFLAGS) hops.cpp -o $(BUILD_DIR)/hops

$(BUILD_DIR)/tput: tput.cpp $(HEADERS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) tput.cpp -o $(BUILD_DIR)/tput

$(BUILD_DIR)/proactive: proactive.cpp $(HEADERS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) proactive.cpp -o $(BUILD_DIR)/proactive

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
