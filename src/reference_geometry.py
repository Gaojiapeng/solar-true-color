"""Independent analytic octant-ray and sRGB reference, using only NumPy."""
import numpy as np


def trace_rays(origins, directions, cutaway=True):
    """Return the nearest nonnegative boundary intersection of each ray.

    Arrays broadcast to (..., 3). Directions are normalized so distance is in
    solar radii. kind: 0 miss, 1 sphere, 2 x-cut, 3 y-cut, 4 z-cut.
    Miss points/radii are zero; miss distances are infinity.
    """
    origins, directions = np.broadcast_arrays(np.asarray(origins, float),
                                               np.asarray(directions, float))
    if origins.shape[-1:] != (3,):
        raise ValueError("Rays must have a trailing xyz axis.")
    norm = np.linalg.norm(directions, axis=-1, keepdims=True)
    if not (np.all(np.isfinite(origins)) and np.all(np.isfinite(directions))) or np.any(norm == 0):
        raise ValueError("Rays must be finite with nonzero directions.")
    directions = directions / norm
    shape = origins.shape[:-1]
    distance = np.full(shape, np.inf)
    kind = np.zeros(shape, dtype=np.uint8)
    b = np.sum(origins * directions, axis=-1)
    c = np.sum(origins * origins, axis=-1) - 1.
    discriminant = b*b - c
    root = np.sqrt(np.maximum(discriminant, 0))
    for t in (-b-root, -b+root):
        p = origins + t[..., None]*directions
        valid = (discriminant >= 0) & (t >= 0)
        if cutaway:
            valid &= ~np.all(p > 1e-10, axis=-1)
        select = valid & (t < distance)
        distance = np.where(select, t, distance)
        kind = np.where(select, 1, kind).astype(np.uint8)
    if cutaway:
        for axis in range(3):
            denominator = directions[..., axis]
            t = np.divide(-origins[..., axis], denominator,
                          out=np.full(shape, np.inf), where=np.abs(denominator) > 1e-12)
            safe_t = np.where(np.isfinite(t), t, 0.)
            p = origins + safe_t[..., None]*directions
            other = [i for i in range(3) if i != axis]
            valid = (np.isfinite(t) & (t >= 0)
                     & np.all(p[..., other] >= -1e-10, axis=-1)
                     & (np.sum(p*p, axis=-1) <= 1. + 1e-10))
            select = valid & (t < distance)
            distance = np.where(select, t, distance)
            kind = np.where(select, axis+2, kind).astype(np.uint8)
    points = origins + np.where(kind > 0, distance, 0.)[..., None]*directions
    points = np.where((kind > 0)[..., None], points, 0.)
    return {"points": points, "radius": np.minimum(np.linalg.norm(points, axis=-1), 1.),
            "kind": kind, "distance": distance}

def srgb_encode(linear):
    """Encode nonnegative linear RGB with the standard sRGB transfer."""
    linear=np.asarray(linear,dtype=float)
    if not np.all(np.isfinite(linear)) or np.any(linear<0):
        raise ValueError('Expected finite, nonnegative linear RGB')
    return np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055)
