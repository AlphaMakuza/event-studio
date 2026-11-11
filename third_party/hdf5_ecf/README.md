# ECF decoder reference

Upstream: https://github.com/prophesee-ai/hdf5_ecf

The original Apache-2.0 `ecf_codec.cpp`, `ecf_codec.h` and LICENSE were retrieved
2026-11-11 as reference for `event_studio/ecf.py`. The app ships a Python
adaptation of the decoder, with bounds checks and NumPy unpacking, rather than
a compiled SDK or HDF5 filter plugin. The original copyright and license are
retained. The release includes `docs/legal/HDF5-ECF-LICENSE.txt`.
