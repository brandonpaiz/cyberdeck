# Assembles every .tal in this directory into a .rom one level up, so the
# result sits next to potato.rom and can be launched from the desktop.
# On the deck this runs automatically whenever a file here changes
# (cyberdeck-build.path); output lands in ../build.log.
UXN2 ?= uxn2
ASM  ?= ../drifblim.rom
TALS := $(wildcard *.tal)
ROMS := $(patsubst %.tal,../%.rom,$(TALS))

all: $(ROMS)

../%.rom: %.tal
	$(UXN2) $(ASM) $< $@ && rm -f $@.sym

.PHONY: all
