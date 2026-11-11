"""Converter compatibility with filenames rejected by Boost path parsing."""
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from event_studio.convert import convert_dat_to_h5_windows, h5_to_csv_windows, _wslpath, _run_wsl, _find_openeb_bin


class ConversionTests(unittest.TestCase):
    def test_wsl_paths_are_decoded_as_utf8(self):
        with patch('event_studio.convert.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '/mnt/c/recording é (1).dat\n'.encode('utf-8')
            run.return_value.stderr = b''
            self.assertEqual(_wslpath(Path('recording é (1).dat')), '/mnt/c/recording é (1).dat')

    def test_utf16_wsl_startup_error_is_readable(self):
        from subprocess import CompletedProcess
        message = 'WSL has no installed distributions.\r\n'
        with patch('event_studio.convert.subprocess.run', return_value=CompletedProcess([], 1, b'', message.encode('utf-16-le'))):
            with self.assertRaisesRegex(RuntimeError, 'WSL has no installed distributions') as error:
                _run_wsl('printf EBS_WSL_READY')
            self.assertNotIn('\x00', str(error.exception))

    def test_missing_wsl_reports_required_setup_and_csv_alternative(self):
        with patch('event_studio.convert._run_wsl', side_effect=FileNotFoundError('wsl.exe')):
            with self.assertRaisesRegex(RuntimeError, 'WSL could not start') as error:
                _find_openeb_bin()
            self.assertIn('CSV recordings open directly', str(error.exception))

    def test_working_wsl_without_openeb_reports_missing_converters(self):
        from subprocess import CompletedProcess
        def run(command):
            if command.startswith('test '):
                raise RuntimeError('not found')
            return CompletedProcess([], 0, '', '')
        with patch('event_studio.convert._run_wsl', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, 'OpenEB recording converters were not found'):
                _find_openeb_bin()

    def test_csv_opens_even_when_wsl_is_unavailable(self):
        from event_studio.recording_import import load_recording
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'sample.csv'
            source.write_text('t,x,y,p\n0,0,0,1\n1000,1,1,0\n', encoding='utf-8')
            with patch('event_studio.convert.subprocess.run', side_effect=FileNotFoundError('wsl.exe')) as run:
                _, events = load_recording(source, Path(folder) / 'data')
            self.assertEqual(events.t.tolist(), [0, 1000])
            run.assert_not_called()

    def test_dat_uses_simple_staging_names_and_preserves_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder).resolve() / 'recording \u00e9 (1).dat'
            source.write_bytes(b'original recording')
            target = Path(folder).resolve() / 'output \u00e9 (1).h5'
            with patch('event_studio.convert._find_openeb_bin', return_value='/tools'), \
                 patch('event_studio.convert._wsl_stage_in_from_windows') as stage_in, \
                 patch('event_studio.convert._wsl_stage_out_to_windows') as stage_out, \
                 patch('event_studio.convert._run_wsl') as run:
                self.assertEqual(convert_dat_to_h5_windows(source, target), target)
                command = shlex.split(run.call_args_list[0].args[0])
                self.assertTrue(command[2].endswith('.dat'))
                self.assertTrue(command[4].endswith('.h5'))
                self.assertNotIn(' ', command[2])
                self.assertNotIn('(1)', command[2])
                self.assertEqual(stage_in.call_args.args[0], source)
                self.assertEqual(stage_out.call_args.args[1], target)
                self.assertTrue(run.call_args.args[0].startswith('rm -f --'))
            self.assertEqual(source.read_bytes(), b'original recording')

    def test_failed_dat_conversion_cleans_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder).resolve() / 'recording.dat'
            source.write_bytes(b'data')
            with patch('event_studio.convert._find_openeb_bin', return_value='/tools'), \
                 patch('event_studio.convert._wsl_stage_in_from_windows'), \
                 patch('event_studio.convert._run_wsl', side_effect=[RuntimeError('failed'), None]) as run:
                with self.assertRaisesRegex(RuntimeError, 'failed'):
                    convert_dat_to_h5_windows(source)
                self.assertTrue(run.call_args.args[0].startswith('rm -f --'))

    def test_missing_hdf5_dataset_explains_compatibility_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder).resolve() / 'recording (1).h5'
            source.write_bytes(b'original')
            with patch('event_studio.convert._find_openeb_bin', return_value='/tools'), \
                 patch('event_studio.convert._wsl_stage_in_from_windows'), \
                 patch('event_studio.convert._run_wsl', side_effect=[RuntimeError('H5Dopen2: Object not found'), None]) as run:
                with self.assertRaisesRegex(RuntimeError, 'missing datasets'):
                    h5_to_csv_windows(source, Path(folder).resolve() / 'out.csv')
                self.assertTrue(run.call_args.args[0].startswith('rm -f --'))
            self.assertEqual(source.read_bytes(), b'original')

