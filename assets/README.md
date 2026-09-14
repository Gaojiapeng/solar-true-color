# Prepared solar inputs

`solar_blender_data.npz` is the complete, uncompressed-in-value numeric input snapshot used by the Blender scene. The NPZ container is losslessly compressed. It contains no Python objects and is loaded with `allow_pickle=False`.

| Array | Meaning |
| --- | --- |
| `radius`, `temperature` | Model radius in solar radii and local temperature in kelvin |
| `rgb`, `luminance` | Relative visible thermal radiance from Planck spectra integrated against CIE 1931 functions |
| `surface` | 1024 × 1024 linear RGB HMI continuum proxy, anchored to model photospheric brightness |
| `surface_mask` | Valid observed-disk footprint |
| `right`, `up`, `toward` | Camera and projection basis vectors |

The rendering snapshot was prepared from [Model S](https://phys.au.dk/~jcd/solar_models/), [CIE 1931 two-degree color matching functions](https://cie.co.at/datatable/cie-1931-colour-matching-functions-2-degree-observer), and an SDO/HMI continuum observation identified in `solar_blender_sources.json`. The JSON retains source filenames, timestamps, hashes, radiometric assumptions, and the NPZ checksum. Machine-specific source paths have been removed.

The snapshot is sufficient to rebuild this visualization offline. Raw FITS acquisition and the original scientific preparation pipeline are outside this repository. The source temperature and radiance arrays remain available for inspection and modification; this is not a new reconstruction of the solar interior.

The `upstream_preparation_tone_mapping` metadata records the original preparation configuration. The current Blender controls are defined in `src/blender_sun.py` and exported to `output/solar_blender_presentation.json` on every build.
