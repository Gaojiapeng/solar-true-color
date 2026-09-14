"""Numerical reference for Blender's shared, chromaticity-preserving curve.

The additional power acts on normalized log luminance, before the display
ceiling and sRGB encoding. It is not a channel-wise gamma correction. Glare,
illustrative texture, and atmospheric emission are deliberately outside this
reference: disable those effects when comparing source and rendered radiance.
Only NumPy is required, so Blender's bundled Python can import this module.
"""
from __future__ import annotations

import numpy as np


LUMINANCE_WEIGHTS = np.array([.2126, .7152, .0722], dtype=np.float64)


def _positive(value, name):
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and greater than zero')
    return value


def _nonnegative(values, name):
    values = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError(f'{name} must contain finite, nonnegative values')
    return values


def display_luminance(values, *, compression=1e7, reference_luminance=60000.,
                      display_peak=.40, exposure_ev=0., display_power=.60):
    """Return P * [log1p(c * min(Y * 2**EV / ref, 1)) / log1p(c)]**q.

    Black remains black; increasing input Y increases output until the fixed
    reference saturates. Values 0 < q < 1 reduce contrast beyond log alone.
    This is the target luminance before the scalar display-gamut ceiling.
    """
    values = _nonnegative(values, 'luminance')
    compression = _positive(compression, 'compression')
    reference_luminance = _positive(reference_luminance, 'reference_luminance')
    display_peak = _positive(display_peak, 'display_peak')
    display_power = _positive(display_power, 'display_power')
    if display_peak > 1:
        raise ValueError('display_peak must be at most one')
    exposure_ev = float(exposure_ev)
    if not np.isfinite(exposure_ev):
        raise ValueError('exposure_ev must be finite')
    # Evaluating the exposure ratio in log space avoids overflow from large
    # finite signals or exposure; the reference is a fixed ceiling.
    log_values = np.full(values.shape, -np.inf, dtype=np.float64)
    np.log(values, out=log_values, where=values > 0)
    ratio = np.exp(np.minimum(log_values + exposure_ev*np.log(2.)
                              - np.log(reference_luminance), 0.))
    normalized_log = np.log1p(compression*ratio) / np.log1p(compression)
    return display_peak * np.clip(normalized_log, 0., 1.)**display_power


def display_rgb(rgb, *, compression=1e7, reference_luminance=60000.,
                display_peak=.40, exposure_ev=0., display_power=.60):
    """Return display-linear RGB, preserving source linear channel ratios.

    A shared scalar gamut ceiling guarantees channels <= 1. It can reduce
    luminance for colors that would otherwise exceed the display gamut.
    """
    rgb = _nonnegative(rgb, 'linear RGB')
    if rgb.ndim == 0 or rgb.shape[-1] != 3:
        raise ValueError('linear RGB must have a final axis of length three')
    y = np.sum(rgb*LUMINANCE_WEIGHTS, axis=-1)
    mapped_y = display_luminance(y, compression=compression,
                                reference_luminance=reference_luminance,
                                display_peak=display_peak, exposure_ev=exposure_ev,
                                display_power=display_power)
    chromaticity = np.divide(rgb, y[..., None], out=np.zeros_like(rgb),
                             where=y[..., None] > 0)
    linear = chromaticity*mapped_y[..., None]
    return linear / np.maximum(1., np.max(linear, axis=-1, keepdims=True))


def brightness_comparison(center_rgb, surface_rgb, **settings):
    """Compare two thermal spectra on the shared curve, without visual effects."""
    source = np.asarray([center_rgb, surface_rgb], dtype=np.float64)
    if source.shape != (2, 3):
        raise ValueError('center_rgb and surface_rgb must each have three channels')
    mapped = display_rgb(source, **settings)
    source_y = source@LUMINANCE_WEIGHTS
    mapped_y = mapped@LUMINANCE_WEIGHTS
    if source_y[1] <= 0 or mapped_y[1] <= 0:
        raise ValueError('The comparison surface must have positive luminance')
    return {'center_source_luminance': float(source_y[0]),
            'surface_source_luminance': float(source_y[1]),
            'source_ratio': float(source_y[0]/source_y[1]),
            'center_display_luminance': float(mapped_y[0]),
            'surface_display_luminance': float(mapped_y[1]),
            'displayed_ratio': float(mapped_y[0]/mapped_y[1]),
            'center_display_rgb': mapped[0].tolist(),
            'surface_display_rgb': mapped[1].tolist()}
