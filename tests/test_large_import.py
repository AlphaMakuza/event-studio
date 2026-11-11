import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from event_studio.filters import CancelledError
from event_studio.science import load_csv
from event_studio.convert import _run_wsl


class LargeImportTests(unittest.TestCase):
    def test_large_numeric_and_quoted_csv_preserve_exact_events(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.csv"
            # Cross a block boundary, using timestamps beyond float64 precision.
            count, base = 131075, 2**53 + 1
            for quote in (csv.QUOTE_MINIMAL, csv.QUOTE_ALL):
                with path.open('w', newline='') as stream:
                    writer = csv.writer(stream, quoting=quote)
                    writer.writerow(['p', 't', 'y', 'x'])
                    writer.writerows((i % 3 - 1, base + i, i % 240, i % 304) for i in range(count))
                updates = []
                batch = load_csv(path, progress=lambda value, message: updates.append((value, message)))
                np.testing.assert_array_equal(batch.t, base + np.arange(count, dtype=np.int64))
                np.testing.assert_array_equal(batch.x, np.arange(count) % 304)
                np.testing.assert_array_equal(batch.p, np.arange(count) % 3 - 1)
                self.assertEqual((batch.t.dtype, batch.x.dtype, batch.y.dtype, batch.p.dtype),
                                 (np.int64, np.int32, np.int32, np.int8))
                self.assertTrue(batch.metadata['complete'])
                self.assertEqual(updates[-1][0], 100)

    def test_rejects_invalid_data_and_disorder_across_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.csv"
            for record in ('1.5,0,0,1', '9223372036854775807,0,0,1',
                           '18446744073709551616,0,0,1', '1,32768,0,1', '1,0,0,2'):
                path.write_text('t,x,y,p\n' + record + '\n')
                with self.assertRaises(ValueError):
                    load_csv(path)
            path.write_text('t,x,y,p\n' + '2,0,0,1\n' * 131072 + '1,0,0,1\n')
            with self.assertRaisesRegex(ValueError, 'nondecreasing'):
                load_csv(path)

    def test_cancel_does_not_return_partial_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.csv'
            path.write_text('t,x,y,p\n1,0,0,1\n')
            with self.assertRaises(CancelledError):
                load_csv(path, cancel=lambda: True)

    def test_cancel_stops_only_its_converter(self):
        with patch('event_studio.convert.subprocess.Popen') as popen, \
             patch('event_studio.convert.subprocess.run') as run:
            run.return_value.returncode = 0
            with self.assertRaises(CancelledError):
                _run_wsl('/bin/sleep 60', cancel=iter([False, True]).__next__)
            wrapped = popen.call_args.args[0][-1]
            self.assertIn('exec /bin/sleep 60', wrapped)
            self.assertIn('kill -TERM', run.call_args_list[0].args[0][-1])
            popen.return_value.communicate.assert_called_once_with(timeout=5)
