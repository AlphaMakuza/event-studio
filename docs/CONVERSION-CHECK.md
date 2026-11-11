# Conversion check — 2026-11-11

The DAT converter now stages files under ASCII UUID filenames in WSL. Some
OpenEB Boost filesystem argument parsers reject whitespace in paths even when
the shell quotes the argument. Windows input/output filenames remain unchanged.
WSL subprocess output is decoded explicitly as UTF-8, including `wslpath` output.
DAT temporary files are cleaned up after failed conversions as well as success.

A local copy of `paper_05P_0_0_2350000_3925000_td.dat`, renamed to
`paper é (1).dat`, passed DAT → H5 → CSV conversion. All 4,829,705 events
matched the existing reference CSV exactly across `t,x,y,p`.

The reported `070617_street4_td_122500000_182500000.h5` is a precomputed tensor:
its only dataset is `data`, shape `(1200, 6, 240, 304)`, dtype `uint8`, with
`events_to_tensor=event_cube` and `delta_t=50000`. It is not an HDF5 event
recording. Original event tuples cannot be recovered losslessly from this tensor.
Use the original DAT or an HDF5 event recording instead. See
https://docs.prophesee.ai/stable/datasets.html for the distinction between
recordings and precomputed datasets. Missing-dataset conversion errors now
explain this distinction while retaining the converter diagnostics.

Four converter regression tests pass. The full test run passed all other
modules except `tests.test_live_camera`, which repeatedly aborted natively in
`test_runtime_view_controls_render_through_worker`, with the main-thread stack
in `theme.py`'s appearance event filter. This remains unresolved; this check
does not establish release readiness or physical camera compatibility.
