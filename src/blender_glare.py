"""Editable Blender 5.2 postprocess glare with a dedicated cut-face seed.

The physical Sun (object index 1) makes a restrained halo. The exposed interior
(material index 1) produces the stronger luminous bloom and faint lens streaks.
Annotations, comparison swatches, and the corona never seed these effects.
"""
from __future__ import annotations

import bpy


def _mix(tree, name, mode, first, second, factor=1.0, location=(0, 0)):
    node = tree.nodes.new('ShaderNodeMixRGB')
    node.name = name
    node.label = name
    node.blend_type = mode
    node.location = location
    node.inputs[0].default_value = factor
    for value, socket in ((first, node.inputs[1]), (second, node.inputs[2])):
        if hasattr(value, 'node'):
            tree.links.new(value, socket)
        else:
            socket.default_value = value
    return node


def _mask(tree, name, source, location):
    node = tree.nodes.new('CompositorNodeIDMask')
    node.name = name
    node.location = location
    node.inputs['Index'].default_value = 1
    node.inputs['Anti-Alias'].default_value = True
    tree.links.new(source, node.inputs['ID value'])
    return node.outputs['Alpha']


def _glare(tree, name, seed, *, threshold, strength, size, location):
    node = tree.nodes.new('CompositorNodeGlare')
    node.name = name
    node.label = name
    node.location = location
    node.inputs['Type'].default_value = 'Fog Glow'
    node.inputs['Quality'].default_value = 'High'
    node.inputs['Threshold'].default_value = threshold
    node.inputs['Smoothness'].default_value = 0.12
    # Keep emission HDR through the optical effect. Clamping at one here would
    # remove the very highlights that should produce visible cut-face glare.
    node.inputs['Clamp'].default_value = False
    node.inputs['Strength'].default_value = strength
    node.inputs['Saturation'].default_value = 1.0
    node.inputs['Size'].default_value = size
    tree.links.new(seed, node.inputs['Image'])
    return node


def _math(tree, operation, a, b=None):
    node = tree.nodes.new('ShaderNodeMath')
    node.operation = operation
    for value, socket in ((a, node.inputs[0]), (b, node.inputs[1])):
        if value is not None:
            if hasattr(value, 'node'):
                tree.links.new(value, socket)
            else:
                socket.default_value = value
    return node.outputs[0]


