"""Portable import, exact event tuples, malformed files, and ECF encodings."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

from event_studio.ecf import decode_ecf
from event_studio.native_import import recording_to_csv
from event_studio.recording_import import load_recording
from event_studio.science import load_csv
from event_studio.filters import CancelledError


def ecf_fixture(mode):
    # Four events: (t,x,y,p) = (100,5,3,0), (100,6,3,1),
    # (115,7,3,0), (116,8,3,1). Golden byte layout from the ECF spec.
    header = struct.pack('<IQ', 16 | mode, 100) + bytes([2, 255, 1, 17])
    if mode == 0:
        return header + struct.pack('<HH', 100, 188) + bytes([1, 129, 1, 129])
    if mode == 1:
        return header + struct.pack('<HHHH', 100, 173, 14, 17)
    return header + struct.pack('<III', 3148301, 3158030, 12305)


class NativeImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def dat(self, name='events.dat', version=2, timestamps=(1, 10), values=None):
        source = self.root / name
        if values is None:
            values = [1 | (2 << 14) | (1 << 28)] * len(timestamps)
        header = f'% Version {version}\n% Width 640\n% Height 480\n'.encode() + bytes([0, 8])
        source.write_bytes(header + b''.join(struct.pack('<II', t, v) for t, v in zip(timestamps, values)))
        return source

    def h5(self, name='events.hdf5', rows=None, **kwargs):
        if rows is None:
            rows = [(2**53 + 1, 3, 4, -1), (2**53 + 2, 5, 6, 1)]
        data = np.array(rows, dtype=[('t', '<u8'), ('x', '<i4'), ('y', '<i4'), ('p', '<i2')])
        source = self.root / name
        with h5py.File(source, 'w') as h:
            h.attrs['geometry'] = '640x480'
            h.create_dataset('CD/events', data=data, **kwargs)
        return source

    def test_dat_opens_without_any_external_process_and_preserves_resolution(self):
        source = self.dat(name='recording é (1).DAT')
        with patch('subprocess.run', side_effect=AssertionError('external process')), patch('subprocess.Popen', side_effect=AssertionError('external process')):
            csv, events = load_recording(source, self.root / 'data')
        self.assertEqual(events.t.tolist(), [1, 10])
        self.assertEqual(events.x.tolist(), [1, 1])
        self.assertEqual(events.y.tolist(), [2, 2])
        self.assertEqual(events.p.tolist(), [1, 1])
        self.assertEqual(events.metadata['resolution'], [640, 480])
        self.assertEqual(events.metadata['resolution_origin'], 'DAT header')
        self.assertTrue(events.metadata['complete'])
        self.assertFalse(events.t.flags.writeable)
        self.assertEqual(load_csv(csv).metadata['resolution'], [640, 480])

    def test_dat_rollover_across_blocks_and_version_one(self):
        source = self.dat(timestamps=(2**32-2, 2**32-1, 0, 1))
        with patch('event_studio.native_import.BLOCK_EVENTS', 2):
            csv = recording_to_csv(source, self.root / 'wrap.csv')
        self.assertEqual(load_csv(csv).t.tolist(), [2**32-2, 2**32-1, 2**32, 2**32+1])
        source = self.dat(name='legacy.dat', version=1, values=[5 | (6 << 9) | (1 << 17)] * 2)
        events = load_csv(recording_to_csv(source, self.root / 'legacy.csv'))
        self.assertEqual(events.x.tolist(), [5, 5])
        self.assertEqual(events.y.tolist(), [6, 6])
        self.assertEqual(events.p.tolist(), [1, 1])

    def test_hdf5_extensions_gzip_and_large_integer_timestamps_without_wsl(self):
        for ext in ('h5', 'hdf5'):
            source = self.h5(name='sample.' + ext, compression='gzip')
            with patch('subprocess.run', side_effect=AssertionError('external process')):
                csv, events = load_recording(source, self.root / ext)
                _, cached = load_recording(source, self.root / ext)
            self.assertTrue(cached.metadata['cache_hit'])
            self.assertEqual(events.t.tolist(), [2**53+1, 2**53+2])
            self.assertEqual(load_csv(csv).t.tolist(), events.t.tolist())
            self.assertEqual(events.p.tolist(), [-1, 1])
            del cached

    def test_three_ecf_encodings_and_hdf5_without_filter_plugin(self):
        for mode in (0, 1, 2):
            raw = ecf_fixture(mode)
            columns = decode_ecf(raw, 4)
            self.assertEqual(columns[0].tolist(), [100, 100, 115, 116])
            self.assertEqual(columns[1].tolist(), [5, 6, 7, 8])
            self.assertEqual(columns[2].tolist(), [3, 3, 3, 3])
            self.assertEqual(columns[3].tolist(), [0, 1, 0, 1])
            source = self.root / f'ecf-{mode}.h5'
            with h5py.File(source, 'w') as h:
                dtype = np.dtype({'names':['x','y','p','t'], 'formats':['<u2','<u2','<i2','<i8'], 'offsets':[0,2,4,8], 'itemsize':16})
                dataset = h.create_dataset('CD/events', (4,), dtype=dtype, chunks=(4,), compression=36559, allow_unknown_filter=True)
                dataset.id.write_direct_chunk((0,), raw, filter_mask=0)
            csv = recording_to_csv(source, self.root / f'ecf-{mode}.csv', max_events=3)
            events = load_csv(csv)
            self.assertEqual(events.x.tolist(), [5, 6, 7])
            self.assertFalse(events.metadata['complete'])

    def test_preview_full_reload_preserves_limits_and_sensor_metadata(self):
        source = self.dat(timestamps=(1, 2, 3, 4))
        with patch('event_studio.recording_import.PREVIEW_EVENTS', 2):
            csv, preview = load_recording(source, self.root / 'data', preview=True)
            _, full = load_recording(source, self.root / 'data')
        self.assertFalse(preview.metadata['complete'])
        self.assertEqual(preview.metadata['input_sha256'], full.metadata['input_sha256'])
        self.assertTrue(full.metadata['complete'])
        self.assertEqual(full.t.tolist(), [1,2,3,4])
        self.assertFalse(load_csv(csv).metadata['complete'])
        self.assertEqual(load_csv(csv).metadata['resolution'], [640,480])

    def test_malformed_inputs_and_cancel_leave_no_partial_csv(self):
        source = self.dat()
        source.write_bytes(source.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'Truncated DAT'):
            recording_to_csv(source, self.root / 'bad.csv')
        self.assertFalse((self.root / 'bad.csv').exists())
        source = self.dat(timestamps=(10, 9))
        with self.assertRaisesRegex(ValueError, 'nondecreasing'):
            recording_to_csv(source, self.root / 'bad.csv')
        with self.assertRaises(CancelledError):
            recording_to_csv(source, self.root / 'cancel.csv', cancel=lambda: True)
        self.assertFalse((self.root / 'cancel.csv').exists())
        for raw in (b'', struct.pack('<I', 65536 << 2), ecf_fixture(1)[:-1], ecf_fixture(1)+b'x'):
            with self.assertRaises(ValueError):
                decode_ecf(raw, 4)

    def test_precomputed_tensor_and_float_event_fields_are_rejected(self):
        source = self.root / 'tensor.h5'
        with h5py.File(source,'w') as h:
            h.create_dataset('data', shape=(2,6,20,20), dtype='u1')
        with self.assertRaisesRegex(ValueError, 'Precomputed event cubes'):
            recording_to_csv(source, self.root / 'tensor.csv')
        with h5py.File(source,'w') as h:
            h.create_dataset('CD/events', shape=(2,), dtype=[(key,'f8') for key in 'txyp'])
        with self.assertRaisesRegex(ValueError, 'must contain integers'):
            recording_to_csv(source, self.root / 'float.csv')
