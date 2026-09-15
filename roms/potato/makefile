ID=potato
DIR=~/roms
ASM=uxncli ${DIR}/drifblim.rom
LIN=uxncli ${DIR}/uxnlin.rom
EMU=uxn11
ROM=bin/${ID}.rom

all: ${ROM}

lint:
	@ ${LIN} src/${ID}.tal
test:
	@ ${EMU} ${ROM} lemon15x12.icn
run: all
	@ ${EMU} ${ROM}
clean:
	@ rm -f ${ROM} ${ROM}.sym
install: ${ROM}
	@ cp ${ROM} ${DIR}
uninstall:
	@ rm -f ${DIR}/${ID}.rom

.PHONY: all clean lint run install uninstall

${ROM}: src/*
	@ mkdir -p bin
	@ ${ASM} src/${ID}.tal ${ROM}