def _highlight_shoulder(tree, source):
    """Retain bright HDR luminance without hard clipping blue solar highlights.

    Pixels inside the display gamut and below the .70 luminance knee bypass
    this operation exactly. Compress higher luminance smoothly toward .98 and
    mix the minimum neutral light needed to bring the largest channel to one.
    """
    initial_nodes = set(tree.nodes)
    separate = tree.nodes.new('ShaderNodeSeparateXYZ')
    separate.name = 'HDR highlight | separate original channels'
    tree.links.new(source, separate.inputs[0])
    maximum = _math(tree, 'MAXIMUM', separate.outputs[0], separate.outputs[1])
    maximum = _math(tree, 'MAXIMUM', maximum, separate.outputs[2])
    is_hdr = _math(tree, 'GREATER_THAN', maximum, 1.0)
    luminance = tree.nodes.new('ShaderNodeVectorMath')
    luminance.name = 'HDR highlight | Rec.709 luminance'
    luminance.operation = 'DOT_PRODUCT'
    tree.links.new(source, luminance.inputs[0])
    luminance.inputs[1].default_value = (.2126, .7152, .0722)
    y = luminance.outputs['Value']
    needs_shoulder = _math(tree, 'MAXIMUM', is_hdr, _math(tree, 'GREATER_THAN', y, .70))
    high = _math(tree, 'MAXIMUM', _math(tree, 'SUBTRACT', y, .70), 0.0)
    exponent = _math(tree, 'DIVIDE', high, -.28)
    exponential = _math(tree, 'POWER', 2.718281828459045, exponent)
    tail = _math(tree, 'MULTIPLY', _math(tree, 'SUBTRACT', 1.0, exponential), .28)
    softened_y = _math(tree, 'ADD', _math(tree, 'MINIMUM', y, .70), tail)
    ratio = _math(tree, 'DIVIDE', softened_y, _math(tree, 'MAXIMUM', y, 1e-12))
    scaled = _mix(tree, 'HDR highlight | soft luminance shoulder', 'MULTIPLY', source, ratio)
    scaled_maximum = _math(tree, 'MULTIPLY', maximum, ratio)
    numerator = _math(tree, 'MAXIMUM', _math(tree, 'SUBTRACT', scaled_maximum, 1.0), 0.0)
    denominator = _math(tree, 'MAXIMUM', _math(tree, 'SUBTRACT', scaled_maximum, softened_y), 1e-12)
    neutral_mix = _math(tree, 'MINIMUM', _math(tree, 'DIVIDE', numerator, denominator), 1.0)
    neutral = _mix(tree, 'HDR highlight | minimum neutral mix preserves luminance',
                   'MIX', scaled.outputs[0], softened_y)
    tree.links.new(neutral_mix, neutral.inputs[0])
    restored = _mix(tree, 'HDR highlight | exact bypass below knee and in gamut', 'MIX', source, neutral.outputs[0])
    tree.links.new(needs_shoulder, restored.inputs[0])
    for i, node in enumerate(n for n in tree.nodes if n not in initial_nodes):
        node.location = (900 + (i % 6) * 215, -450 - (i // 6) * 175)
    return restored.outputs[0]


def setup_glare(scene, controller):
    """Attach solar-only glare and a luminance-preserving HDR highlight shoulder.

    Mark the Sun with object index 1 and its exposed cut-face material with
    material index 1. Additional solar emitter objects can also opt in through
    ``obj['solar_glare_emitter'] = True``. All annotation indices stay zero.
    """
    if 'glare_strength' not in controller:
        controller['glare_strength'] = 0.35
    controller.id_properties_ui('glare_strength').update(
        min=0.0, max=1.0, soft_min=0.0, soft_max=0.6,
        description='Blender postprocess glare: strong cut-face bloom and a '
                    'gentler solar halo. Default 0.35; zero disables glare. '
                    'Labels and comparison swatches never seed glare.')
    for obj in scene.objects:
        if obj.name == 'Sun | exact 7/8 solid' or obj.get('solar_glare_emitter', False):
            obj.pass_index = 1

    layer = scene.view_layers[0]
    layer.use_pass_object_index = True
    layer.use_pass_material_index = True
    layer.update_render_passes()
    group = bpy.data.node_groups.new('Solar glare | luminous cut faces', 'CompositorNodeTree')
    group.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    scene.compositing_node_group = group
    scene.render.use_compositing = True
    nodes, links = group.nodes, group.links

    render = nodes.new('CompositorNodeRLayers')
    render.name = 'Original HDR render | untouched at glare strength zero'
    render.scene = scene
    render.layer = layer.name
    render.location = (-1300, 300)

    solar_mask = _mask(group, 'Solar geometry only | object index 1',
                       render.outputs['Object Index'], (-1300, -30))
    cut_mask = _mask(group, 'Exposed interior only | material index 1',
                     render.outputs['Material Index'], (-1300, -300))
    solar_seed = _mix(group, 'Solar emission | no typography or corona', 'MULTIPLY',
                      render.outputs['Image'], solar_mask, location=(-1050, 40))
    cut_seed = _mix(group, 'Exposed cut-face emission', 'MULTIPLY',
                    solar_seed.outputs[0], cut_mask, location=(-820, -220))

    halo = _glare(group, 'Gentle whole-Sun Fog Glow', solar_seed.outputs[0],
                  threshold=0.30, strength=0.65, size=0.16, location=(-560, 230))
    cut_glow = _glare(group, 'Luminous cut faces | strong Fog Glow', cut_seed.outputs[0],
                      threshold=0.55, strength=6.0, size=0.95, location=(-560, -110))
    streak = _glare(group, 'Cut-face lens streaks | faint accent', cut_seed.outputs[0],
                    threshold=0.85, strength=1.0, size=0.16, location=(-560, -500))
    streak.inputs['Type'].default_value = 'Streaks'
    streak.inputs['Streaks'].default_value = 4
    streak.inputs['Streaks Angle'].default_value = 0.31
    streak.inputs['Iterations'].default_value = 2
    streak.inputs['Fade'].default_value = 0.76
    streak.inputs['Color Modulation'].default_value = 0.0

    bloom = _mix(group, 'Soft solar halo + cut-face glow', 'ADD',
                 halo.outputs['Glare'], cut_glow.outputs['Glare'], location=(-250, 170))
    combined = _mix(group, 'Bloom + 5% cut-face lens streaks', 'ADD',
                    bloom.outputs[0], streak.outputs['Glare'], factor=0.05,
                    location=(-30, 70))
    # Preserve the cut-face texture and narrow structural guide lines, while
    # allowing the full bloom to spill outside the emitting cut edge. Closing
    # small mask gaps prevents glare from filling the dark guide-line pixels.
    expanded = nodes.new('CompositorNodeDilateErode')
    expanded.name = 'Cut-face protection | close 3 px guide gaps'
    expanded.location = (-780, -780)
    expanded.inputs['Type'].default_value = 'Steps'
    expanded.inputs['Size'].default_value = 3
    links.new(cut_mask, expanded.inputs['Mask'])
    softened = nodes.new('CompositorNodeBlur')
    softened.name = 'Cut-face protection | soften 2 px edge transition'
    softened.location = (-560, -780)
    softened.inputs['Type'].default_value = 'Gaussian'
    softened.inputs['Size'].default_value = (2.0, 2.0)
    links.new(expanded.outputs['Mask'], softened.inputs['Image'])
    attenuation = _math(group, 'SUBTRACT', 1.0,
                         _math(group, 'MULTIPLY', softened.outputs['Image'], .964))
    attenuation.node.name = 'Cut-face glare allowance | one minus protection'
    attenuation.node.location = (-80, -640)
    attenuation.node.inputs[1].links[0].from_node.location = (-300, -640)
    protected = _mix(group, 'Glare spill | 3.6% inside face, full outside', 'MULTIPLY',
                     combined.outputs[0], attenuation, location=(200, -30))
    # Add optical light in HDR. SCREEN can darken channels above one, precisely
    # where the stronger emission should be producing brighter highlights.
    final = _mix(group, 'Glare | additive HDR optical light', 'ADD',
                 render.outputs['Image'], protected.outputs[0], factor=controller['glare_strength'],
                 location=(440, 300))
    driver = final.inputs[0].driver_add('default_value').driver
    driver.type = 'SCRIPTED'
    variable = driver.variables.new()
    variable.name = 'strength'
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id = controller
    variable.targets[0].data_path = '["glare_strength"]'
    driver.expression = 'min(max(strength, 0.0), 1.0)'

    bypass = nodes.new('CompositorNodeSwitch')
    bypass.name = 'Zero strength | original HDR emission without optical glare'
    bypass.location = (700, 300)
    bypass.inputs['Switch'].default_value = controller['glare_strength'] > 0.0
    bypass_driver = bypass.inputs['Switch'].driver_add('default_value').driver
    bypass_driver.type = 'SCRIPTED'
    variable = bypass_driver.variables.new()
    variable.name = 'strength'
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id = controller
    variable.targets[0].data_path = '["glare_strength"]'
    bypass_driver.expression = 'strength > 0.0'
    links.new(render.outputs['Image'], bypass.inputs['Off'])
    links.new(final.outputs[0], bypass.inputs['On'])
    display_safe = _highlight_shoulder(group, bypass.outputs[0])
    alpha = nodes.new('CompositorNodeSetAlpha')
    alpha.name = 'Retain original render alpha'
    alpha.location = (2250, 300)
    alpha.inputs['Type'].default_value = 'Replace Alpha'
    links.new(display_safe, alpha.inputs['Image'])
    links.new(render.outputs['Alpha'], alpha.inputs['Alpha'])
    output = nodes.new('NodeGroupOutput')
    output.location = (2490, 300)
    links.new(alpha.outputs[0], output.inputs['Image'])
    group['glare_model'] = ('Illustrative Blender Fog Glow from HDR solar emission, '
                            'with a stronger separate material-index cut-face seed.')
    group['equation'] = ('RGBout = RGB + strength * (1-.964*soft_dilated_cut_mask) '
                         '* (0.65*solar_halo + 6.0*cut_glow + 0.05*cut_streaks)')
    group['highlight_shoulder'] = ('For Y>.70 or max(RGB)>1: Ysoft=min(Y,.70)+.28*(1-exp(-max(Y-.70,0)/.28)); '
                                   'rescale RGB by Ysoft/Y, then mix the minimum neutral Ysoft so max(RGB)<=1.')
    group['zero_strength'] = ('Zero disables optical glare. HDR highlights retain the display shoulder; '
                              'pixels below the .70 luminance knee and in gamut bypass the shoulder exactly. '
                              'Original alpha is preserved.')
    return group
