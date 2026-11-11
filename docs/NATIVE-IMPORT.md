# Portable recording import ? 2026-11-11

The Windows app now reads supported CSV, DAT, H5 and HDF5 recordings without
WSL, OpenEB, a camera SDK or an external converter executable. h5py/HDF5 is
bundled; Prophesee ECF decompression runs in the application with bounded reads.
Live cameras still require their native SDK and driver. The normal Windows x64
system requirements, including the Microsoft C++ runtime, still apply.

Supported binary recordings:

- Prophesee DAT v1/v2, 8-byte CD events of type 0 or 12; legacy headerless v1.
  Sensor dimensions come from header metadata when present. Timestamp rollover
  across uint32 boundaries is expanded to int64 without rebasing or sorting.
- HDF5 integer microsecond event tuples in a 1-D `CD/events` or `events`
  compound dataset with scalar `t,x,y,p` fields. Both extensions use the same
  reader. Bundled HDF5 compression and Prophesee ECF are supported. Geometry
  metadata is retained; otherwise sensor dimensions are explicitly inferred.
- Precomputed tensors/event cubes/histograms/time surfaces are rejected.
  Unknown compression/layouts and noninteger or unsorted data are rejected,
  rather than guessed or silently changed. Only CD tuples are imported;
  external trigger datasets are not part of the app's event representation.

Imports run in the background, report progress and support cancellation.
Large recordings offer a prefix preview with full-load later. Converted CSVs
retain original integer values and resolution metadata; partial CSVs stay
marked incomplete when reopened. Cache format 2 avoids reusing old converter
results. Recordings still reside in RAM; capacity depends on available memory.

Verification:

- `tests.test_native_import` covers DAT versions, rollover across blocks,
  Unicode/spaced paths, exact uint64 timestamps above 2**53, negative polarity,
  gzip HDF5, all three ECF packing layouts, preview/full loading, unsupported
  tensors/float fields, malformed chunks and cancellation.
- Real DAT and ECF-HDF5 versions of
  `paper_05P_0_0_2350000_3925000_td` each produced all 4,829,705 events exactly
  equal to the existing OpenEB CSV across `t,x,y,p`, with subprocess execution
  blocked. Evidence: `artifacts/native-import-acceptance/full/report.json`.
- The executable smoke check generates DAT, gzip HDF5 and ECF H5 samples and
  loads them with every external process call blocked and external HDF5 plugin
  lookup directed to an absent directory. This checks bundled dependencies.
- Repeating the final ZIP on a genuinely clean Windows PC remains a separate
  manual acceptance check; development-machine packaging checks do not prove
  compatibility with every Windows installation or every HDF5 layout.

References:
https://docs.prophesee.ai/stable/data/file_formats/dat.html
https://docs.prophesee.ai/stable/data/file_formats/hdf5.html
https://github.com/prophesee-ai/hdf5_ecf
