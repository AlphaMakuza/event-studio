"""Reproducible PNG sequences and optional FFmpeg MP4 encoding."""
from pathlib import Path
from fractions import Fraction
import shutil
import subprocess
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPainter,QColor,QFont
from .rendering import render_frame
from .filters import CancelledError
from .project_utils import save_json
from .version import __version__


def export_sequence(directory,events,hw,t0,t1,mode,parameters,*,fps=30,window_us=50000,
                    width=640,height=480,overlays=None,timestamps=True,mp4=False,
                    cancelled=lambda:False,progress=lambda n,message:None):
    if t0 < 0 or t1 <= t0 or window_us <= 0 or width <= 0 or height <= 0 or width*height > 16_777_216:
        raise ValueError("Use a valid interval, accumulation window and output dimensions up to 16 megapixels.")
    rate=Fraction(str(fps))
    if rate <= 0 or rate > 240: raise ValueError("Frame rate must be between 0 and 240 fps.")
    count=((t1-t0)*rate.numerator+1_000_000*rate.denominator-1)//(1_000_000*rate.denominator)
    if count > 50000: raise ValueError("Sequence exceeds 50,000 frames; reduce duration or frame rate.")
    if mp4 and shutil.which('ffmpeg') is None:
        raise ValueError("MP4 requires an FFmpeg executable on PATH. PNG sequences need no extra dependency.")
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    manifest={'software_version':__version__,'source':events.metadata,'classification':'visual representation, not event data',
              'mode':mode,'parameters':parameters,'start_us':t0,'end_us_exclusive':t1,'window_us':window_us,
              'fps':str(rate),'width':width,'height':height,'resize':'nearest-neighbor, aspect-preserving letterbox',
              'overlays':overlays or [],'timestamps':timestamps,'frames':[],'status':'running'}
    try:
        for i in range(count):
            if cancelled(): raise CancelledError("Visual export cancelled; manifest records completed frames.")
            start=t0+(i*1_000_000*rate.denominator)//rate.numerator
            end=min(t1,start+window_us)
            frame=np.ascontiguousarray(render_frame(events,hw,start,end-start,mode,parameters))
            image=QImage(frame.data,hw[1],hw[0],frame.strides[0],QImage.Format_RGB888).copy()
            scaled=image.scaled(width,height,Qt.KeepAspectRatio,Qt.FastTransformation)
            output=QImage(width,height,QImage.Format_RGB888);output.fill(QColor('black'))
            painter=QPainter(output);left=(width-scaled.width())//2;top=(height-scaled.height())//2
            painter.drawImage(left,top,scaled)
            for probe in overlays or []:
                roi=probe['roi'];painter.setPen(QColor(probe.get('color','#ff3b30')))
                painter.drawRect(left+int(roi['x']*scaled.width()/hw[1]),top+int(roi['y']*scaled.height()/hw[0]),
                                 int(roi['w']*scaled.width()/hw[1]),int(roi['h']*scaled.height()/hw[0]))
            if timestamps:
                painter.setFont(QFont('Segoe UI',10));painter.fillRect(0,0,width,22,QColor('black'));painter.setPen(QColor('white'))
                painter.drawText(6,16,f"{mode} | [{start}, {end}) us")
            painter.end();name=f'frame_{i:06d}.png'
            if not output.save(str(directory/name)): raise RuntimeError("Could not write visual frame.")
            manifest['frames'].append({'file':name,'start_us':start,'end_us_exclusive':end})
            progress(int((i+1)*100/count),'Exporting visualization frames')
        if mp4:
            result=subprocess.run([shutil.which('ffmpeg'),'-nostdin','-v','error','-framerate',str(rate),'-i',str(directory/'frame_%06d.png'),
                                   '-c:v','libx264','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-pix_fmt','yuv420p',str(directory/'visualization.mp4')],capture_output=True,text=True)
            if result.returncode: raise RuntimeError(result.stderr)
            manifest['mp4']='visualization.mp4'
        manifest['status']='complete'
    except Exception as exc:
        manifest['status']='cancelled' if isinstance(exc,CancelledError) else 'failed'
        manifest['error']=str(exc)
        raise
    finally:
        save_json(directory/'manifest.json',manifest)
    return manifest
