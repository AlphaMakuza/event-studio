# Dependency audit — November 10, 2026

This records observed files and primary-source licensing information. The final
bundle must pass its binary allowlist and include the notices and source companion;
this document alone is not a claim that every release requirement is complete.

## Observed development-preview bundle

PySide6, Qt, and Shiboken are version 6.10.1. The earlier preview unintentionally
included `Qt6VirtualKeyboard.dll` and `qtvirtualkeyboardplugin.dll`. Qt Virtual
Keyboard is GPLv3-only for open-source users, so it is excluded from the intended
proprietary release. Qt PDF is available under LGPLv3 (it is not GPL-only), but
its unused `qpdf.dll` image plugin and `Qt6Pdf.dll` add unnecessary PDFium notice
coverage. The release build excludes that path too.

The previous multimedia plugin contained FFmpeg 7.1.2, confirmed by calling
`av_version_info` from the bundled DLL. Its reported license was LGPL 2.1 or
later. Its build configuration used shared libraries and zlib 1.3.1, with
programs, documentation, debug output, LZMA, Vulkan, V4L2 M2M, and truemotion1
decoder disabled. It did not enable GPL or nonfree options. The release build
excludes the unused FFmpeg plugin and its libraries and retains Windows native
multimedia for the startup WAV. Test that playback on a real Windows machine.

The intended native Qt scope is Core, GUI, Widgets, Network, Multimedia,
OpenGL/OpenGLWidgets, SVG, and the required Windows plugins. The binary report
must confirm no Virtual Keyboard, PDF, QML/Quick, FFmpeg, or unused image-format
plugins remain. Mesa's optional `opengl32sw.dll` is omitted from the raster-widget
release build.

## License texts and source companion

Installed PySide6/Shiboken wheel metadata contained only the commercial license
reference text, despite the packages also being available under open-source
licenses. Therefore copying installed metadata alone was insufficient. The full
LGPLv3 and GPLv3 texts are now in `docs/legal`, along with GPLv2 where applicable.

`docs/legal/qt-source-notices` preserves license/copyright/notice files and
`qt_attribution.json` metadata from the exact 6.10.1 source archives. Referenced
license files are also included. The set is intentionally broader than the
shipped components; unrelated source notices do not mean those modules ship.

The separate source companion under `artifacts/corresponding-source` contains
the original Qt Base, SVG, Multimedia, and PySide/Shiboken source archives and a
SHA-256 manifest. Publish that companion beside the binary download and retain
access to the matching version. A generic upstream homepage link is not used
as a substitute for making the corresponding source available. The companion
contains upstream build scripts and instructions; the application's proprietary
source is not included. Preserve users' ability to replace LGPL libraries.

## QtAwesome fonts

QtAwesome 1.4.2 initializes all its bundled font families, even though this app
uses Phosphor icons. Its installed license only covers the MIT Python wrapper.
The release notices therefore retain the following font declarations/texts:

| Font files | Version | License / attribution |
| --- | --- | --- |
| Phosphor | 1.3.0 | MIT; copyright 2020–2021 Phosphor Icons |
| Font Awesome regular/solid/brands | 5.15.4, 6.7.2 | SIL OFL 1.1 for font files; Font Awesome / Fonticons, Inc. |
| Elusive Icons | 2.0.0 | SIL OFL 1.1; Team Redux |
| Material Design Icons | 5.9.55, 6.9.96 | Apache 2.0; Pictogrammers |
| Remix Icon | 2.5.0 | Apache 2.0; Remix Design |
| Microsoft Codicons | 0.0.36 | CC BY 4.0; Microsoft |

Fonts are unmodified. `docs/legal/provenance.json` records source URLs and hashes
of fetched notices. `SIL-OFL-1.1.txt` is the verbatim OFL section extracted from
the included official Font Awesome 6.7.2 license. Elusive's official website had
a TLS hostname error; its original GitHub license template and configuration
are included instead, with the full OFL text separately. Preserve attribution
and note that brand glyphs do not grant trademark rights.

NumPy's bundled OpenBLAS license includes the GCC Runtime Library Exception;
that exception is distinct from shipping a GPL-only Qt module. Its installed
license text and all Python dependency notices must remain in the download.
Python and PyInstaller notices remain included. Microsoft's runtime DLLs are
excluded because redistribution rights have not been established for this
publisher. Users install Microsoft's official Visual C++ v14 x64 prerequisite
separately. The final binary checker rejects bundled MSVCP/VCRUNTIME/CONCRT DLLs.
The NumPy wheel privately names its MSVCP import. The release transformation
retargets import-name storage in two NumPy extensions to the normal installed
`msvcp140.dll`, retaining binary sizes and executable instructions. The generated
RUNTIME-IMPORT-CHANGES.json records original/modified hashes. Packaged CSV and FFT
checks validate both paths. This is a disclosed NumPy binary-import modification,
not an assertion that every bundled binary is unchanged.

Microsoft's redistribution guidance:
https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files

## Primary references

- [Qt 6.10 licensing and GPL-only module list](https://doc.qt.io/qt-6.10/licensing.html)
- [Qt PDF LGPL licensing](https://doc.qt.io/qt-6.10/qtpdf-index.html)
- [Qt LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations)
- [Qt 6.10.1 source archives](https://download.qt.io/archive/qt/6.10/6.10.1/submodules/)
- [PySide6 6.10.1 source archives](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.1-src/)
- [QtAwesome 1.4.2 font declarations](https://github.com/spyder-ide/qtawesome/blob/v1.4.2/README.md#license)
- [Font Awesome 6.7.2 terms](https://github.com/FortAwesome/Font-Awesome/blob/6.7.2/LICENSE.txt)
- [Elusive Icons original license declaration](https://github.com/dovy/elusive-icons#license)

## Portable file import ? 2026-11-11

h5py 3.15.1 and its bundled HDF5/LZF libraries are included for event-file
reading. The build inventory retains h5py's BSD license and the wheel's
HDF5/LZF/other bundled notices. ECF decompression is a bounds-checked Python
adaptation of Prophesee's Apache-2.0 hdf5_ecf decoder; its license is retained
at legal/HDF5-ECF-LICENSE.txt. No SDK, WSL image or OpenEB executable is added.
