# Third-party software

Event-Based Studio is proprietary software owned by Alpha Makuza. Third-party
components retain their own copyrights and licenses. The application's
proprietary restrictions do not replace or narrow those licenses.

The bundled graphical interface uses PySide6 and Qt under their applicable
open-source licenses. LGPL-covered components may be modified, replaced, and
redistributed under those licenses. The application license permits the
reverse engineering and modification needed to exercise those rights.

The folder bundle keeps shared libraries separate under `_internal`, including
the PySide6 libraries. Keep a backup before replacing libraries and use builds
compatible with the bundled Python, Qt, architecture, and dependent libraries.
No application-level signature or checksum check prevents library replacement.
This does not promise compatibility with arbitrary library versions.

See `_internal/release-docs/third-party/inventory.json` and the adjacent license
texts for the installed dependency inventory. The inventory includes build-tool
dependencies for transparency; not every listed package is shipped as runtime code.
QtAwesome also contains separately licensed fonts; its MIT license does not
replace font licenses. Python and PyInstaller notices are retained as well.
The release candidate excludes unused FFmpeg, Qt PDF, Virtual Keyboard,
QML/Quick, and Mesa software-OpenGL libraries. Microsoft's C++ runtime DLLs are
also excluded: install the official Microsoft x64 redistributable separately.
This avoids assuming publisher rights to redistribute Microsoft's binaries.
NumPy's two extension modules that reference a private, renamed MSVC DLL have
their import-name strings retargeted to the standard installed `msvcp140.dll`.
No executable instructions are rewritten. Original/modified hashes and names
are recorded in `RUNTIME-IMPORT-CHANGES.json`; the build transformation is in
`scripts/runtime_imports.py`. NumPy's BSD terms and bundled dependency notices
remain included. The installed Microsoft runtime must be current and compatible.

Full Qt LGPL/GPL texts, Qt source notices/attributions, and the font notices are
under `_internal/release-docs/legal`. See the bundled DEPENDENCY-AUDIT.md for
the component/version record. The separate matching source companion contains
Qt Base, SVG, Multimedia, PySide6, and Shiboken 6.10.1 source archives and build
instructions. Download it beside the matching binary. It contains no proprietary
application source. Public source availability must be maintained for recipients;
generic upstream links alone are not a substitute for that distribution.

References:

- HDF5 import uses h5py and its bundled HDF5 library; their license texts are
  listed in the bundled third-party inventory and retained in the release notices.
- ECF decoding in `event_studio/ecf.py` is a Python adaptation of Prophesee's
  Apache-2.0 hdf5_ecf decoder, copyright Prophesee S.A. The adaptation adds
  bounds/run validation and NumPy unpacking. Its license is included at
  `legal/HDF5-ECF-LICENSE.txt`. Upstream: https://github.com/prophesee-ai/hdf5_ecf

- https://www.qt.io/development/open-source-lgpl-obligations
- https://doc.qt.io/qt-6.10/licensing.html
- https://pyinstaller.org/en/stable/license.html
