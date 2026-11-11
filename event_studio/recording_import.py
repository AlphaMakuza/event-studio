"""Bounded previews and checksum-validated local event-array caches."""
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import uuid4

import numpy as np

from .native_import import recording_to_csv
from .filters import CancelledError
from .science import load_csv
from .viewer import EventBatch

PREVIEW_EVENTS = 2_000_000
CACHE_VERSION = 2


def _check(cancel):
    if cancel and cancel():
        raise CancelledError("Recording import cancelled.")


def _hash(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            _check(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def load_recording(path, data_dir, *, preview=False, cancel=None, progress=None):
    path, data_dir = Path(path).resolve(), Path(data_dir).resolve()
    if progress:
        progress(0, "Checking recording and local cache...")
    original_hash = _hash(path, cancel)
    sidecar = path.with_suffix('.json')
    sidecar_hash = _hash(sidecar, cancel) if path.suffix.lower() == '.csv' and sidecar.exists() else None
    limit = PREVIEW_EVENTS if preview else None
    key = hashlib.sha256(json.dumps([CACHE_VERSION, original_hash, sidecar_hash, limit]).encode()).hexdigest()
    root = data_dir / 'import-cache'
    root.mkdir(parents=True, exist_ok=True)
    index = root / (key + '.json')
    try:
        record = json.loads(index.read_text(encoding='utf-8'))
        csv_path = path if path.suffix.lower() == '.csv' else Path(record['csv_path'])
        if csv_path == path:
            if record['metadata']['sha256'] != original_hash:
                raise ValueError('Source checksum changed')
        elif _hash(csv_path, cancel) != record['metadata']['sha256']:
            raise ValueError('Converted recording changed')
        arrays = []
        for entry, dtype in zip(record['arrays'], ('int64', 'int32', 'int32', 'int8')):
            cached = (root / entry['file']).resolve()
            if not cached.is_relative_to(root.resolve()) or _hash(cached, cancel) != entry['sha256']:
                raise ValueError('Cache checksum mismatch')
            array = np.load(cached, mmap_mode='r', allow_pickle=False)
            if array.ndim != 1 or array.dtype != np.dtype(dtype) or len(array) != record['metadata']['loaded_events']:
                raise ValueError('Cache shape mismatch')
            arrays.append(array)
        if len(arrays) != 4:
            raise ValueError('Incomplete cache')
        metadata = {**record['metadata'], 'cache_hit': True, 'csv_path': str(csv_path)}
        if path.suffix.lower() != '.csv' or not (metadata.get('preview') and sidecar_hash):
            metadata['input_path'] = str(path)
        _check(cancel)
        if progress:
            progress(100, f"Opened cached recording: {len(arrays[0]):,} events")
        return csv_path, EventBatch(*arrays, metadata)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # A missing, changed or incomplete cache is rebuilt from the source.

    csv_path = path
    is_binary = path.suffix.lower() in ('.dat', '.h5', '.hdf5')
    if is_binary:
        csv_path = data_dir / 'converted' / uuid4().hex[:12] / (path.stem + '.csv')
        csv_path = recording_to_csv(path, csv_path, max_events=limit, cancel=cancel, progress=progress)
    events = load_csv(csv_path, max_events=limit, cancel=cancel, progress=progress)
    events.metadata.setdefault('input_path', str(path))
    events.metadata.setdefault('input_sha256', original_hash)
    events.metadata['cache_hit'] = False
    if is_binary:
        events.metadata.update(original_path=str(path), original_sha256=original_hash,
                               input_path=str(path), input_sha256=original_hash,
                               conversion='Native DAT/HDF5 event reader')
        if not events.metadata['complete']:
            # Preserve partial status if the converted CSV is opened or saved
            # separately later; it must never masquerade as a full recording.
            csv_path.with_suffix('.json').write_text(json.dumps({
                'csv_sha256': events.metadata['sha256'],
                'partial_recording': True,
                'sensor_resolution': {'width': events.metadata['resolution'][0],
                                      'height': events.metadata['resolution'][1],
                                      'origin': events.metadata['resolution_origin']},
                'original_path': str(path), 'original_sha256': original_hash,
            }), encoding='utf-8')
    _check(cancel)
    if progress:
        progress(96, 'Saving local cache for faster reopening...')
    # Generation folders keep previous memory-mapped arrays valid if this cache
    # is rebuilt while another window still uses them. CSVs stay in converted/.
    entries = []
    try:
        generation = Path(tempfile.mkdtemp(prefix=key[:12] + '-', dir=root))
        for name, array in zip(('t', 'x', 'y', 'p'), (events.t, events.x, events.y, events.p)):
            _check(cancel)
            destination = generation / (name + '.npy')
            np.save(destination, array, allow_pickle=False)
            entries.append({'file': destination.relative_to(root).as_posix(), 'sha256': _hash(destination, cancel)})
        record = {'csv_path': str(csv_path), 'metadata': events.metadata, 'arrays': entries}
        temporary = generation / 'index.json'
        temporary.write_text(json.dumps(record), encoding='utf-8')
        temporary.replace(index)
        if is_binary and events.metadata['complete']:
            # Saved projects reopen the converted CSV rather than the HDF5.
            csv_sidecar = csv_path.with_suffix('.json')
            alias = hashlib.sha256(json.dumps([CACHE_VERSION, events.metadata['sha256'],
                                               _hash(csv_sidecar, cancel) if csv_sidecar.exists() else None, None]).encode()).hexdigest()
            temporary.write_text(json.dumps(record), encoding='utf-8')
            temporary.replace(root / (alias + '.json'))
    except OSError:
        pass  # A full cache disk must not prevent opening a valid recording.
    return csv_path, events
