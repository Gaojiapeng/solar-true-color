"""Validate the delivered Blender Sun without changing the scene.

Run with Blender, for example::

    blender --background solar_cutaway.blend --python-exit-code 1 \
        --python src/verify_blender_sun.py

Checks concern the resulting solid, source assets, and rendering pipeline,
not the implementation of the scene-generation script. A JSON report is
written beside the loaded blend file, including when validation fails.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bmesh
import bpy


SOLID_NAME = "Sun | exact 7/8 solid"
GROUP_NAME = "Solar brightness | shared global curve"
PROFILE_NAME = "Model S | linear radiance lookup"
MATERIAL_NAMES = ("Interior | thermal emission", "Photosphere | HMI continuum")
GEOMETRY_EPSILON = 2e-6
RELATIVE_TESSELLATION_TOLERANCE = 0.003


class SceneValidation:
    def __init__(self):
        self.checks = []
        self.metrics = {}

    def check(self, name, passed, details=None):
        record = {"name": name, "passed": bool(passed)}
        if details is not None:
            record["details"] = details
        self.checks.append(record)
        return bool(passed)

    def geometry(self):
        obj = bpy.data.objects.get(SOLID_NAME)
        if not self.check("Named Sun mesh exists", obj is not None and obj.type == "MESH"):
            return
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        evaluated_mesh = evaluated.to_mesh()
        bm = bmesh.new()
        try:
            bm.from_mesh(evaluated_mesh)
            bm.transform(evaluated.matrix_world)
            bm.normal_update()
            self.metrics["geometry"] = stats = {
                "vertices": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces)
            }
            if not self.check("Solid has nonempty geometry", bool(bm.verts and bm.faces)):
                return
            bad_edges = sum(not edge.is_manifold for edge in bm.edges)
            reversed_edges = sum(edge.is_manifold and not edge.is_contiguous for edge in bm.edges)
            loose_vertices = sum(not vertex.link_faces for vertex in bm.verts)
            self.check("Every edge has exactly two incident faces", bad_edges == 0,
                       {"nonmanifold_edges": bad_edges})
            self.check("Face winding is consistent", reversed_edges == 0,
                       {"inconsistently_wound_edges": reversed_edges})
            self.check("No loose vertices", loose_vertices == 0)
            self.check("All faces have positive area", all(face.calc_area() > 1e-14 for face in bm.faces))

            unseen = set(bm.verts)
            components = 0
            while unseen:
                components += 1
                stack = [unseen.pop()]
                while stack:
                    vertex = stack.pop()
                    for edge in vertex.link_edges:
                        other = edge.other_vert(vertex)
                        if other in unseen:
                            unseen.remove(other)
                            stack.append(other)
            self.check("Sun is one connected solid", components == 1,
                       {"connected_components": components})

            target_volume = (7 / 8) * (4 * math.pi / 3)
            volume = bm.calc_volume(signed=True)
            volume_relative_error = abs(volume - target_volume) / target_volume
            radii = [vertex.co.length for vertex in bm.verts]
            stats.update(signed_volume=volume, target_volume=target_volume,
                         volume_relative_error=volume_relative_error,
                         min_radius=min(radii), max_radius=max(radii))
            self.check("Positive volume equals seven eighths of unit sphere",
                       volume > 0 and volume_relative_error <= RELATIVE_TESSELLATION_TOLERANCE,
                       {"relative_error": volume_relative_error,
                        "tolerance": RELATIVE_TESSELLATION_TOLERANCE})
            self.check("All solid vertices lie within one solar radius",
                       max(radii) <= 1 + GEOMETRY_EPSILON)
            self.check("The cutaway reaches the solar center", min(radii) <= GEOMETRY_EPSILON)

            slots = [slot.material.name if slot.material else None for slot in obj.material_slots]
            self.check("Required physical materials are assigned",
                       all(name in slots for name in MATERIAL_NAMES), {"material_slots": slots})
            cut_area = [0.0, 0.0, 0.0]
            cut_count = [0, 0, 0]
            wrong_cut_normals = 0
            positive_octant_faces = 0
            unexpected_faces = 0
            wrong_materials = 0
            surface_count = 0
            for face in bm.faces:
                coordinates = [vertex.co for vertex in face.verts]
                cut_axis = None
                for axis in range(3):
                    if (all(abs(point[axis]) <= GEOMETRY_EPSILON for point in coordinates)
                            and all(point[other] >= -GEOMETRY_EPSILON
                                    for point in coordinates for other in range(3) if other != axis)):
                        cut_axis = axis
                        break
                material_name = slots[face.material_index] if face.material_index < len(slots) else None
                if cut_axis is not None:
                    cut_area[cut_axis] += face.calc_area()
                    cut_count[cut_axis] += 1
                    wrong_cut_normals += face.normal[cut_axis] < 1 - GEOMETRY_EPSILON
                    wrong_materials += material_name != MATERIAL_NAMES[0]
                else:
                    surface_count += 1
                    spherical = all(abs(point.length - 1) <= GEOMETRY_EPSILON for point in coordinates)
                    unexpected_faces += not spherical
                    centroid = face.calc_center_median()
                    positive_octant_faces += all(value > GEOMETRY_EPSILON for value in centroid)
                    wrong_materials += material_name != MATERIAL_NAMES[1]
            stats.update(cut_face_counts=cut_count, cut_face_areas=cut_area,
                         spherical_face_count=surface_count)
            self.check("All three cuts are quarter-discs",
                       all(count > 0 for count in cut_count)
                       and all(abs(area - math.pi / 4) / (math.pi / 4)
                               <= RELATIVE_TESSELLATION_TOLERANCE for area in cut_area),
                       {"areas": cut_area, "target_area_each": math.pi / 4})
            self.check("Cut normals point into the removed positive octant", wrong_cut_normals == 0,
                       {"incorrect_cut_normals": wrong_cut_normals})
            self.check("No spherical patches remain in the removed octant", positive_octant_faces == 0,
                       {"positive_octant_surface_faces": positive_octant_faces})
            self.check("Other physical faces lie on the unit sphere", unexpected_faces == 0 and surface_count > 0,
                       {"unexpected_faces": unexpected_faces})
            self.check("Interior and photosphere use their respective materials", wrong_materials == 0,
                       {"incorrect_material_faces": wrong_materials})
        finally:
            bm.free()
            evaluated.to_mesh_clear()

    @staticmethod
    def reachable_nodes(tree, starts, visited=None):
        """Trace actual upstream links, including the contents of node groups."""
        visited = set() if visited is None else visited
        found = []
        stack = list(starts)
        while stack:
            node = stack.pop()
            key = (tree.as_pointer(), node.as_pointer())
            if key in visited:
                continue
            visited.add(key)
            found.append(node)
            for socket in node.inputs:
                stack.extend(link.from_node for link in socket.links)
            if node.type == "GROUP" and node.node_tree:
                outputs = [item for item in node.node_tree.nodes
                           if item.type == "GROUP_OUTPUT" and item.is_active_output]
                found.extend(SceneValidation.reachable_nodes(node.node_tree, outputs, visited))
        return found

    def render_pipeline(self):
        scene = bpy.context.scene
        view = scene.view_settings
        actual_view = {"view_transform": view.view_transform, "look": view.look,
                       "exposure": view.exposure, "gamma": view.gamma,
                       "display_device": scene.display_settings.display_device}
        self.metrics["color_management"] = actual_view
        self.check("Display encoding uses Standard after the explicit compositor shoulder",
                   view.view_transform == "Standard" and view.look == "None"
                   and abs(view.exposure) < 1e-8 and abs(view.gamma - 1) < 1e-8
                   and scene.display_settings.display_device == "sRGB", actual_view)

        controller = bpy.data.objects.get("Solar brightness controls")
        if self.check("Brightness controller exists", controller is not None):
            expected = {"compression": 1e7, "reference_luminance": 60000.0,
                        "display_peak": 0.40, "exposure_ev": 0.0, "display_power": 0.60,
                        "surface_texture": 0.14, "interior_texture": 0.04,
                        "glare_strength": 0.35, "corona_strength": 0.025,
                        "solar_emission_gain": 2.5}
            actual = {key: controller.get(key) for key in expected}
            self.metrics["brightness_controls"] = actual
            self.check("Shared brightness controls have the documented defaults",
                       all(isinstance(actual[key], (int, float))
                           and math.isclose(actual[key], value, rel_tol=1e-7, abs_tol=1e-8)
                           for key, value in expected.items()), actual)

        group = bpy.data.node_groups.get(GROUP_NAME)
        self.check("Shared global brightness group exists", group is not None)
        if group is not None:
            power = group.nodes.get('display_power')
            self.check("Extra compression has an exposed value control", power is not None)
            if power is not None:
                output_nodes = [node for node in group.nodes
                                if node.type == 'GROUP_OUTPUT' and node.is_active_output]
                upstream = self.reachable_nodes(group, output_nodes)
                self.check("Extra power acts in the active shared brightness path",
                           any(link.to_node in upstream and link.to_node.type == 'MATH'
                               and link.to_node.operation == 'POWER'
                               and link.to_socket == link.to_node.inputs[1]
                               for link in power.outputs[0].links))
                drivers = group.animation_data.drivers if group.animation_data else []
                path = power.outputs[0].path_from_id('default_value')
                control_drivers = [driver for driver in drivers if driver.data_path == path]
                self.check("Extra power is driven by the user's display_power property",
                           any(target.id == controller and target.data_path == '["display_power"]'
                               for fcurve in control_drivers
                               for variable in fcurve.driver.variables
                               for target in variable.targets))

        atmosphere = bpy.data.collections.get('Corona | illustrative visible-light atmosphere')
        self.check("Illustrative corona can be hidden independently",
                   atmosphere is not None and len(atmosphere.all_objects) > 0
                   and bpy.data.objects.get(SOLID_NAME) not in list(atmosphere.all_objects))
        self.check("Illustrated scene enables compositor effects", scene.render.use_compositing)
        for name in MATERIAL_NAMES:
            material = bpy.data.materials.get(name)
            if not self.check(f"{name}: node material exists",
                              material is not None and material.use_nodes and material.node_tree is not None):
                continue
            outputs = [node for node in material.node_tree.nodes
                       if node.type == "OUTPUT_MATERIAL" and node.is_active_output]
            surface_starts = [link.from_node for node in outputs
                              for link in node.inputs["Surface"].links]
            reachable = self.reachable_nodes(material.node_tree, surface_starts)
            self.check(f"{name}: output uses the shared global curve",
                       any(node.type == "GROUP" and node.node_tree == group for node in reachable))
            self.check(f"{name}: output uses self-emission",
                       any(node.bl_idname == "ShaderNodeEmission" for node in reachable))
            self.check(f"{name}: output has no directional surface shader",
                       not any(node.bl_idname in {"ShaderNodeBsdfDiffuse", "ShaderNodeBsdfPrincipled",
                                                 "ShaderNodeBsdfGlossy", "ShaderNodeBsdfAnisotropic"}
                               for node in reachable))

    def packed_assets(self):
        profile = bpy.data.images.get(PROFILE_NAME)
        if self.check("Model S radiance lookup is embedded", profile is not None):
            packed = bool(profile.packed_file) or len(profile.packed_files) > 0
            self.metrics["profile_image"] = {"size": list(profile.size),
                                             "is_float": profile.is_float,
                                             "packed": packed,
                                             "color_space": profile.colorspace_settings.name}
            self.check("Source lookup retains floating point radiance", profile.is_float)
            self.check("Source lookup has packed pixels", packed)
            self.check("Source lookup has a resolved radial profile", max(profile.size) >= 256)
            self.check("Source lookup is not interpreted as gamma-encoded sRGB",
                       profile.colorspace_settings.name not in {"sRGB", "sRGB Encoded Rec.709"})
        external = [image.name for image in bpy.data.images
                    if image.source == "FILE" and image.users > 0
                    and not image.packed_file and len(image.packed_files) == 0]
        self.check("All referenced file images are packed", not external, {"unpacked_images": external})

    def run(self):
        for name, method in (("Geometry", self.geometry), ("Render pipeline", self.render_pipeline),
                             ("Packed assets", self.packed_assets)):
            try:
                method()
            except Exception as error:
                self.check(f"{name} inspection completed", False,
                           {"exception": type(error).__name__, "message": str(error)})
        failures = [check for check in self.checks if not check["passed"]]
        report = {"passed": not failures, "blender_version": bpy.app.version_string,
                  "blend_file": Path(bpy.data.filepath).name, "checks": self.checks,
                  "metrics": self.metrics, "failed_checks": len(failures)}
        destination = Path(bpy.data.filepath).resolve().parent / "solar_blender_validation.json"
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Solar Blender validation: {len(self.checks) - len(failures)}/{len(self.checks)} checks passed")
        print(f"Validation report: {destination}")
        if failures:
            raise RuntimeError("Solar scene validation failed: " + "; ".join(item["name"] for item in failures))
        return report


if __name__ == "__main__":
    SceneValidation().run()
