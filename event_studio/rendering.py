"""Presentation-only renderers. Input event arrays are never modified."""
from __future__ import annotations

import numpy as np
from .science import select

POSITIVE = np.array([255, 135, 50], dtype=np.float64)
NEGATIVE = np.array([55, 165, 255], dtype=np.float64)


def raw(events, hw, t0, t1, polarity="both"):
    batch = select(events, t0, t1, polarity=polarity)
    image = np.zeros((*hw, 3), dtype=np.uint8)
    # Presence encoding, no per-frame normalization. Mixed pixels are white.
    pos = np.zeros(hw, dtype=bool)
    neg = np.zeros(hw, dtype=bool)
    pm = batch.p > 0
    pos[batch.y[pm], batch.x[pm]] = True
    neg[batch.y[~pm], batch.x[~pm]] = True
    image[pos] = POSITIVE
    image[neg] = NEGATIVE
    image[pos & neg] = 255
    return image


def heatmap(events, hw, t0, t1, polarity="both", scaling="Log relative"):
    batch = select(events, t0, t1, polarity=polarity)
    count = np.zeros(hw, dtype=np.uint64)
    np.add.at(count, (batch.y, batch.x), 1)
    values = count.astype(np.float64)
    if scaling == "Log relative":
        values = np.log1p(values)
    if scaling == "Absolute (100 events/pixel)":
        norm = np.clip(values / 100, 0, 1)
    else:
        norm = values / max(1, float(values.max()))
    # Black is zero; white is the upper scale limit.
    rgb = np.stack((np.minimum(1, norm * 3), np.clip(norm * 3 - 1, 0, 1),
                    np.clip(norm * 3 - 2, 0, 1)), axis=-1)
    return (rgb * 255).astype(np.uint8), int(count.max())


def persistence(events, hw, end_us, duration_us, polarity="both"):
    start = end_us - duration_us
    batch = select(events, start, end_us, polarity=polarity)
    # Latest real event at each pixel, linearly faded by its actual age.
    image = np.zeros((*hw, 3), dtype=np.float64)
    for positive, color in ((True, POSITIVE), (False, NEGATIVE)):
        mask = (batch.p > 0) if positive else (batch.p <= 0)
        latest = np.full(hw, -1, dtype=np.int64)
        np.maximum.at(latest, (batch.y[mask], batch.x[mask]), batch.t[mask])
        valid = latest >= 0
        intensity = np.zeros(hw, dtype=np.float64)
        intensity[valid] = 1 - (end_us - latest[valid]) / max(1, duration_us)
        image += np.clip(intensity, 0, 1)[..., None] * color
    return np.clip(image, 0, 255).astype(np.uint8)


def glow(events, hw, t0, t1, polarity="both", intensity=0.7):
    base = raw(events, hw, t0, t1, polarity).astype(np.float64)
    # Explicit spatial halo; this is styling, never exported as event data.
    halo = np.zeros_like(base)
    padded = np.pad(base, ((2, 2), (2, 2), (0, 0)))
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            weight = np.exp(-(dx * dx + dy * dy) / 3) / 5
            halo += weight * padded[2 + dy:2 + dy + hw[0], 2 + dx:2 + dx + hw[1]]
    return np.clip(base + intensity * halo, 0, 255).astype(np.uint8)


def time_colors(values):
    values = np.clip(values, 0, 1)
    return np.stack((np.clip(2.2 * values - .2, 0, 1),
                     np.clip(1.8 - 2 * np.abs(values - .5), 0, 1),
                     np.clip(1.2 - 2 * values, 0, 1)), axis=-1)


def legacy_trail(events, hw, t0, t1, polarity="both"):
    batch = select(events, t0, t1, polarity=polarity)
    image = np.zeros((*hw, 3), dtype=np.float64)
    if len(batch.t):
        relative = batch.t - int(batch.t.min())
        colors = time_colors(relative / max(1, int(relative.max())))
        for channel in range(3):
            np.add.at(image[..., channel], (batch.y, batch.x), colors[:, channel])
        image = np.log1p(image)
        image /= max(1e-12, float(image.max()))
    return (image * 255).astype(np.uint8)


def motion_arrows(events, hw, t0, t1, polarity="both", grid=24, scale=1., minimum=10, silhouette=.4, quality=.65):
    heat, _ = heatmap(events, hw, t0, t1, polarity)
    canvas = np.clip(np.array([24, 34, 58]) * (1 - silhouette) + heat * silhouette, 0, 255).astype(np.uint8)
    from .motion_field import estimate_motion_field
    vectors = estimate_motion_field(events, hw, t0, t1, polarity, grid, minimum, quality)

    def line(x0, y0, x1, y1, color):
        length = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.rint(np.linspace(x0, x1, length)).astype(int)
        ys = np.rint(np.linspace(y0, y1, length)).astype(int)
        valid = (xs >= 0) & (ys >= 0) & (xs < hw[1]) & (ys < hw[0])
        canvas[ys[valid], xs[valid]] = color

    drawn = []
    for vector in sorted(vectors,key=lambda v:(-v['correlation'],v['y'],v['x'])):
        x0, y0 = vector["x"], vector["y"]
        if any(np.hypot(x0-x,y0-y)<grid*.65 for x,y in drawn):
            continue
        drawn.append((x0,y0))
        dx, dy = vector["dx_px"], vector["dy_px"]
        x1, y1 = x0 + dx * scale, y0 + dy * scale
        color = (70, 210, 255)
        line(x0, y0, x1, y1, color)
        angle = np.arctan2(y1-y0, x1-x0)
        head = min(6., max(1.5, np.hypot(dx, dy) * scale * .4))
        for rotation in (-.6, .6):
            line(x1, y1, x1 - head * np.cos(angle + rotation), y1 - head * np.sin(angle + rotation), color)
    return canvas


def render_frame(events, hw, t0, window_us, mode, parameters):
    end = t0 + window_us
    polarity = parameters.get("polarity", "both")
    if mode == "HEATMAP":
        return heatmap(events, hw, t0, end, polarity, parameters.get("heat_scale", "Log relative"))[0]
    if mode == "PERSISTENCE TRAILS":
        return persistence(events, hw, end, parameters.get("persistence_us", 100000), polarity)
    if mode == "POLARITY GLOW":
        return glow(events, hw, t0, end, polarity, parameters.get("glow", .7))
    if mode == "TRAIL":
        return legacy_trail(events, hw, t0, end, polarity)
    if mode == "MOTION ARROWS":
        return motion_arrows(events, hw, t0, end, polarity, parameters.get("grid", 24),
                             parameters.get("scale", 1.), parameters.get("minimum", 10),
                             parameters.get("silhouette", .4), parameters.get("arrow_quality", .65))
    return raw(events, hw, t0, end, polarity)
