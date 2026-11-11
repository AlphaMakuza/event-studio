"""Portable DAT/HDF5 event recording import. No SDK, WSL or subprocesses."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import numpy as np

from .ecf import decode_ecf
from .filters import CancelledError

BLOCK_EVENTS = 131072


def _check(cancel):
    if cancel and cancel():
        raise CancelledError('Recording import cancelled.')


def _dat_blocks(path, metadata, limit, cancel):
    with path.open('rb') as stream:
        header, header_bytes = {}, 0
        while True:
            start = stream.tell()
            prefix = stream.read(2)
            stream.seek(start)
            if prefix != b'% ':
                break
            line = stream.readline(4097)
            header_bytes += len(line)
            if len(line) > 4096 or header_bytes > 65536:
                raise ValueError('DAT header exceeds the supported size.')
            match = re.match(rb'%\s+(Version|Width|Height)\s+(\d+)\s*$', line, re.I)
            if match:
                header[match[1].decode().lower()] = int(match[2])
        version = header.get('version', 1)
        if version not in (1, 2):
            raise ValueError(f'Unsupported DAT version {version}; supported versions are 1 and 2.')
        if header_bytes:
            descriptor = stream.read(2)
            if len(descriptor) != 2 or descriptor[0] not in (0, 12) or descriptor[1] != 8:
                raise ValueError('Unsupported DAT event type/size. Select an 8-byte CD event recording.')
        size = path.stat().st_size - stream.tell()
        if size % 8:
            raise ValueError('Truncated DAT recording: incomplete 8-byte event.')
        total = size // 8
        metadata.update(total_events=total, dat_version=version)
        if 'width' in header and 'height' in header:
            metadata['sensor_resolution'] = dict(width=header['width'], height=header['height'], origin='DAT header')
        count = total if limit is None else min(limit, total)
        previous, offset = None, 0
        for start in range(0, count, BLOCK_EVENTS):
            _check(cancel)
            block = np.fromfile(stream, dtype=[('t', '<u4'), ('v', '<u4')], count=min(BLOCK_EVENTS, count - start))
            if len(block) != min(BLOCK_EVENTS, count - start):
                raise ValueError('DAT recording changed or was truncated during import.')
            raw_t = block['t'].astype(np.int64)
            differences = np.diff(raw_t, prepend=raw_t[0] if previous is None else previous)
            if np.any((differences < 0) & (differences > -(1 << 31))):
                raise ValueError('DAT timestamps are not nondecreasing; source order was not changed.')
            wraps = np.cumsum(differences < 0, dtype=np.int64)
            t = raw_t + offset + wraps * (1 << 32)
            offset += int(wraps[-1]) * (1 << 32)
            previous = int(raw_t[-1])
            values = block['v']
            if version == 1:
                x, y, p = values & 511, (values >> 9) & 255, (values >> 17) & 1
            else:
                x, y, p = values & 16383, (values >> 14) & 16383, values >> 28
            yield t, x, y, p


def _hdf5_blocks(path, metadata, limit, cancel):
    import h5py
    with h5py.File(path, 'r') as source:
        dataset = source.get('CD/events')
        if dataset is None:
            dataset = source.get('events')
        if not isinstance(dataset, h5py.Dataset) or dataset.ndim != 1 or not dataset.dtype.names or not set('txyp').issubset(dataset.dtype.names):
            raise ValueError('This HDF5 file is not a supported event recording. Expected a one-dimensional '
                             'CD/events (or events) dataset with integer t,x,y,p fields. Precomputed event cubes, '
                             'histograms and time surfaces do not contain original event tuples.')
        if any(dataset.dtype.fields[name][0].kind not in 'iu' for name in 'txyp'):
            raise ValueError('HDF5 t,x,y,p fields must contain integers; floating-point event values are not converted.')
        if any(dataset.dtype.fields[name][0].shape for name in 'txyp'):
            raise ValueError('HDF5 event fields must be scalar integers.')
        total = len(dataset)
        metadata['total_events'] = total
        geometry = source.attrs.get('geometry', '')
        if isinstance(geometry, bytes):
            geometry = geometry.decode('utf-8')
        match = re.fullmatch(r'(\d+)x(\d+)', str(geometry))
        if match:
            metadata['sensor_resolution'] = dict(width=int(match[1]), height=int(match[2]), origin='HDF5 geometry')
        # A time-unit declaration must agree with the supported event-file spec.
        units = dataset.attrs.get('timestamp_unit', source.attrs.get('timestamp_unit', 'us'))
        if isinstance(units, bytes):
            units = units.decode('utf-8')
        if str(units) not in ('us', 'µs', 'microseconds'):
            raise ValueError(f'Unsupported HDF5 timestamp unit {units!r}; expected integer microseconds.')
        properties = dataset.id.get_create_plist()
        filters = [properties.get_filter(i)[0] for i in range(properties.get_nfilters())]
        ecf = 36559 in filters
        if ecf and (filters != [36559] or dataset.chunks is None or dataset.chunks[0] > 65535):
            raise ValueError('Unsupported ECF filter pipeline or chunk size in this HDF5 recording.')
        if not ecf:
            unavailable = [code for code in filters if not h5py.h5z.filter_avail(code)]
            if unavailable:
                raise ValueError(f'Unsupported HDF5 compression filter(s): {unavailable}. '
                                 'This app includes standard HDF5 compression and Prophesee ECF; '
                                 'obtain an event recording using one of those formats.')
        count = total if limit is None else min(total, limit)
        step = dataset.chunks[0] if ecf else BLOCK_EVENTS
        for start in range(0, count, step):
            _check(cancel)
            end = min(start + step, count)
            if ecf:
                mask, raw = dataset.id.read_direct_chunk((start,))
                if mask & 1:
                    block = np.frombuffer(raw, dtype=dataset.dtype)
                    if len(block) < end - start:
                        raise ValueError('Truncated uncompressed HDF5 chunk.')
                    yield tuple(block[name][:end - start] for name in 'txyp')
                else:
                    columns = decode_ecf(raw, min(step, total - start))
                    yield tuple(column[:end - start] for column in columns)
            else:
                block = dataset[start:end]
                yield tuple(block[name] for name in 'txyp')


def recording_to_csv(path, output, *, max_events=None, cancel=None, progress=None):
    """Write a validated, lossless CSV plus provenance/resolution metadata."""
    path, output = Path(path).resolve(), Path(output).resolve()
    if output.exists() or output.with_suffix('.json').exists():
        raise FileExistsError(f'Import output already exists: {output}')
    if max_events is not None and (type(max_events) is not int or max_events < 1):
        raise ValueError('Preview event limit must be a positive integer.')
    if path.suffix.lower() not in ('.dat', '.h5', '.hdf5'):
        raise ValueError('Expected a DAT or HDF5 event recording.')
    _check(cancel)
    metadata = {}
    blocks = _dat_blocks if path.suffix.lower() == '.dat' else _hdf5_blocks
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='native-import-', suffix='.csv', dir=output.parent)
    temporary = Path(name)
    loaded, last = 0, None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write('t,x,y,p\n')
            for columns in blocks(path, metadata, max_events, cancel):
                _check(cancel)
                t, x, y, p = columns
                if np.any(t < 0) or np.any(t >= np.iinfo(np.int64).max):
                    raise ValueError('Timestamp outside supported nonnegative int64 range.')
                if np.any(x < 0) or np.any(y < 0) or np.any(x >= 32768) or np.any(y >= 32768):
                    raise ValueError('Pixel coordinates must be between 0 and 32767.')
                if np.any(p < -1) or np.any(p > 1):
                    raise ValueError('Polarity must be -1, 0 or 1.')
                if (last is not None and int(t[0]) < last) or np.any(t[1:] < t[:-1]):
                    raise ValueError('Timestamps must be nondecreasing; source order was not changed.')
                last = int(t[-1])
                resolution = metadata.get('sensor_resolution')
                if resolution and (not 0 < resolution['width'] <= 32768 or not 0 < resolution['height'] <= 32768
                                   or resolution['width'] * resolution['height'] > 16_777_216
                                   or np.any(x >= resolution['width']) or np.any(y >= resolution['height'])):
                    raise ValueError('Sensor metadata conflicts with event coordinates or exceeds supported dimensions.')
                # uint64 timestamps combined with signed fields otherwise promote
                # to float64, losing integers above 2**53.
                np.savetxt(stream, np.column_stack([column.astype(np.int64) for column in columns]), fmt='%d', delimiter=',')
                loaded += len(t)
                if progress:
                    progress(min(85, int(85 * loaded / max(1, metadata['total_events']))),
                             f'Reading {path.suffix.upper()[1:]} recording: {loaded:,} events')
        if not loaded:
            raise ValueError('Recording contains no events.')
        _check(cancel)
        digest = hashlib.sha256()
        with temporary.open('rb') as stream:
            for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                _check(cancel)
                digest.update(data)
        metadata.update(csv_sha256=digest.hexdigest(), partial_recording=loaded < metadata['total_events'],
                        original_path=str(path), import_method='native-windows-events-v1')
        # Destination is a fresh per-import directory, never a source recording.
        temporary.replace(output)
        try:
            output.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return output
    finally:
        temporary.unlink(missing_ok=True)
