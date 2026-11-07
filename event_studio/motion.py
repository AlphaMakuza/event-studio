"""Image-space integer displacement estimates, never inferred physical motion."""
import math
import numpy as np
from .science import select
from .filters import CancelledError


def estimate_translation(reference, target, max_shift=16):
    if reference.shape != target.shape or reference.ndim != 2:
        raise ValueError("Tracking requires equal two-dimensional accumulation images.")
    height, width = reference.shape
    if max_shift < 1 or max_shift >= min(height, width) / 2:
        raise ValueError("Maximum shift must be positive and less than half the ROI's shortest side.")
    a, b = reference.astype(float), target.astype(float)
    a -= a.mean(); b -= b.mean()
    if not a.any() or not b.any():
        return {"dx_px": float("nan"), "dy_px": float("nan"), "quality": 0.}
    cross = np.fft.fft2(b) * np.conj(np.fft.fft2(a))
    magnitude = np.abs(cross)
    correlation = np.fft.ifft2(cross / np.maximum(magnitude, 1e-12)).real
    xs = np.arange(width); xs = np.where(xs > width//2, xs-width, xs)
    ys = np.arange(height); ys = np.where(ys > height//2, ys-height, ys)
    allowed = (np.abs(ys[:,None]) <= max_shift) & (np.abs(xs[None,:]) <= max_shift)
    row, col = np.unravel_index(np.argmax(np.where(allowed, correlation, -np.inf)), correlation.shape)
    # Heuristic peak prominence, NOT a calibrated confidence probability.
    quality = max(0., float(correlation[row, col])) / max(1e-12, float(np.abs(correlation).sum()))
    return {"dx_px": float(xs[col]), "dy_px": float(ys[row]), "quality": quality}


def track_motion(events, hw, t0, t1, bin_us=10000, roi=None, polarity="both", max_shift=8,
                 minimum_events=10, minimum_quality=.05, units_per_pixel=0., unit="px",
                 cancelled=lambda:False, progress=lambda n,message:None):
    from .activity import activity_series
    if minimum_events < 1 or not math.isfinite(minimum_quality) or not 0 <= minimum_quality <= 1:
        raise ValueError("Use a positive minimum event count and quality threshold between 0 and 1.")
    if not math.isfinite(units_per_pixel) or units_per_pixel < 0:
        raise ValueError("Calibration must be zero (pixels) or a positive units-per-pixel scale.")
    series = activity_series(events,t0,t1,bin_us,roi,polarity)
    if len(series.total) > 2000:
        raise ValueError("Tracking is limited to 2000 windows; increase the bin width.")
    height, width = (roi.h, roi.w) if roi else hw
    if max_shift < 1 or max_shift >= min(height,width)/2:
        raise ValueError("Choose a larger ROI or reduce maximum shift below half its shortest side.")
    rows, previous, previous_count = [], None, 0
    cumulative_x = cumulative_y = 0.
    for i, (start,end) in enumerate(zip(series.start_us,series.end_us)):
        if cancelled(): raise CancelledError("Motion analysis cancelled.")
        progress(int(i*100/max(1,len(series.total))),"Estimating image-space displacement")
        batch = select(events,int(start),int(end),roi,polarity)
        frame = np.zeros((height,width),dtype=np.float64)
        np.add.at(frame,(batch.y-(roi.y if roi else 0),batch.x-(roi.x if roi else 0)),1)
        valid = previous is not None and len(batch.t) >= minimum_events and previous_count >= minimum_events
        estimate = estimate_translation(previous,frame,max_shift) if valid else {"dx_px":float('nan'),"dy_px":float('nan'),"quality":0.}
        valid = valid and estimate['quality'] >= minimum_quality and math.isfinite(estimate['dx_px'])
        if i == 0:
            valid = False
            reason = "reference window"
        else:
            reason = "ok" if valid else "insufficient events, texture or peak prominence"
        if i:
            if valid and math.isfinite(cumulative_x):
                cumulative_x += estimate['dx_px']; cumulative_y += estimate['dy_px']
            else:
                cumulative_x = cumulative_y = float('nan')
        scale = units_per_pixel if units_per_pixel else 1.
        rows.append({"start_us":int(start),"end_us_exclusive":int(end),"events":len(batch.t),
                     "dx_px":estimate['dx_px'] if valid else float('nan'),
                     "dy_px":estimate['dy_px'] if valid else float('nan'),"quality":estimate['quality'],
                     "cumulative_x_px":cumulative_x,"cumulative_y_px":cumulative_y,
                     "dx_calibrated":estimate['dx_px']*scale if valid else float('nan'),
                     "dy_calibrated":estimate['dy_px']*scale if valid else float('nan'),
                     "valid":bool(valid),"reason":reason})
        previous, previous_count = frame, len(batch.t)
    return {"rows":rows,"metadata":{**series.metadata,"algorithm":"integer phase correlation of adjacent count images",
            "max_shift_px":max_shift,"minimum_events":minimum_events,"minimum_quality":minimum_quality,
            "quality_definition":"peak / sum(abs(correlation)); heuristic, not a probability",
            "units_per_pixel":units_per_pixel,"unit":unit if units_per_pixel else "px",
            "limitations":"Integer image-space estimate. Circular-correlation assumption, no subpixel interpolation. Cumulative trajectory remains unknown after any failed link."}}
