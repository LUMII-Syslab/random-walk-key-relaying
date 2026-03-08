BUILD_DIR := build
TARGET := $(BUILD_DIR)/hops
SRC := cpp/hops.cpp
HEADERS := $(wildcard cpp/*.hpp)

CXX := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -pedantic

.DEFAULT_GOAL := $(TARGET)

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC) $(HEADERS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(SRC) -o $(TARGET)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
