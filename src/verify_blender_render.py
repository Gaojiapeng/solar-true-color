"""Compare a flat native Blender reference render with the spectral model.

The illustrated clean render contains deliberate texture and glare. This
check uses the separately rendered reference, with all presentation effects
disabled, so a pleasing image cannot conceal a spectral shader regression.
"""
from pathlib import Path
import json

import cv2
import numpy as np

from .reference_geometry import trace_rays
from .blender_display import brightness_comparison, display_rgb
from .reference_geometry import srgb_encode

ROOT=Path(__file__).resolve().parents[1]


def verify(output_dir='output',data_dir='assets'):
    root=Path(output_dir)
    if not root.is_absolute():root=ROOT/root
    assets=Path(data_dir)
    if not assets.is_absolute():assets=ROOT/assets
    data=np.load(assets/'solar_blender_data.npz',allow_pickle=False)
    image=cv2.imread(str(root/'solar_blender_reference.png'),cv2.IMREAD_UNCHANGED)
    if image is None or image.dtype!=np.uint16:raise AssertionError('Expected Blender 16-bit PNG.')
    image=image[...,:3][...,::-1]/65535.
    height,width=image.shape[:2]
    yy,xx=np.mgrid[12:height:24,12:width:24]
    right,up,toward=(data[k] for k in ('right','up','toward'))
    reference_ortho_scale=3.05
    origins=(toward*6.+((xx+.5)/width-.5)[...,None]*reference_ortho_scale*right
             +(.5-(yy+.5)/height)[...,None]*(reference_ortho_scale*height/width)*up)
    hit=trace_rays(origins,-toward)
    keep=(hit['kind']>1)&(hit['radius']>.05)&(hit['radius']<.97)
    rgb=np.stack([np.interp(hit['radius'][keep],data['radius'],data['rgb'][:,c])
                  for c in range(3)],axis=-1)
    expected=srgb_encode(display_rgb(rgb))
    error=np.abs(image[yy[keep],xx[keep]]-expected)
    result={'reference_image':'solar_blender_reference.png',
            'presentation_effects':'Emission gain 1; texture, corona, annotations and compositor disabled',
            'reference_camera_ortho_scale':reference_ortho_scale,
            'comparison':brightness_comparison(data['rgb'][0],data['rgb'][-1]),
            'tested_cut_face_pixels':int(keep.sum()),
            'median_srgb_error':float(np.median(error)),
            'p99_srgb_error':float(np.quantile(error,.99)),
            'maximum_srgb_error':float(error.max()),
            'sample_coverage_passed':bool(keep.sum()>500),
            'color_error_passed':bool(np.quantile(error,.99)<.003),
            'passed':bool(keep.sum()>500 and np.quantile(error,.99)<.003)}
    (root/'solar_blender_color_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result)
    if not result['sample_coverage_passed']:
        raise AssertionError('Too few cut-face samples; render the full-resolution reference image.')
    if not result['color_error_passed']:
        raise AssertionError('Blender color/brightness disagrees with the reference model.')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='output')
    parser.add_argument('--data-dir',default='assets')
    args=parser.parse_args()
    verify(args.output_dir,args.data_dir)
