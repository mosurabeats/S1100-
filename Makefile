# Build S1100FX: stock OS floppy in, patched OS floppy out.
#
#   1. Put Akai's S11K-430.EXE (S1100 OS v4.30 update) in original/
#      (or your own stock OS floppy image at original/S1100_OS.img)
#   2. make [MODS="banner vintage autochop"]   -> build/S1100FX.img
#      make first-test                         -> banner only, no new code
#   3. Copy the .img to a Gotek/HxC (FlashFloppy: host = akai)

PY       ?= python3
EXE      ?= original/S11K-430.EXE
STOCK    ?= original/S1100_OS.img
OS_NAME  ?= \#0
SPEC     ?= patches/s1100fx.toml
MODS     ?= banner vintage autochop
MOD_SPECS := $(foreach m,$(MODS),mods/$(m).toml)
OUT      := build/S1100FX.img

all: $(OUT)

$(STOCK): | $(EXE)
	$(PY) tools/sxd2img.py $(EXE) $@

build/stock_os.bin: $(STOCK) | build
	$(PY) tools/akaidisk.py probe $(STOCK)
	$(PY) tools/akaidisk.py get $(STOCK) "$(OS_NAME)" $@

build/s1100fx_os.bin: build/stock_os.bin $(SPEC) $(MOD_SPECS) src/fx.asm $(wildcard src/dsp/*) tools/patch.py
	$(PY) tools/patch.py $< $@ $(SPEC) $(MOD_SPECS)

first-test: build/stock_os.bin
	$(PY) tools/patch.py --no-payload $< build/first_test_os.bin $(SPEC) mods/banner.toml
	$(PY) tools/akaidisk.py put $(STOCK) "$(OS_NAME)" build/first_test_os.bin --replace -o build/S1100FX-first-test.img
	$(PY) tools/akaidisk.py ls build/S1100FX-first-test.img

$(OUT): build/s1100fx_os.bin $(STOCK)
	$(PY) tools/akaidisk.py put $(STOCK) "$(OS_NAME)" $< --replace -o $@
	$(PY) tools/akaidisk.py ls $@

ls: $(STOCK)
	$(PY) tools/akaidisk.py ls $(STOCK)

build:
	mkdir -p build

test:
	$(PY) -m unittest discover -s tests -v

emu:
	emu/mame/build.sh

test-emu:
	$(PY) -m unittest tests.test_mame -v

presets:
	$(PY) tools/vintage.py gen-inc > src/dsp/presets.inc

clean:
	rm -rf build

.PHONY: all first-test ls test emu test-emu presets clean
