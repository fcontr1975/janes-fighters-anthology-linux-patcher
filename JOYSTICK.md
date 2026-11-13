# Joystick mapping

FA.EXE reads joystick state through WinMM, so Linux joystick calibration tools
do not necessarily change the values that FA receives through Wine. The
game-local `FAJoystick.dll` adapter remaps the WinMM values returned to FA;
it does not alter Wine or other applications.

The default configuration swaps the WinMM Z and R axes (`Rx` in Wine's
joystick panel) to match the requested layout. To inspect the host joystick
and edit mappings, run:

```sh
./configure-joystick.sh
```

The script opens Wine's joystick properties for identifying physical axes and
buttons, then asks for the FA-specific mappings. Close and restart FA after
changing them. The control panel shows the physical axes before the adapter is
applied.

`FA-JOYSTICK.INI` is stored beside `FA.EXE`:

- `AxisMap` lists the physical source for logical X, Y, Z, R, U, and V, in
  that order. For example, `X,Y,R,Z,U,V` swaps Z and Rx.
- `InvertAxes` lists logical axes to invert, such as `Y,V`.
- `ButtonMap` lists the physical button for each logical button, in order.
  `0` disables a logical button. An empty value restores identity mapping.

The adapter is built from `joystick/FAJoystick.c` with
`./build-joystick-adapter.sh`. FA is a 32-bit executable, so the build uses
`i686-w64-mingw32-gcc`. The patcher adds the adapter as an executable import;
keep `FAJoystick.dll` beside `FA.EXE`.
