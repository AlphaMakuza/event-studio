import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from event_studio.recording_import import load_recording
from event_studio.science import load_csv, export_csv


class ImportCacheTests(unittest.TestCase):
    def test_cache_reuses_exact_readonly_arrays_and_invalidates_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'events.csv'
            source.write_text('t,x,y,p\n9007199254740993,0,0,1\n9007199254740994,1,0,-1\n')
            _, first = load_recording(source, root / 'data')
            with patch('event_studio.recording_import.load_csv', side_effect=AssertionError('parsed again')):
                _, second = load_recording(source, root / 'data')
            self.assertTrue(second.metadata['cache_hit'])
            for name in ('t', 'x', 'y', 'p'):
                np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
                self.assertFalse(getattr(second, name).flags.writeable)
            del second
            index = next((root / 'data/import-cache').glob('*.json'))
            cache = root / 'data/import-cache' / json.loads(index.read_text())['arrays'][0]['file']
            contents = bytearray(cache.read_bytes()); contents[-1] ^= 1; cache.write_bytes(contents)
            _, rebuilt = load_recording(source, root / 'data')
            self.assertFalse(rebuilt.metadata['cache_hit'])
            np.testing.assert_array_equal(first.t, rebuilt.t)
            source.write_text('t,x,y,p\n10,0,0,1\n')
            _, changed = load_recording(source, root / 'data')
            self.assertEqual(changed.t.tolist(), [10])

    def test_hdf5_preview_remains_partial_when_reopened_as_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            import h5py
            source = root / 'example.hdf5'
            rows = np.array([(1,0,0,1),(2,1,0,0),(3,0,0,1),(4,1,0,0)],
                            dtype=[('t','<i8'),('x','<i4'),('y','<i4'),('p','i1')])
            with h5py.File(source, 'w') as h:
                h.create_dataset('CD/events', data=rows)
            with patch('event_studio.recording_import.PREVIEW_EVENTS', 3), \
                 patch('event_studio.recording_import.recording_to_csv', wraps=__import__('event_studio.native_import', fromlist=['recording_to_csv']).recording_to_csv) as converter:
                csv_path, preview = load_recording(source, root / 'data', preview=True)
                _, cached = load_recording(source, root / 'data', preview=True)
                self.assertEqual(converter.call_count, 1)
            self.assertEqual(len(preview.t), 3)
            self.assertFalse(preview.metadata['complete'])
            self.assertTrue(cached.metadata['cache_hit'])
            self.assertFalse(load_csv(csv_path).metadata['complete'])
            with self.assertRaisesRegex(ValueError, 'limited preview'):
                export_csv(root / 'export.csv', preview, (1, 2))
            del cached  # Release Windows memory mappings before temp cleanup.

    def test_preview_and_full_cache_entries_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'events.csv'; source.write_text('t,x,y,p\n1,0,0,1\n2,0,0,0\n3,0,0,1\n')
            with patch('event_studio.recording_import.PREVIEW_EVENTS', 2):
                _, preview = load_recording(source, root / 'data', preview=True)
                _, full = load_recording(source, root / 'data')
            self.assertFalse(preview.metadata['complete'])
            self.assertTrue(full.metadata['complete'])
            self.assertEqual(len(full.t), 3)
