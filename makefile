# cyberdeck top-level build
#
#   make            build uxn2 and every ROM with a source under roms/
#   make disk       populate a Varvara disk directory (default ~/deck)
#   make test       run the toolchain and device tests
#   make install    install uxn2 into $(PREFIX)/bin
#
# ROM sources are assembled with the Drifblim ROM bundled in uxn2, running
# headlessly inside uxn2 itself, so the only host dependency is SDL2.

UXN2   := uxn2/bin/uxn2
ASM    := uxn2/bin/drifblim.rom
BUILD  := build
DISK   ?= $(HOME)/deck
PREFIX ?= /usr/local

ABS_UXN2 := $(abspath $(UXN2))
ABS_ASM  := $(abspath $(ASM))

# ROMs assembled from sources in roms/. Add a line per ROM.
ROMS := $(BUILD)/potato.rom $(BUILD)/noodle.rom $(BUILD)/drifblim.rom $(BUILD)/hello.rom
# ROMs that only exist as binaries (until their sources land in roms/).
BIN_ROMS := roms/potato/etc/nasu.rom

all: $(UXN2) roms

roms: $(ROMS)

$(UXN2): uxn2/src/uxn2.c $(wildcard uxn2/src/*.c)
	$(MAKE) -C uxn2 bin/uxn2

# Drifblim is bootstrapped from its hex dump through xh.rom, which reads stdin
# and therefore needs the SDL event loop; the dummy drivers keep it headless.
$(ASM): $(UXN2) uxn2/etc/utils/drifblim.rom.txt uxn2/etc/utils/xh.rom
	cd uxn2 && SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy sh -c 'cat etc/utils/drifblim.rom.txt | bin/uxn2 etc/utils/xh.rom > bin/drifblim.rom'

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/drifblim.rom: $(ASM) | $(BUILD)
	cp $(ASM) $@

# Potato includes its other files with ~src/... so it assembles from its own dir.
$(BUILD)/potato.rom: $(ASM) $(wildcard roms/potato/src/*.tal) | $(BUILD)
	cd roms/potato && $(ABS_UXN2) $(ABS_ASM) src/potato.tal $(abspath $@)

$(BUILD)/noodle.rom: $(ASM) roms/noodle.tal | $(BUILD)
	cd roms && $(ABS_UXN2) $(ABS_ASM) noodle.tal $(abspath $@)

# Our own ROMs live in roms/deck and include shared code from roms/lib
# with ~lib/..., so they assemble from roms/ (Drifblim resolves ~ from cwd).
$(BUILD)/%.rom: roms/deck/%.tal $(ASM) $(wildcard roms/lib/*.tal) | $(BUILD)
	cd roms && $(ABS_UXN2) $(ABS_ASM) deck/$*.tal $(abspath $@)

roms/lib/atari8.tal: tools/icn2tal.py roms/potato/etc/font.icn
	python3 tools/icn2tal.py font-atari8 roms/potato/etc/font.icn > $@

# Populate a disk directory: built ROMs and Potato's assets go in, but files
# a user may have edited (src/, lxmf/, .theme, .wallpaper) are never overwritten.
disk: roms
	mkdir -p $(DISK)/src/lib $(DISK)/lxmf
	install -m 644 roms/lib/*.tal $(DISK)/src/lib/
	install -m 644 $(ROMS) $(DISK)/
	for r in $(BIN_ROMS); do install -m 644 $$r $(DISK)/; done
	[ -e $(DISK)/.wallpaper ] || install -m 644 roms/potato/.wallpaper $(DISK)/.wallpaper
	install -m 644 roms/makefile $(DISK)/src/makefile
	[ -e $(DISK)/src/hello.tal ] || install -m 644 roms/deck/hello.tal $(DISK)/src/hello.tal
	$(MAKE) -C $(DISK)/src UXN2=$(ABS_UXN2) ASM=../drifblim.rom

# Tests: uxn2's own suite, the Reticulum device against the stub bridge, the
# bridge's protocol tests, and (when rns/lxmf are importable) an LXMF
# roundtrip between two nodes. Use PY=.venv/bin/python after `make venv`.
PY ?= python3
PY_ABS := $(if $(findstring /,$(PY)),$(abspath $(PY)),$(PY))

uxn2/bin/reticulum.rom: $(ASM) uxn2/etc/tests/reticulum.tal
	$(UXN2) $(ASM) uxn2/etc/tests/reticulum.tal $@

test: $(ASM) uxn2/bin/reticulum.rom
	SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy $(MAKE) -C uxn2 tests
	cd bridge && $(PY_ABS) -m unittest discover -s tests -t . -v

# Laptop-side virtualenv with the bridge installed editable.
venv: .venv/bin/cyberdeck-bridge

.venv/bin/cyberdeck-bridge: bridge/pyproject.toml
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -e bridge

install: $(UXN2)
	install -d $(PREFIX)/bin
	install -m 755 $(UXN2) $(PREFIX)/bin/uxn2

clean:
	rm -rf $(BUILD) uxn2/bin roms/potato/bin

.PHONY: all roms disk test venv install clean
