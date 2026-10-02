# Build S1100FX: stock OS floppy in, patched OS floppy out.
#
#   1. Put an image of your stock S1100 OS floppy at original/S1100_OS.img
#   2. make OS_NAME="<name shown by make ls>" [MODS="banner vintage autochop"]
#   3. Copy build/S1100FX.img to a Gotek/HxC (FlashFloppy: host = akai)

PY       ?= python3
STOCK    ?= original/S1100_OS.img
OS_NAME  ?= S1100 OS
SPEC     ?= patches/s1100fx.toml
MODS     ?= banner vintage autochop
MOD_SPECS := $(foreach m,$(MODS),mods/$(m).toml)
OUT      := build/S1100FX.img

all: $(OUT)

build/stock_os.bin: $(STOCK) | build
	$(PY) tools/akaidisk.py probe $(STOCK)
	$(PY) tools/akaidisk.py get $(STOCK) "$(OS_NAME)" $@

build/s1100fx_os.bin: build/stock_os.bin $(SPEC) $(MOD_SPECS) src/fx.asm $(wildcard src/dsp/*) tools/patch.py
	$(PY) tools/patch.py $< $@ $(SPEC) $(MOD_SPECS)

$(OUT): build/s1100fx_os.bin $(STOCK)
	$(PY) tools/akaidisk.py put $(STOCK) "$(OS_NAME)" $< --replace -o $@
	$(PY) tools/akaidisk.py ls $@

ls: $(STOCK)
	$(PY) tools/akaidisk.py ls $(STOCK)

build:
	mkdir -p build

test:
	$(PY) -m unittest discover -s tests -v

presets:
	$(PY) tools/vintage.py gen-inc > src/dsp/presets.inc

clean:
	rm -rf build

.PHONY: all ls test presets clean
