# A potato

[Potato](https://wiki.xxiivv.com/site/potato.html) is a desktop environment, written in [Uxntal](https://wiki.xxiivv.com/site/uxntal.html).

## Build

You must have an [Uxntal](https://git.sr.ht/~rabbits/uxn) assembler.

```sh
uxnasm src/potato.tal bin/potato.rom
uxnemu bin/potato.rom
```

If do not wish to assemble it yourself, you can download [potato.rom](https://rabbits.srht.site/potato/potato.rom).

[![builds.sr.ht status](https://builds.sr.ht/~rabbits/potato.svg)](https://builds.sr.ht/~rabbits/potato?)

## Manual

Since this is designed to be used principally on a handheld devices without a window manager, the controls are aimed at d-pad centric. The pattern here is using the B button to handle all window operations, and leave the A button to the applications. Alternatively, you can open a file with `mouse2`.

- `B+Up`, expand a window
- `B+Down`, tab a window
- `B+Right`, open a window
- `B+Left`, close a window

## Editing the theme

Saving the theme, from the tile or theme editor will create a hidden file called [.theme](https://wiki.xxiivv.com/site/theme.html), which can be opened and edited in [Nasu](https://wiki.xxiivv.com/site/nasu.html).

## Adding a wallpaper

The wallpaper is an invisible file called `.wallpaper` in the working directory, the file is a [1bpp icn](https://wiki.xxiivv.com/site/icn_format.html) of the size of the desktop. The wallpaper image can be created with [Noodle](https://wiki.xxiivv.com/site/noodle.html).

## TODO

- Change cursor icon on alt mod for drag.
- Fix mouse picking issue in Play app.
- Terminal.
- Remove scrollbar in text editor and add line numbers.
- Hex Viewer.
- `.wallpaper` should open as Picture.

## Support

- [theme](https://wiki.xxiivv.com/site/theme.html)
- [snarf](https://wiki.xxiivv.com/site/snarf.html)

