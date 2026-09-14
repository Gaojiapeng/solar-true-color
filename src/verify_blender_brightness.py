"""Render native Blender control changes to verify brightness monotonicity.

Run in background with the delivered .blend loaded. Does not save changes to
that file; temporary renders are removed on completion.
"""
from pathlib import Path
import json
import tempfile

import bpy
import numpy as np


def rendered_pixels(path):
    bpy.context.scene.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)
    image=bpy.data.images.load(str(path),check_existing=False)
    values=np.asarray(image.pixels[:],dtype=np.float64).reshape(-1,4)[:,:3]
    bpy.data.images.remove(image)
    # Blender's loaded PNG pixels are scene-linear after sRGB decoding.
    return values@np.array([.2126,.7152,.0722])


scene=bpy.context.scene
scene.render.resolution_x=400
scene.render.resolution_y=267
scene.cycles.samples=16
bpy.data.collections['Annotations | hide for clean render'].hide_render=True
bpy.data.collections['Layer guides | annotations'].hide_render=True
bpy.data.collections['Corona | illustrative visible-light atmosphere'].hide_render=True
scene.render.use_compositing=False
controller=bpy.data.objects['Solar brightness controls']
controller['surface_texture']=0.
controller['interior_texture']=0.
controller['solar_emission_gain']=1.
root=Path(bpy.data.filepath).parent
with tempfile.TemporaryDirectory(prefix='solar_brightness_') as directory:
    checks=[]
    # Both changes should lift faint structures without reversing brightness.
    for property_name,values in (('compression',(1e4,1e9)),
                                ('display_power',(.95,.35))):
        result=[]
        controller['compression']=1e7
        controller['display_power']=.60
        for value in values:
            controller[property_name]=value
            controller.update_tag()
            scene.frame_set(scene.frame_current)
            bpy.context.view_layer.update()
            node=bpy.data.node_groups['Solar brightness | shared global curve'].nodes[property_name]
            if abs(node.outputs[0].default_value-value)>abs(value)*1e-6:
                raise AssertionError(f'Shared {property_name} driver did not update.')
            result.append(rendered_pixels(Path(directory)/f'{property_name}_{value:g}.png'))
        # Use a fraction of the frame, robust to the expanded corona framing.
        difference=result[1]-result[0]
        brightened_fraction=float(np.mean(difference>.001))
        checks.append({'control':property_name,'values':list(values),
                       'mean_luminance_before':float(result[0].mean()),
                       'mean_luminance_after':float(result[1].mean()),
                       'minimum_pixel_luminance_change':float(difference.min()),
                       'pixels_brightened':int(np.count_nonzero(difference>.001)),
                       'fraction_of_frame_brightened':brightened_fraction,
                       'passed':bool(difference.mean()>.003 and difference.min()>-.0005
                                     and brightened_fraction>.05)})
    report={'presentation_effects':'Emission gain 1; texture, corona, annotations and compositor disabled',
            'checks':checks, 'passed':all(check['passed'] for check in checks)}
    (root/'solar_blender_brightness_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('BLENDER_BRIGHTNESS_VALIDATION',json.dumps(report))
    if not report['passed']:raise AssertionError('Rendered brightness failed monotonic-response check.')
