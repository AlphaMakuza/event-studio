import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from event_studio.viewer import EventBatch,load_events_from_csv
from event_studio.roi_label import Roi
from event_studio.activity import activity_series,detect_bursts,frequency_spectrum
from event_studio.filters import apply_filters,CancelledError
from event_studio.motion import estimate_translation,track_motion
from event_studio.science import export_csv
from event_studio.app import MainWindow


def events(t,x=None,y=None,p=None,hw=(32,32)):
    n=len(t)
    batch=EventBatch(np.array(t,dtype=np.int64),np.array(x if x is not None else [0]*n,dtype=np.int32),
                     np.array(y if y is not None else [0]*n,dtype=np.int32),np.array(p if p is not None else [1]*n,dtype=np.int8),
                     {'sorted':True,'complete':True,'resolution':[hw[1],hw[0]],'resolution_origin':'fixture','sha256':'fixture'})
    for array in (batch.t,batch.x,batch.y,batch.p): array.flags.writeable=False
    return batch


class V2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def test_activity_exact_boundaries_and_partial_bin(self):
        offset=9007199254740993
        source=events([offset,offset+2,offset+3,offset+6,offset+7],p=[1,0,1,-1,1])
        series=activity_series(source,offset,offset+7,3)
        self.assertEqual(series.total.tolist(),[2,1,1]);self.assertEqual(series.negative.tolist(),[1,0,1])
        self.assertEqual(series.rate.tolist(),[2000/3,1000/3,1000]);self.assertEqual(series.cumulative[-1],4)
        self.assertEqual(series.end_us[-1],offset+7)

    def test_empty_bins_and_roi(self):
        series=activity_series(events([0,8],x=[0,4]),0,10,2,Roi(0,0,2,2))
        self.assertEqual(series.total.tolist(),[1,0,0,0,0])
        self.assertEqual(sum(series.positive+series.negative),sum(series.total))

    def test_burst_boundaries_strict_threshold_and_no_gap_interpolation(self):
        series=activity_series(events([0,1,2,3,6,7]),0,9,3)
        bursts=detect_bursts(series,500)
        self.assertEqual([(b['t0'],b['t1']) for b in bursts],[(0,3),(6,9)])
        self.assertEqual(detect_bursts(series,2000),[])
        self.assertEqual(detect_bursts(series,500,4),[])
        empty=activity_series(events([]),0,10,2)
        self.assertEqual(detect_bursts(empty,0),[])

    def test_known_activity_frequency(self):
        counts=np.rint(20+10*np.sin(2*np.pi*100*np.arange(1000)/1000)).astype(int)
        times=np.concatenate([i*1000+np.arange(count) for i,count in enumerate(counts)])
        spectrum=frequency_spectrum(activity_series(events(times),0,1_000_000,1000))
        self.assertAlmostEqual(spectrum['peaks'][0]['hz'],100)
        self.assertAlmostEqual(spectrum['metadata']['nyquist_hz'],500)
        self.assertAlmostEqual(spectrum['metadata']['frequency_spacing_hz'],1)
        with self.assertRaises(ValueError): frequency_spectrum(activity_series(events([1]),0,4,1))

    def test_refractory_uses_last_retained_event(self):
        raw=events([0,2,4,6,9])
        filtered=apply_filters(raw,{'refractory_us':4})
        self.assertEqual(filtered.t.tolist(),[0,4,9]);self.assertEqual(raw.t.tolist(),[0,2,4,6,9])
        self.assertFalse(filtered.t.flags.writeable)

    def test_neighbor_filter_is_causal_and_excludes_same_pixel(self):
        raw=events([0,1,2,10],x=[0,0,1,2])
        filtered=apply_filters(raw,{'support_us':3})
        self.assertEqual(filtered.t.tolist(),[2])

    def test_hot_pixel_filter_and_cancellation(self):
        raw=events([0,1,2,3,4,999],x=[0,0,0,0,0,2])
        self.assertEqual(apply_filters(raw,{'hot_pixel_events_per_ms':2}).x.tolist(),[2])
        with self.assertRaises(CancelledError): apply_filters(raw,{'refractory_us':1},cancelled=lambda:True)

    def test_known_translation_and_blank_failure(self):
        rng=np.random.default_rng(2);image=np.zeros((32,32));coords=rng.integers(6,22,(30,2));image[coords[:,0],coords[:,1]]=1
        target=np.roll(np.roll(image,2,axis=1),-1,axis=0)
        result=estimate_translation(image,target,4)
        self.assertEqual((result['dx_px'],result['dy_px']),(2,-1))
        self.assertTrue(np.isnan(estimate_translation(image,np.zeros_like(image),4)['dx_px']))

    def test_motion_series_tracks_known_steps_and_reports_missing_links(self):
        rng=np.random.default_rng(3);coords=np.unique(rng.integers(6,22,(60,2)),axis=0)
        t=[];x=[];y=[]
        for frame in range(5):
            t.extend(frame*1000+np.arange(len(coords)));x.extend(coords[:,1]+frame);y.extend(coords[:,0])
        result=track_motion(events(t,x,y),(32,32),0,5000,1000,max_shift=4,minimum_events=10)
        self.assertEqual([row['dx_px'] for row in result['rows'][1:]],[1]*4)
        self.assertEqual(result['rows'][-1]['cumulative_x_px'],4)
        self.assertFalse(result['rows'][0]['valid'])

    def test_failed_export_preserves_existing_csv_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'out.csv';raw=events([0,1,2])
            export_csv(path,raw,(32,32));previous=(path.read_bytes(),path.with_suffix('.json').read_bytes())
            with patch('event_studio.project_utils.save_json',side_effect=OSError('write failed')):
                with self.assertRaises(OSError): export_csv(path,raw,(32,32),t0=1)
            self.assertEqual((path.read_bytes(),path.with_suffix('.json').read_bytes()),previous)
            import os
            real=os.replace
            def fail_metadata(src,dst):
                if Path(dst)==path.with_suffix('.json'): raise OSError('replacement failed')
                return real(src,dst)
            with patch('event_studio.io_utils.os.replace',side_effect=fail_metadata):
                with self.assertRaises(OSError): export_csv(path,raw,(32,32),t0=1)
            self.assertEqual((path.read_bytes(),path.with_suffix('.json').read_bytes()),previous)

    def test_invalid_session_preserves_dataset_and_overlays_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'raw.csv';path.write_text('t,x,y,p\n0,0,0,1\n10,1,1,0\n')
            raw=load_events_from_csv(path);window=MainWindow();window._load_csv_into_app(path,'test',prepared_events=raw)
            session=window._build_session_dict();session['view']['duration_us']='invalid'
            with self.assertRaises(ValueError): window._restore_session(session,raw)
            self.assertIs(window.events,raw);self.assertFalse(window._restoring)
            session['view']['duration_us']=10;session['view']['comparison']=True;session['view']['show_roi_overlays']=False
            window._restore_session(session,raw)
            self.assertFalse(window.compare_view._show_overlays);window.close()

    def test_final_trail_seek_is_not_stale(self):
        from event_studio.analysis_window import ROIAnalysisPanel
        panel=ROIAnalysisPanel();raw=events([0,100,300])
        for start in (0,200):
            panel.set_analysis_data(project_name='test',loaded_name='test',events=raw,hw=(32,32),roi_name='test',roi=Roi(0,0,32,32),roi_color='#ff0000',current_t0_us=start,current_window_us=100)
        self.assertEqual(panel._last_trail_playhead_us,300);panel.close()

    def test_png_temporal_mapping_and_manifest(self):
        from event_studio.visual_export import export_sequence
        with tempfile.TemporaryDirectory() as directory:
            manifest=export_sequence(Path(directory)/'frames',events([0,10000,30000]),(32,32),0,50000,'RAW',{},fps=30,width=32,height=32,timestamps=False)
            self.assertEqual([row['start_us'] for row in manifest['frames']],[0,33333])
            self.assertEqual(manifest['status'],'complete')

    def test_batch_rejects_unverified_roi_resolution(self):
        from event_studio.batch import analyze_batch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'raw.csv';source.write_text('t,x,y,p\n0,0,0,1\n10,1,1,0\n')
            report=analyze_batch([source],root/'output',rois=[{'name':'probe','roi':{'x':0,'y':0,'w':2,'h':2}}],expected_hw=(2,2))
            self.assertEqual(report['results'][0]['status'],'error')
            self.assertIn('inferred',report['results'][0]['error'])
