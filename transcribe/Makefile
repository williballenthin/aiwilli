# VoxtralDictate Makefile
# Builds voxtral.c as a static library and links it into a Swift menubar app.
#
# Prerequisites:
#   - Xcode command line tools (xcode-select --install)
#   - voxtral.c submodule initialized (git submodule update --init)
#   - Model downloaded (./download_model.sh in deps/voxtral.c)
#
# Usage:
#   make              # Build everything
#   make clean        # Remove build artifacts
#   make install      # Copy binary + metallib to ~/.local/bin/
#   make run          # Build and run

# ---- Configuration ----

# Path to voxtral.c source (submodule in deps/)
VOXTRAL_SRC ?= deps/voxtral.c

# Build directory
BUILD_DIR = build

# Output binary
BINARY = VoxtralDictate

# Install location
INSTALL_DIR = $(HOME)/.local/bin

# ---- Toolchain ----

CC = clang
OBJCC = clang
SWIFTC = swiftc
AR = ar

# ---- Compiler flags ----

# Common C flags
CFLAGS = -O2 -Wall -std=c11

# MPS/Metal flags (Apple Silicon)
MPS_CFLAGS = -DUSE_MPS
MPS_OBJCFLAGS = -O2 -Wall -fobjc-arc
MPS_FRAMEWORKS = -framework Metal -framework Foundation -framework MetalPerformanceShaders

# Swift flags
SWIFTFLAGS = -O -import-objc-header VoxtralBridge.h

# Linker flags
LDFLAGS = -framework Cocoa -framework AVFoundation -framework Carbon \
          -framework Metal -framework Foundation -framework MetalPerformanceShaders \
          -framework Accelerate

# ---- voxtral.c source files ----
# (main.c is excluded — that's voxtral's CLI entry point, not ours)

VOX_C_SRCS = \
	$(VOXTRAL_SRC)/voxtral.c \
	$(VOXTRAL_SRC)/voxtral_audio.c \
	$(VOXTRAL_SRC)/voxtral_encoder.c \
	$(VOXTRAL_SRC)/voxtral_decoder.c \
	$(VOXTRAL_SRC)/voxtral_kernels.c \
	$(VOXTRAL_SRC)/voxtral_safetensors.c \
	$(VOXTRAL_SRC)/voxtral_tokenizer.c

VOX_OBJC_SRCS = \
	$(VOXTRAL_SRC)/voxtral_metal.m

# Object files
VOX_C_OBJS = $(patsubst $(VOXTRAL_SRC)/%.c,$(BUILD_DIR)/%.o,$(VOX_C_SRCS))
VOX_OBJC_OBJS = $(patsubst $(VOXTRAL_SRC)/%.m,$(BUILD_DIR)/%.o,$(VOX_OBJC_SRCS))
VOX_OBJS = $(VOX_C_OBJS) $(VOX_OBJC_OBJS)

# Static library
VOX_LIB = $(BUILD_DIR)/libvoxtral.a

# Swift object
SWIFT_OBJ = $(BUILD_DIR)/main.o

# ============================================================================
# Targets
# ============================================================================

.PHONY: all clean install run check-src

all: check-src $(BINARY)

# Verify voxtral.c source exists
check-src:
	@if [ ! -f "$(VOXTRAL_SRC)/voxtral.c" ]; then \
		echo "❌ voxtral.c source not found at: $(VOXTRAL_SRC)"; \
		echo ""; \
		echo "Initialize the submodule:"; \
		echo "  git submodule update --init"; \
		echo ""; \
		echo "Then download the model:"; \
		echo "  cd deps/voxtral.c && ./download_model.sh"; \
		exit 1; \
	fi

# ---- Create build directory ----

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

# ---- Compile voxtral C sources ----

$(BUILD_DIR)/%.o: $(VOXTRAL_SRC)/%.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(MPS_CFLAGS) -I$(VOXTRAL_SRC) -c $< -o $@

# ---- Generate Metal shader source header (embeds shader as C array) ----

$(BUILD_DIR)/voxtral_shaders_source.h: $(VOXTRAL_SRC)/voxtral_shaders.metal | $(BUILD_DIR)
	xxd -i $< | sed 's/deps_voxtral_c_voxtral_shaders_metal/voxtral_shaders_metal/g' > $@

# ---- Compile voxtral ObjC source (Metal backend) ----

$(BUILD_DIR)/voxtral_metal.o: $(VOXTRAL_SRC)/voxtral_metal.m $(BUILD_DIR)/voxtral_shaders_source.h | $(BUILD_DIR)
	$(OBJCC) $(MPS_OBJCFLAGS) $(MPS_CFLAGS) -I$(VOXTRAL_SRC) -I$(BUILD_DIR) -c $< -o $@


# ---- Archive static library ----

$(VOX_LIB): $(VOX_OBJS)
	$(AR) rcs $@ $^

# ---- Compile Swift ----

$(SWIFT_OBJ): main.swift VoxtralBridge.h | $(BUILD_DIR)
	$(SWIFTC) $(SWIFTFLAGS) -I$(VOXTRAL_SRC) -c main.swift -o $@

# ---- Link final binary ----

$(BINARY): $(SWIFT_OBJ) $(VOX_LIB)
	$(SWIFTC) $(SWIFT_OBJ) -L$(BUILD_DIR) -lvoxtral $(LDFLAGS) -o $@
	@echo ""
	@echo "✅ Built: $(BINARY)"
	@echo ""
	@echo "Run with: ./$(BINARY)"

# ---- Install ----

install: $(BINARY)
	mkdir -p $(INSTALL_DIR)
	cp $(BINARY) $(INSTALL_DIR)/
	@echo "✅ Installed to $(INSTALL_DIR)/$(BINARY)"

# ---- Run ----

run: $(BINARY)
	./$(BINARY)

# ---- Clean ----

clean:
	rm -rf $(BUILD_DIR) $(BINARY)
