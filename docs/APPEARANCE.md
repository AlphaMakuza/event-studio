# Appearance comparison

Use **Glass / Original** in the browser or editor title bar. Both windows
follow the same choice. The switch keeps the current recording, project,
search, view mode, and analysis state; no restart is needed. The preference
is stored separately from project/session data.

**Original** preserves the palette, stylesheets, hand-drawn view/window icons,
and text-only controls from immediately before this refresh. The comparison
selector itself is new. The original source files and screenshots are also
saved locally under `artifacts/appearance-comparison/`.

**Glass** uses a consistent Phosphor icon family through QtAwesome, cool
cyan accents, layered translucent fills, directional reflections, brighter
upper edges and darker lower edges. Corners stay at 0–2 pixels. Scientific
images and plots are not blurred or recolored by the appearance switch.
Play/Pause icons follow playback state. Text labels and accessible names
remain available alongside icons.

This is a Liquid Glass inspired Qt treatment, not Apple's native material
or a physical refraction simulation. On Windows 11 build 22621 and later,
the app requests the documented DWM transient-window acrylic backdrop and
square outer corners. Windows controls the resulting material and may
reduce transparency. Unsupported platforms and rejected requests retain
the painted glass surface. Offscreen screenshots show this fallback;
they cannot demonstrate desktop blur.

Native API: [Microsoft DWM system backdrops](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type).
Icon library: [QtAwesome](https://github.com/spyder-ide/qtawesome), using
[Phosphor](https://github.com/phosphor-icons/phosphor-icons).

## Capture previews

```powershell
.\.venv\Scripts\python.exe -m scripts.preview_appearance --appearance classic --label original
.\.venv\Scripts\python.exe -m scripts.preview_appearance --label glass
.\.venv\Scripts\python.exe -m scripts.preview_appearance --native --label native-glass
```

This reads local project previews, opens an unloaded editor, and saves PNGs
under `artifacts/appearance-comparison/`. It does not load or modify project
sessions, start acquisition, or change the saved appearance preference.
When the pre-change `before-*.png` captures are present, the glass capture
also creates side-by-side `comparison-browser.png` and
`comparison-editor.png` sheets.

Verification covers both appearances, live switching, preserved browser
state, playback icon changes, and every mapped icon's availability. Native
Windows capture also checks whether DWM accepts the acrylic request; final
desktop appearance still depends on the user's compositor settings.

The GUI regression check runs in a separate process so native crashes and
exceptions in Qt paint callbacks fail the check. It exercises view/menu
popups, repeated theme changes, and clean shutdown. To include the actual
Windows startup path and boot audio, run:

```powershell
.\.venv\Scripts\python.exe -X faulthandler -m scripts.check_gui_launch --native --boot
```

The diagnostic process alone disables Windows' modal crash-report dialog;
it still reports faults and returns a failure code. Normal application
launch behavior is unchanged.
