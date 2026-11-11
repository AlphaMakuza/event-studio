from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from event_studio.app import MainWindow

class Hdf5ImportTests(unittest.TestCase):
    def test_unified_picker_accepts_small_dat_without_converter_dialog(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'recording (1).DAT'
            source.write_bytes(b'fixture')
            owner = SimpleNamespace(data_dir=Path(folder), _open_recording_path=Mock())
            with patch('event_studio.app.QFileDialog.getOpenFileName', return_value=(str(source), '')) as picker:
                MainWindow._open_recording(owner)
            picker.assert_called_once()
            self.assertIn('*.dat', picker.call_args.args[3])
            owner._open_recording_path.assert_called_once_with(str(source), preview=False)

    def test_both_hdf5_extensions_use_the_import_service(self):
        for extension in ('.h5', '.hdf5', '.HDF5'):
            with self.subTest(extension=extension):
                original=Path('driving_sample'+extension)
                events=SimpleNamespace(metadata={})
                owner=SimpleNamespace(data_dir=Path('data'),_load_csv_into_app=Mock())
                cancel,progress=Mock(return_value=False),Mock()
                owner._run_task=lambda load,complete,message,cooperative=False:complete(load(cancel,progress))
                with patch('event_studio.recording_import.load_recording',return_value=(Path('converted.csv'),events)) as load:
                    MainWindow._open_recording_path(owner,original,preview=True)
                load.assert_called_once_with(original,owner.data_dir,preview=True,cancel=cancel,progress=progress)
                owner._load_csv_into_app.assert_called_once_with(Path('converted.csv'),original.stem,prepared_events=events)
