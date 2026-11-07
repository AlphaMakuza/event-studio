import unittest
import os
import tempfile
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from event_studio.motion_field import estimate_motion_field
from event_studio.viewer import EventBatch
from event_studio.rendering import motion_arrows,render_frame


def recording(before,after):
    arrays=[[],[],[],[]]
    for phase,image in enumerate((before,after)):
        for channel in range(2):
            ys,xs=np.nonzero(image[channel])
            repeats=image[channel,ys,xs].astype(int)
            x,y=np.repeat(xs,repeats),np.repeat(ys,repeats)
            for target,values in zip(arrays,(np.full(len(x),phase*1000),x,y,np.full(len(x),channel))):
                target.extend(values)
    result=EventBatch(*(np.array(values,dtype=dtype) for values,dtype in zip(arrays,(np.int64,np.int32,np.int32,np.int8))),
                      metadata={'sorted':True,'complete':True})
    for array in (result.t,result.x,result.y,result.p):array.flags.writeable=False
    return result


def texture(seed=4,height=96,width=96):
    rng=np.random.default_rng(seed)
    image=np.zeros((2,height,width),dtype=int)
    image[:,16:height-16,16:width-16]=rng.integers(1,4,(2,height-32,width-32))*(rng.random((2,height-32,width-32))<.12)
    return image


class MotionFieldTests(unittest.TestCase):
    def test_translations_follow_structure_in_every_direction(self):
        before=texture()
        for dx,dy in ((3,-2),(-3,2),(0,3),(3,0)):
            after=np.roll(np.roll(before,dy,axis=1),dx,axis=2)
            source=recording(before,after)
            vectors=estimate_motion_field(source,(96,96),0,2000,grid=16)
            self.assertGreater(len(vectors),0)
            self.assertTrue(all((v['dx_px'],v['dy_px'])==(dx,dy) for v in vectors),vectors)
            self.assertTrue(all(v['reverse_error_px']<=1 for v in vectors))

    def test_independent_objects_keep_opposite_directions(self):
        before=np.concatenate((texture(1),texture(2)),axis=2)
        after=np.concatenate((np.roll(before[:,:,:96],3,axis=2),np.roll(before[:,:,96:],-3,axis=2)),axis=2)
        vectors=estimate_motion_field(recording(before,after),(96,192),0,2000,grid=16)
        left=[v for v in vectors if v['x']<80];right=[v for v in vectors if v['x']>112]
        self.assertTrue(left and right)
        self.assertTrue(all(v['dx_px']==3 and v['dy_px']==0 for v in left))
        self.assertTrue(all(v['dx_px']==-3 and v['dy_px']==0 for v in right))

    def test_activity_centroid_shift_does_not_create_motion(self):
        before=texture();after=before.copy();after[:,:,:48]*=12
        self.assertEqual(estimate_motion_field(recording(before,after),(96,96),0,2000,grid=16),[])

    def test_unrelated_patterns_and_missing_events_do_not_create_arrows(self):
        before=texture()
        for after in (texture(19),np.zeros_like(before)):
            self.assertEqual(estimate_motion_field(recording(before,after),(96,96),0,2000,grid=16),[])

    def test_repetitive_patterns_and_straight_edges_are_ambiguous(self):
        pattern=np.zeros((2,96,96),dtype=int);pattern[1,::4,::4]=1
        self.assertEqual(estimate_motion_field(recording(pattern,np.roll(pattern,2,axis=2)),(96,96),0,2000,grid=16),[])
        edge=np.zeros_like(pattern);edge[1,:,40]=4
        self.assertEqual(estimate_motion_field(recording(edge,np.roll(edge,3,axis=2)),(96,96),0,2000,grid=16),[])

    def test_search_limit_motion_is_not_clipped_into_a_false_vector(self):
        before=texture();after=np.roll(before,8,axis=2)
        self.assertEqual(estimate_motion_field(recording(before,after),(96,96),0,2000,grid=16),[])

    def test_render_is_deterministic_and_preserves_source(self):
        before=texture();source=recording(before,np.roll(before,3,axis=2));saved=[a.copy() for a in (source.t,source.x,source.y,source.p)]
        first=motion_arrows(source,(96,96),0,2000,grid=16)
        np.testing.assert_array_equal(first,motion_arrows(source,(96,96),0,2000,grid=16))
        for expected,actual in zip(saved,(source.t,source.x,source.y,source.p)):np.testing.assert_array_equal(expected,actual)
        self.assertEqual(render_frame(source,(96,96),0,2000,'MOTION ARROWS',{'grid':16,'arrow_quality':.8}).shape,(96,96,3))

    def test_empty_tiny_and_single_timestamp_windows(self):
        source=recording(np.zeros((2,2,2),dtype=int),np.zeros((2,2,2),dtype=int))
        self.assertEqual(estimate_motion_field(source,(2,2),0,1),[])

    def test_match_quality_and_display_scale_persist(self):
        from PySide6.QtWidgets import QApplication
        from event_studio.app import MainWindow
        from event_studio.viewer import load_events_from_csv
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.csv';path.write_text('t,x,y,p\n0,0,0,1\n10,1,1,0\n')
            source=load_events_from_csv(path);window=MainWindow();window._load_csv_into_app(path,'fixture',prepared_events=source)
            self.assertEqual(window.arrow_scale_spin.value(),1.)
            window.arrow_quality_spin.setValue(.91)
            session=window._build_session_dict();other=MainWindow();other._restore_session(session,source)
            self.assertEqual(other.arrow_quality_spin.value(),.91)
            self.assertEqual(other._render_parameters()['arrow_algorithm'],'local-ncc-v1')
            window.close();other.close()
