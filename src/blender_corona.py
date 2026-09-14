"""Illustrative, optically thin visible-light corona for the Blender Sun.

This is a three-dimensional emission volume, not a billboard or a coronal
blackbody. Its separately scaled neutral-white brightness represents scattered
photospheric light schematically. It is not a reconstructed density map or a
measurement of the Sun's coronal radiance.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Vector


def _math(tree, operation, a, b=None, label=""):
    node = tree.nodes.new("ShaderNodeMath")
    node.operation = operation
    node.label = label
    for index, value in enumerate((a, b)):
        if value is None:
            continue
        if hasattr(value, "node"):
            tree.links.new(value, node.inputs[index])
        else:
            node.inputs[index].default_value = value
    return node.outputs[0]


def _vector(tree, operation, a, b=None, label=""):
    node = tree.nodes.new("ShaderNodeVectorMath")
    node.operation = operation
    node.label = label
    for index, value in enumerate((a, b)):
        if value is None:
            continue
        if hasattr(value, "node"):
            tree.links.new(value, node.inputs[index])
        else:
            node.inputs[index].default_value = value
    return node.outputs["Value" if operation in ("LENGTH", "DOT_PRODUCT") else "Vector"]


def _gain(tree, controller):
    value = tree.nodes.new("ShaderNodeValue")
    value.name = "corona_strength"
    value.label = "Independent illustrative corona scale"
    value.outputs[0].default_value = controller["corona_strength"]
    driver = value.outputs[0].driver_add("default_value").driver
    driver.type = "AVERAGE"
    variable = driver.variables.new()
    variable.name = "corona_scale"
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = controller
    variable.targets[0].data_path = '["corona_strength"]'
    return value.outputs[0]


def create_corona(scene, controller, basis):
    """Add a cutaway, tapered corona extending to 1.42 solar radii.

    ``basis`` supplies ``right``, ``up`` and ``toward`` vectors from the initial
    camera. These only choose the long-streamer directions; the finished field
    is three-dimensional and remains inspectable from other viewpoints.
    ``controller['corona_strength']`` drives its independent emission gain.
    """
    if "corona_strength" not in controller:
        controller["corona_strength"] = 0.025
        controller.id_properties_ui("corona_strength").update(
            min=0.0, max=0.15, soft_max=0.08,
            description="Illustrative visible-light corona gain; independent of the interior brightness comparison.",
        )
    collection = bpy.data.collections.new("Corona | illustrative visible-light atmosphere")
    scene.collection.children.link(collection)
    collection["interpretation"] = (
        "Optically thin neutral-white emission surrogate for scattered visible sunlight; "
        "density structure and brightness are illustrative and separately scaled."
    )

    # A single small volume domain is inexpensive and does not alter the closed
    # 7/8 solar mesh or its surface normals. The shader clips the domain into an
    # actual hollow 3D atmosphere and removes the same positive-XYZ octant.
    extent = 1.42
    vertices = [(x, y, z) for x in (-extent, extent)
                for y in (-extent, extent) for z in (-extent, extent)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new("Corona | volume domain")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Corona | tapered white streamers in 3D", mesh)
    collection.objects.link(obj)
    obj.display_type = "WIRE"
    obj["radial_extent_Rsun"] = extent
    obj["removed_octant"] = "Positive x, positive y, positive z, matching the Sun cutaway"
    obj["brightness"] = "Independent illustrative gain, not physical coronal/core radiance ratio"

    material = bpy.data.materials.new("Corona | neutral-white optically thin glow")
    material.use_nodes = True
    material.diffuse_color = (0.94, 0.97, 1.0, 0.05)
    tree = material.node_tree
    tree.nodes.clear()
    coordinates = tree.nodes.new("ShaderNodeTexCoord")
    coordinates.label = "Local 3D position in solar radii"
    position = coordinates.outputs["Object"]
    radius = _vector(tree, "LENGTH", position)
    direction = _vector(tree, "NORMALIZE", position)
    height = _math(tree, "MAXIMUM", _math(tree, "SUBTRACT", radius, 1.0), 0.0)

    # The denser base falls rapidly; a weaker anisotropic component persists
    # farther out. No absorption/scattering is needed for this faint display
    # surrogate, so the volume cannot shadow or dim the interior.
    base = _math(tree, "MULTIPLY", 0.85, _math(
        tree, "EXPONENT", _math(tree, "MULTIPLY", height, -1.0 / 0.038)))
    right, up, toward = (Vector(basis[key]).normalized() for key in ("right", "up", "toward"))
    streamers = None
    # Asymmetry avoids an undifferentiated ring. Cones taper angularly while the
    # radial falloff and terminal fade soften their ends without visible caps.
    for angle_deg, width_power, amplitude, depth in (
        (6, 48, 7.80, 0.035), (34, 105, 4.50, -0.04),
        (146, 70, 5.80, 0.015), (181, 42, 7.30, -0.025),
        (211, 95, 3.80, 0.045), (325, 88, 5.00, -0.035),
    ):
        angle = math.radians(angle_deg)
        axis = (right * math.cos(angle) + up * math.sin(angle) + toward * depth).normalized()
        cone = _math(tree, "POWER", _math(
            tree, "MAXIMUM", _vector(tree, "DOT_PRODUCT", direction, tuple(axis)), 0.0), width_power)
        cone = _math(tree, "MULTIPLY", cone, amplitude)
        streamers = cone if streamers is None else _math(tree, "ADD", streamers, cone)
    tail = _math(tree, "MULTIPLY", streamers, _math(
        tree, "EXPONENT", _math(tree, "MULTIPLY", height, -1.0 / 0.155)))

    # Keep filament modulation coherent through the optically thin volume:
    # otherwise many unrelated 3D noise samples integrate into a smooth fog.
    # A fixed cylindrical angular coordinate makes radial strands distinct
    # while their density and streamer envelopes remain three-dimensional.
    projection = tree.nodes.new("ShaderNodeCombineXYZ")
    tree.links.new(_vector(tree, "DOT_PRODUCT", position, tuple(right)), projection.inputs["X"])
    tree.links.new(_vector(tree, "DOT_PRODUCT", position, tuple(up)), projection.inputs["Y"])
    angular_coordinate = _vector(tree, "NORMALIZE", projection.outputs[0])
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.label = "Coherent radial filaments within 3D streamers"
    tree.links.new(angular_coordinate, noise.inputs["Vector"])
    noise.inputs["Scale"].default_value = 67.0
    noise.inputs["Detail"].default_value = 1.4
    noise.inputs["Roughness"].default_value = 0.67
    contrast = _math(tree, "MAXIMUM", 0.0, _math(tree, "MULTIPLY", 2.0,
        _math(tree, "SUBTRACT", noise.outputs["Fac"], 0.20)))
    filaments = _math(tree, "ADD", 0.13, _math(tree, "MULTIPLY", 2.7,
        _math(tree, "POWER", contrast, 3.0)))
    filaments = _math(tree, "MINIMUM", filaments, 2.0,
                      label="Cap rare bright strands below the photosphere")
    density = _math(tree, "MULTIPLY", _math(tree, "ADD", base, tail), filaments)
    outside_sun = _math(tree, "GREATER_THAN", radius, 1.002)
    fade = _math(tree, "MINIMUM", 1.0, _math(tree, "MAXIMUM", 0.0,
        _math(tree, "DIVIDE", _math(tree, "SUBTRACT", extent, radius), 0.12)))
    fade = _math(tree, "MULTIPLY", fade, fade)
    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(position, separate.inputs[0])
    positive = [_math(tree, "GREATER_THAN", separate.outputs[i], 0.0) for i in range(3)]
    removed = _math(tree, "MULTIPLY", positive[0], _math(tree, "MULTIPLY", positive[1], positive[2]))
    retained = _math(tree, "SUBTRACT", 1.0, removed)
    density = _math(tree, "MULTIPLY", density, _math(
        tree, "MULTIPLY", outside_sun, _math(tree, "MULTIPLY", fade, retained)))
    strength = _math(tree, "MULTIPLY", density, _gain(tree, controller))
    volume = tree.nodes.new("ShaderNodeVolumePrincipled")
    volume.label = "Neutral-white scattered-light display surrogate"
    volume.inputs["Density"].default_value = 0.0
    volume.inputs["Emission Color"].default_value = (0.94, 0.97, 1.0, 1.0)
    volume.inputs["Blackbody Intensity"].default_value = 0.0
    tree.links.new(strength, volume.inputs["Emission Strength"])
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(volume.outputs["Volume"], output.inputs["Volume"])
    obj.data.materials.append(material)
    for i, node in enumerate(tree.nodes):
        node.location = ((i % 10) * 220, -(i // 10) * 180)
    material["color_basis"] = "Nearly neutral white: visible light scattered by coronal electrons; illustrative geometry."
    material["density_profile"] = "Thin exponentially fading base + 6 anisotropic tapered radial cones + angular filaments."
    return collection
