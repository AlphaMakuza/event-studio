"""Conservative local translation estimates for the motion-arrow overlay.

Polarity-separated log-count patches are compared by normalized correlation.
Two-dimensional texture, match uniqueness and a reverse match are required.
This is an integer image-space estimate, not calibrated optical flow.
"""
import numpy as np
from .science import select


def _window_sum(image, side):
    integral = np.pad(image.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    return (integral[side:, side:] - integral[:-side, side:]
            - integral[side:, :-side] + integral[:-side, :-side])


def _match(reference, target, x, y, side, radius, quality, margin):
    template = reference[:, y:y + side, x:x + side]
    x0, y0 = max(0, x - radius), max(0, y - radius)
    x1 = min(target.shape[2], x + side + radius)
    y1 = min(target.shape[1], y + side + radius)
    search = target[:, y0:y1, x0:x1]
    centered = template - template.mean(axis=(1, 2), keepdims=True)
    energy = float(np.square(centered).sum())
    if energy < 1e-9:
        return None
    shape = tuple(1 << int(n - 1).bit_length()
                  for n in (search.shape[1] + side - 1, search.shape[2] + side - 1))
    numerator = np.zeros((search.shape[1] - side + 1, search.shape[2] - side + 1))
    variance = np.zeros_like(numerator)
    for channel in range(2):
        correlation = np.fft.irfft2(
            np.fft.rfft2(search[channel], s=shape)
            * np.fft.rfft2(centered[channel, ::-1, ::-1], s=shape), s=shape)
        numerator += correlation[side - 1:search.shape[1], side - 1:search.shape[2]]
        sums = _window_sum(search[channel], side)
        variance += _window_sum(np.square(search[channel]), side) - sums * sums / (side * side)
    scores = numerator / np.sqrt(energy * np.maximum(variance, 1e-12))
    scores = np.clip(scores, -1, 1)
    row, col = np.unravel_index(np.argmax(scores), scores.shape)
    score = float(scores[row, col])
    if score < quality:
        return None
    alternatives = scores.copy()
    # Adjacent offsets in a broad correlation peak are the same solution,
    # not competing structures. Compare against distinct peak basins.
    exclusion = max(2, min(5, radius // 3))
    alternatives[max(0, row - exclusion):row + exclusion + 1,
                 max(0, col - exclusion):col + exclusion + 1] = -np.inf
    if score - float(alternatives.max()) < margin:
        return None
    dx, dy = x0 + int(col) - x, y0 + int(row) - y
    # Peaks at the search limit may be clipped versions of faster motion.
    if abs(dx) >= radius or abs(dy) >= radius:
        return None
    return dx, dy, score


def estimate_motion_field(events, hw, t0, t1, polarity="both", grid=24,
                          minimum=10, quality=.65, margin=.04):
    """Return accepted local vectors; uncertain regions produce no estimate.

    `grid` is sampling spacing. Support is 2*grid and search is grid//2 pixels.
    Vectors measure translation between the interval's two equal time halves.
    No temporal smoothing or fabricated correspondence is applied.
    """
    if grid < 4 or minimum < 1 or not 0 <= quality <= 1 or margin < 0:
        raise ValueError("Invalid motion-field parameters.")
    height, width = hw
    side, radius = grid * 2, max(2, grid // 2)
    if t1 - t0 < 2 or min(hw) < side:
        return []
    middle = t0 + (t1 - t0) // 2
    counts = []
    for start, end in ((t0, middle), (middle, t1)):
        batch = select(events, start, end, polarity=polarity)
        image = np.zeros((2, height, width), dtype=np.float64)
        np.add.at(image, ((batch.p > 0).astype(np.intp), batch.y, batch.x), 1)
        counts.append(image)
    earlier, later = [np.log1p(image) for image in counts]
    vectors = []
    for y in range(0, height - side + 1, grid):
        for x in range(0, width - side + 1, grid):
            patch = earlier[:, y:y + side, x:x + side]
            if counts[0][:, y:y + side, x:x + side].sum() < minimum:
                continue
            occupied = np.any(patch > 0, axis=0)
            if occupied.sum() < 8:
                continue
            # A lone straight edge cannot determine motion along that edge.
            gy, gx = np.gradient(patch, axis=(1, 2))
            tensor = np.array([[np.square(gx).sum(), (gx * gy).sum()],
                               [(gx * gy).sum(), np.square(gy).sum()]])
            eigenvalues = np.linalg.eigvalsh(tensor)
            if eigenvalues[0] < .025 * max(1e-12, eigenvalues[1]):
                continue
            forward = _match(earlier, later, x, y, side, radius, quality, margin)
            if forward is None:
                continue
            dx, dy, score = forward
            if dx == 0 and dy == 0:
                continue
            tx, ty = x + dx, y + dy
            if counts[1][:, ty:ty + side, tx:tx + side].sum() < minimum:
                continue
            reverse = _match(later, earlier, tx, ty, side, radius, quality, margin)
            if reverse is None or np.hypot(dx + reverse[0], dy + reverse[1]) > 1:
                continue
            weights = patch.sum(axis=0)
            yy, xx = np.indices(weights.shape)
            # Anchor on matched activity in the later image. Centroids place
            # the glyph only; they are never used to infer its displacement.
            anchor_x = x + float((xx * weights).sum() / weights.sum()) + dx
            anchor_y = y + float((yy * weights).sum() / weights.sum()) + dy
            vectors.append({"x": anchor_x, "y": anchor_y, "dx_px": dx,
                            "dy_px": dy, "correlation": min(score, reverse[2]),
                            "reverse_error_px": float(np.hypot(dx + reverse[0], dy + reverse[1]))})
    return vectors
