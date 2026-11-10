"""Build a closed cutter above a single-valued height field in local +Z.

Caller owns seam tracing, units (mm), coverage, clearance, and world transforms.
"""
import numpy as np
import manifold3d as m


def graph_above(gx, gy, heights, ceiling):
    gx, gy, h = map(lambda a: np.asarray(a, dtype=np.float64), (gx, gy, heights))
    if gx.ndim != 1 or gy.ndim != 1 or min(len(gx), len(gy)) < 2:
        raise ValueError("gx and gy must each be 1D with at least two points")
    if h.shape != (len(gx), len(gy)):
        raise ValueError("heights must have shape (len(gx), len(gy))")
    if not all(np.isfinite(a).all() for a in (gx, gy, h)) or not np.isfinite(ceiling):
        raise ValueError("All inputs must be finite")
    if not (np.diff(gx) > 0).all() or not (np.diff(gy) > 0).all():
        raise ValueError("Grid coordinates must be strictly increasing")
    if ceiling <= h.max():
        raise ValueError("ceiling must be strictly above every height")
    x, y = np.meshgrid(gx, gy, indexing="ij")
    v = np.column_stack((x.ravel(), y.ravel(), h.ravel()))
    n = len(v)
    v = np.vstack((v, np.column_stack((v[:, :2], np.full(n, ceiling)))))
    idx = np.arange(n).reshape(len(gx), len(gy))
    a, b = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel()
    c, d = idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    bottom = np.concatenate((np.column_stack((a, c, b)), np.column_stack((a, d, c))))
    rim = np.concatenate((idx[:-1, 0], idx[-1, :-1], idx[:0:-1, -1], idx[0, :0:-1]))
    nxt = np.roll(rim, -1)
    faces = np.vstack((bottom, bottom[:, ::-1] + n,
                       np.column_stack((rim, nxt, nxt + n)),
                       np.column_stack((rim, nxt + n, rim + n))))
    solid = m.Manifold(m.Mesh64(np.ascontiguousarray(v), np.asarray(faces, dtype=np.uint64)))
    if solid.status() != m.Error.NoError or solid.is_empty() or solid.volume() <= 0:
        raise ValueError(f"Invalid cutter: {solid.status()}")
    return solid
