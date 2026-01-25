.PHONY: build build-all run clean deps

# Binary name
BINARY=sparkctl

# Build directory
BUILD_DIR=build

# Go parameters
GOCMD=go
GOBUILD=$(GOCMD) build
GORUN=$(GOCMD) run
GOMOD=$(GOCMD) mod
GOCLEAN=$(GOCMD) clean

# Build flags
LDFLAGS=-ldflags "-s -w"

# Default target
all: deps build

# Install dependencies
deps:
	$(GOMOD) download
	$(GOMOD) tidy

# Build for current platform
build:
	$(GOBUILD) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY) .

# Run directly
run:
	$(GORUN) .

# Build for all platforms
build-all: deps
	@mkdir -p $(BUILD_DIR)
	@echo "Building for Linux (amd64)..."
	GOOS=linux GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY)-linux-amd64 .
	@echo "Building for Linux (arm64)..."
	GOOS=linux GOARCH=arm64 $(GOBUILD) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY)-linux-arm64 .
	@echo "Building for Windows (amd64)..."
	GOOS=windows GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY)-windows-amd64.exe .
	@echo "Building for macOS (amd64)..."
	GOOS=darwin GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY)-darwin-amd64 .
	@echo "Building for macOS (arm64)..."
	GOOS=darwin GOARCH=arm64 $(GOBUILD) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY)-darwin-arm64 .
	@echo "Done! Binaries are in $(BUILD_DIR)/"

# Clean build artifacts
clean:
	$(GOCLEAN)
	rm -rf $(BUILD_DIR)

# Show help
help:
	@echo "Available targets:"
	@echo "  deps       - Download and tidy dependencies"
	@echo "  build      - Build for current platform"
	@echo "  build-all  - Build for all platforms (linux, windows, macos)"
	@echo "  run        - Run directly without building"
	@echo "  clean      - Remove build artifacts"
