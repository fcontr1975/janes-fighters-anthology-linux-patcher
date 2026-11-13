# Jane's Fighters Anthology on Linux

This guide installs the game from your original CD-ROM. This package contains
only the Linux compatibility helpers; it does not contain the game, its data,
or a CD key. Use your own retail disc and its key, if requested.

The steps below use `~/Games/FA` as the game folder. Keeping this location
makes the commands easier to follow.

## What you need

- Your Fighters Anthology CD-ROM and a working CD/DVD drive
- Wine that can run 32-bit Windows programs
- Python 3
- The 32-bit MinGW-w64 compiler (`i686-w64-mingw32-gcc`) to build the
  per-game joystick adapter
- About 150 MB of free space for the game's Digital install, plus room for
  saved missions and pilots

Install Wine, Python 3, and the 32-bit MinGW-w64 compiler from your Linux
distribution's Software app or package manager. Package names vary by
distribution; the compiler package must provide
`i686-w64-mingw32-gcc`. If you need help installing Wine, follow the official
Wine instructions for your distribution at
[WineHQ's download guide](https://wiki.winehq.org/Download). Do not run Wine
or the game as `root` or with `sudo`.

## 1. Prepare the game folder

1. Open your Home folder in the file manager.
2. Create a folder named `Games`, then a folder inside it named `FA`.
   The full location should be `~/Games/FA`.
3. Copy the compatibility files from this package into `~/Games/FA`,
   preserving the `joystick/` subfolder. This includes `launch.sh`,
   `patch-fa.py`, `build-joystick-adapter.sh`, `configure-joystick.sh`,
   `configure-joystick.py`, `FA-JOYSTICK.INI`, `JOYSTICK.md`, and
   `joystick/FAJoystick.c`.

The launcher treats the folder containing itself as the game folder. The
installer must put the game files in this same `~/Games/FA` folder.

## 2. Start the CD installer with Wine

1. Insert the CD and open it in the file manager. Find `setup.exe`. On the
   media layout checked for this guide, it is inside `FA_1_00F`.
2. Open a Terminal in the folder containing `setup.exe`. Many file managers
   offer **Open in Terminal** when you right-click the folder. Otherwise,
   open Terminal, type `cd ` (including the space), drag that folder into the
   Terminal window, and press Enter.
3. Start the installer with this command:

   ```sh
   WINEPREFIX="$HOME/Games/FA/.wine-prefix" wine ./setup.exe
   ```

   If your CD shows the filename with different capitalization, use the
   spelling shown by the file manager. Wine may take a little while to set up
   its first-time environment. Let it finish.

This command is important: it makes the installer use the same private Wine
environment that `launch.sh` will use. For this guide, do not double-click
`setup.exe` or start it with `sudo`.

## 3. Install the game

Follow the installer's prompts and use your own CD key if it asks for one.
Keep the CD in the drive during installation.

When asked where to install, change the default location so the game is
installed in `~/Games/FA`. The installer uses Windows-style paths. Wine's
`Z:` drive points to the Linux filesystem, so the destination will look like
`Z:\home\YOUR-LINUX-USER\Games\FA`.

To find your home-folder path, open another Terminal and run:

```sh
echo "$HOME"
```

For example, if it prints `/home/alex`, enter
`Z:\home\alex\Games\FA` as the install destination. If it prints a different
path, use that path after `Z:` and change the slashes to backslashes. Do not
leave the installer pointed at its default `C:\...` location; the launcher
needs `FA.EXE` and the game files beside `launch.sh`.

If the installer offers a choice between MIDI and Digital music, choose
Digital to keep the music on the hard drive. MIDI music plays from the CD.
If a separate DirectX 5 installer is offered, skip it; Wine provides the
DirectDraw support this setup needs. If the installer offers to start the
game immediately, decline and use the Linux launcher in the next step.

## 4. Start the game

Open a Terminal in `~/Games/FA` and run:

```sh
./launch.sh
```

On first launch, the script builds the 32-bit `FAJoystick.dll` adapter if
needed. The patcher verifies `FA.EXE`, adds the adapter import, and applies the
Wine compatibility, focus-loss recovery, and HD display patches. The game
will have 1280x720 and 1920x1080 choices under **Preferences > Screen
resolution**; 640x480 remains available. The patcher also fixes rendering at
the HD resolutions. It saves `FA.EXE.orig` if that backup does not already
exist and refuses to modify an unrecognized executable. The launcher then
creates or updates the local `.wine-prefix` and starts the game. Leave the
Terminal open while Wine starts. Keep the CD in the drive if the game asks
for it.

### Configure joystick mappings

The adapter applies mappings only to Fighters Anthology; it does not change
Wine or other applications. By default it swaps the game's Z and R (Rx) axes.
To identify your controller's physical axes and change axes, inversion, or
button mappings, run:

```sh
./configure-joystick.sh
```

The script opens Wine's joystick properties and then prompts for the
game-specific mappings. Close and restart the game after changing them.
Details and mapping examples are in [JOYSTICK.md](./JOYSTICK.md).

If Linux says **Permission denied**, run this once from `~/Games/FA`, then
launch again:

```sh
chmod +x launch.sh
./launch.sh
```

## If something goes wrong

- **A required file is missing:** Check that the installer destination was
  `~/Games/FA` and that `FA.EXE`, `FA.SMS`, and the game DLLs are in that
  folder beside `launch.sh`.
- **“Not enough memory” appears:** The game can show this message if it
  cannot find `FA.SMS`. Check that it is beside `FA.EXE`.
- **The game cannot find the CD:** Leave the disc inserted. Open the Wine
  configuration for this game with
  `WINEPREFIX="$HOME/Games/FA/.wine-prefix" winecfg`. On the **Drives** tab,
  make sure drive `D:` points to the folder where Linux mounted the CD.
- **Wine, wineboot, or Python is reported missing:** Install Wine (including
  `wineboot`) or Python 3 using your distribution's Software app or package
  manager, then try again.
- **The joystick adapter cannot be built:** Install the 32-bit MinGW-w64
  compiler that provides `i686-w64-mingw32-gcc`, then run `./launch.sh`
  again.

If you ask for help, include your Linux distribution, Wine version, and the
exact error message. Do not post your CD key.


## Advanced users

If you have already copied the installed Fighters Anthology files from both
CDs to your machine, you can skip running the installer:

1. Put all the compatibility files listed in step 1 in the folder you want to
   use for the game, such as `~/Games/FA`, preserving the `joystick/`
   subfolder.
2. Copy the game files from both CDs into that same folder. Merge the files
   from the two discs; do not leave the game files only inside separate
   `CD1` and `CD2` subfolders. In particular, `FA.EXE`, `FA.SMS`,
   `WAIL32.DLL`, `CDRVDL32.DLL`, `CDRVHF32.DLL`, and `msapi.dll` must be
   alongside `launch.sh`. The launcher builds `FAJoystick.dll` from
   `joystick/FAJoystick.c` when needed.
3. Open a Terminal in the game folder and start the game:

   ```sh
   ./launch.sh
   ```

On the first launch, the script builds the joystick adapter if needed and
validates and patches `FA.EXE` for Wine, joystick remapping, focus-loss
recovery, and HD resolutions (keeping the original as `FA.EXE.orig`), creates
the local `.wine-prefix`, and starts the game. Configure mappings with
`./configure-joystick.sh` as described above. If the game asks for the CD,
insert it and make sure drive `D:` in this game's Wine configuration points
to the mounted disc, as described above.

This path assumes the copied files are already an installed game. If you
only copied the raw disc contents and do not have the required files in the
game folder, follow the CD-ROM installation steps instead.
