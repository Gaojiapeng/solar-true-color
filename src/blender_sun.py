"""Create and render an editable Blender Sun, using the prepared Model S data.

Run with Blender's Python, not system Python. No third-party add-ons required.
All interior colors and brightness follow one editable node group; the Sun
is an actual closed 7/8 sphere mesh with three flat exposed quarter discs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def emission_material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = tuple(color)+(1.,)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Color'].default_value = (*color, 1)
    emit.inputs['Strength'].default_value = 1
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(emit.outputs[0], out.inputs['Surface'])
    return mat


def image_from_array(name, values):
    """Pack native float data so the .blend does not need external textures."""
    height, width = values.shape[:2]
    image = bpy.data.images.new(name, width, height, alpha=True, float_buffer=True)
    image.colorspace_settings.name = 'Non-Color'
    image.file_format = 'OPEN_EXR'
    image.pixels.foreach_set(np.ascontiguousarray(values, dtype=np.float32).ravel())
    image.pack()
    return image


def math_node(tree, operation, a, b=None, label=''):
    node = tree.nodes.new('ShaderNodeMath')
    node.operation, node.label = operation, label
    for index, value in enumerate((a, b)):
        if value is None:
            continue
        if hasattr(value, 'node'):
            tree.links.new(value, node.inputs[index])
        else:
            node.inputs[index].default_value = value
    return node.outputs[0]


def vector_node(tree, operation, a, b=None):
    node = tree.nodes.new('ShaderNodeVectorMath')
    node.operation = operation
    for index, value in enumerate((a, b)):
        if value is not None:
            if hasattr(value, 'node'):
                tree.links.new(value, node.inputs[index])
            else:
                node.inputs[index].default_value = value
    return node.outputs['Value' if operation in ('DOT_PRODUCT', 'LENGTH', 'DISTANCE') else 'Vector']


def scale_vector(tree, color, scale):
    node = tree.nodes.new('ShaderNodeVectorMath'); node.operation = 'SCALE'
    tree.links.new(color, node.inputs[0]); tree.links.new(scale, node.inputs['Scale'])
    return node.outputs['Vector']


def driven_value(tree, controller, prop):
    node = tree.nodes.new('ShaderNodeValue'); node.name=prop; node.label=prop
    node.outputs[0].default_value=controller[prop]
    driver=node.outputs[0].driver_add('default_value').driver;driver.type='AVERAGE'
    variable=driver.variables.new();variable.name='setting';variable.type='SINGLE_PROP'
    variable.targets[0].id=controller;variable.targets[0].data_path='["'+prop+'"]'
    return node.outputs[0]


def add_plasma_texture(tree, position, controller, *, surface=False):
    """Illustrative scalar detail; no independent RGB tint or fabricated data."""
    prop='surface_texture' if surface else 'interior_texture'
    strength=driven_value(tree,controller,prop)
    fine=tree.nodes.new('ShaderNodeTexNoise');fine.name='Illustrative fine plasma texture'
    fine.noise_dimensions='3D';fine.inputs['Scale'].default_value=165. if surface else 130.
    fine.inputs['Detail'].default_value=2.;fine.inputs['Roughness'].default_value=.65
    tree.links.new(position,fine.inputs['Vector'])
    cells=tree.nodes.new('ShaderNodeTexVoronoi');cells.name='Illustrative granules' if surface else 'Illustrative convection structure'
    cells.voronoi_dimensions='3D';cells.feature='DISTANCE_TO_EDGE'
    cells.inputs['Scale'].default_value=105. if surface else 40.
    tree.links.new(position,cells.inputs['Vector'])
    edge=math_node(tree,'MINIMUM',math_node(tree,'MULTIPLY',cells.outputs['Distance'],7.),1.)
    fine_signal=math_node(tree,'SUBTRACT',math_node(tree,'MULTIPLY',fine.outputs['Fac'],2.),1.)
    cell_signal=math_node(tree,'SUBTRACT',math_node(tree,'MULTIPLY',edge,2.),1.)
    signal=math_node(tree,'ADD',math_node(tree,'MULTIPLY',cell_signal,.7),
                     math_node(tree,'MULTIPLY',fine_signal,.3))
    if not surface:
        radius=vector_node(tree,'LENGTH',position)
        convective=math_node(tree,'GREATER_THAN',radius,.713)
        amplitude=math_node(tree,'ADD',1.,math_node(tree,'MULTIPLY',convective,2.))
        strength=math_node(tree,'MULTIPLY',strength,amplitude)
    return math_node(tree,'ADD',1.,math_node(tree,'MULTIPLY',signal,strength))


def brightness_group(controller):
    group = bpy.data.node_groups.new('Solar brightness | shared global curve', 'ShaderNodeTree')
    group.interface.new_socket(name='Source linear radiance', in_out='INPUT', socket_type='NodeSocketColor')
    detail_socket=group.interface.new_socket(name='Illustrative detail', in_out='INPUT', socket_type='NodeSocketFloat')
    detail_socket.default_value=1.;detail_socket.min_value=0.;detail_socket.max_value=2.
    gain_socket=group.interface.new_socket(name='Emission gain', in_out='INPUT', socket_type='NodeSocketFloat')
    gain_socket.default_value=1.;gain_socket.min_value=0.;gain_socket.max_value=20.
    group.interface.new_socket(name='Emission', in_out='OUTPUT', socket_type='NodeSocketShader')
    group.interface.new_socket(name='Display linear RGB', in_out='OUTPUT', socket_type='NodeSocketColor')
    nodes, links = group.nodes, group.links
    source = nodes.new('NodeGroupInput'); source.location=(-1100, 200)
    output = nodes.new('NodeGroupOutput'); output.location=(950, 200)
    controls = {}
    for i, prop in enumerate(('compression', 'reference_luminance', 'display_peak', 'exposure_ev', 'display_power')):
        value = nodes.new('ShaderNodeValue'); value.name=prop; value.label=prop
        value.location=(-1100, -100-i*100)
        value.outputs[0].default_value = controller[prop]
        driver = value.outputs[0].driver_add('default_value').driver
        driver.type = 'AVERAGE'
        variable = driver.variables.new(); variable.name='setting'; variable.type='SINGLE_PROP'
        variable.targets[0].id = controller; variable.targets[0].data_path='["'+prop+'"]'
        controls[prop] = value.outputs[0]
    color = source.outputs[0]
    y = vector_node(group, 'DOT_PRODUCT', color, (.2126,.7152,.0722))
    exposure = math_node(group, 'POWER', 2., controls['exposure_ev'])
    normalized = math_node(group, 'DIVIDE', math_node(group, 'MULTIPLY', y, exposure), controls['reference_luminance'])
    normalized = math_node(group, 'MINIMUM', normalized, 1.)
    compressed = math_node(group, 'LOGARITHM', math_node(group, 'ADD',
                    math_node(group, 'MULTIPLY', normalized, controls['compression']), 1.), math.e)
    denominator = math_node(group, 'LOGARITHM', math_node(group, 'ADD', controls['compression'], 1.), math.e)
    normalized_display=math_node(group,'DIVIDE',compressed,denominator)
    softened=math_node(group,'POWER',normalized_display,controls['display_power'],label='Gentle extra contrast compression')
    display_y = math_node(group, 'MULTIPLY', controls['display_peak'], softened)
    ratio = math_node(group, 'DIVIDE', display_y, math_node(group, 'MAXIMUM', y, 1e-12))
    mapped = scale_vector(group, color, ratio)
    mapped = scale_vector(group,mapped,source.outputs['Illustrative detail'])
    separate = nodes.new('ShaderNodeSeparateXYZ'); links.new(mapped, separate.inputs[0])
    peak = math_node(group, 'MAXIMUM', separate.outputs[0], separate.outputs[1])
    peak = math_node(group, 'MAXIMUM', peak, separate.outputs[2])
    peak = math_node(group, 'MAXIMUM', peak, 1.)
    mapped = scale_vector(group, mapped, math_node(group, 'DIVIDE', 1., peak))
    emission = nodes.new('ShaderNodeEmission'); emission.location=(720,200)
    links.new(mapped, emission.inputs['Color'])
    links.new(source.outputs['Emission gain'],emission.inputs['Strength'])
    links.new(emission.outputs[0], output.inputs['Emission'])
    links.new(mapped, output.inputs['Display linear RGB'])
    # Arrange arithmetic nodes for inspection without changing the equations.
    work = [n for n in nodes if n.type in ('MATH', 'VECT_MATH', 'SEPXYZ')]
    for i,node in enumerate(work): node.location=(-850+(i%6)*230, 500-(i//6)*190)
    group['equation'] = 'Yout=P*[ln(1+c*min(Y*2^EV/ref,1))/ln(1+c)]^q; RGBout=RGB*Yout/Y; optional scalar texture; scalar gamut limit'
    return group


def radiance_material(name, group):
    mat = bpy.data.materials.new(name); mat.use_nodes=True
    tree = mat.node_tree; tree.nodes.clear()
    geometry = tree.nodes.new('ShaderNodeNewGeometry'); geometry.location=(-1000,100)
    shared = tree.nodes.new('ShaderNodeGroup'); shared.node_tree=group; shared.location=(380,100)
    out = tree.nodes.new('ShaderNodeOutputMaterial'); out.location=(630,100)
    tree.links.new(shared.outputs['Emission'], out.inputs['Surface'])
    return mat, tree, geometry.outputs['Position'], shared.inputs[0]


def thermal_material(data, group, controller):
    # Quadratic radial sampling resolves the very thin outer thermal gradient.
    t = np.linspace(0,1,8192)
    radii = 1-(1-t)**2
    rgba = np.ones((1,len(t),4),np.float32)
    for i in range(3): rgba[0,:,i]=np.interp(radii,data['radius'],data['rgb'][:,i])
    image = image_from_array('Model S | linear radiance lookup',rgba)
    mat,tree,position,destination = radiance_material('Interior | thermal emission',group)
    r = vector_node(tree,'LENGTH',position)
    r = math_node(tree,'MINIMUM',r,1.)
    t_socket = math_node(tree,'SUBTRACT',1.,math_node(tree,'SQRT',math_node(tree,'SUBTRACT',1.,r)))
    coord = math_node(tree,'ADD', math_node(tree,'MULTIPLY',t_socket,8191/8192),.5/8192)
    xy=tree.nodes.new('ShaderNodeCombineXYZ'); tree.links.new(coord,xy.inputs['X']);xy.inputs['Y'].default_value=.5
    tex=tree.nodes.new('ShaderNodeTexImage'); tex.image=image;tex.interpolation='Linear';tex.extension='EXTEND'
    tree.links.new(xy.outputs[0],tex.inputs['Vector']);tree.links.new(tex.outputs['Color'],destination)
    tree.links.new(add_plasma_texture(tree,position,controller),destination.node.inputs['Illustrative detail'])
    tree.links.new(driven_value(tree,controller,'solar_emission_gain'),destination.node.inputs['Emission gain'])
    mat.pass_index=1
    mat.diffuse_color=(.34,.45,.86,1.)
    return mat


def photosphere_material(data,group,controller):
    rgba=np.concatenate((data['surface'],data['surface_mask'][...,None]),axis=-1)
    image=image_from_array('SDO HMI | observed hemisphere linear radiance',rgba[::-1])
    mat,tree,position,destination=radiance_material('Photosphere | HMI continuum',group)
    u=vector_node(tree,'DOT_PRODUCT',position,tuple(data['right']))
    v=vector_node(tree,'DOT_PRODUCT',position,tuple(data['up']))
    front=vector_node(tree,'DOT_PRODUCT',position,tuple(data['toward']))
    xy=tree.nodes.new('ShaderNodeCombineXYZ')
    for socket,value in (('X',u),('Y',v)):
        tree.links.new(math_node(tree,'ADD',math_node(tree,'MULTIPLY',value,.5),.5),xy.inputs[socket])
    tex=tree.nodes.new('ShaderNodeTexImage');tex.image=image;tex.interpolation='Linear';tex.extension='CLIP'
    tree.links.new(xy.outputs[0],tex.inputs['Vector'])
    valid=math_node(tree,'MULTIPLY',math_node(tree,'GREATER_THAN',front,0.),tex.outputs['Alpha'])
    mix=tree.nodes.new('ShaderNodeMixRGB');mix.blend_type='MIX'
    tree.links.new(valid,mix.inputs[0]);mix.inputs[1].default_value=(*data['rgb'][-1],1.)
    tree.links.new(tex.outputs['Color'],mix.inputs[2]);tree.links.new(mix.outputs[0],destination)
    detail=add_plasma_texture(tree,position,controller,surface=True)
    # The global curve strongly suppresses observed surface contrast. Recover a
    # restrained amount for this illustration, without changing feature positions
    # or chromaticity. Setting surface_texture to zero removes both enhancements.
    hmi_y=vector_node(tree,'DOT_PRODUCT',mix.outputs[0],(.2126,.7152,.0722))
    surface_y=float(np.dot(data['rgb'][-1],(.2126,.7152,.0722)))
    hmi_relative=math_node(tree,'DIVIDE',hmi_y,surface_y)
    hmi_signal=math_node(tree,'SUBTRACT',math_node(tree,'SQRT',hmi_relative),1.)
    hmi_gain=math_node(tree,'MULTIPLY',driven_value(tree,controller,'surface_texture'),3.)
    hmi_detail=math_node(tree,'ADD',1.,math_node(tree,'MULTIPLY',hmi_signal,hmi_gain))
    tree.links.new(math_node(tree,'MULTIPLY',detail,hmi_detail),destination.node.inputs['Illustrative detail'])
    tree.links.new(driven_value(tree,controller,'solar_emission_gain'),destination.node.inputs['Emission gain'])
    mat.pass_index=2
    mat.diffuse_color=(.45,.43,.40,1.)
    return mat


def solar_mesh(interior_mat,surface_mat):
    vertices,faces,materials=[],[],[]
    cache={}
    def vertex(p):
        key=tuple(round(float(v),9) for v in p)
        if key not in cache: cache[key]=len(vertices);vertices.append(key)
        return cache[key]
    def face(points,material):
        indices=list(dict.fromkeys(vertex(p) for p in points))
        if len(indices)>=3: faces.append(indices);materials.append(material)
    ntheta,nphi=128,256
    def sphere(theta,phi):
        return (math.sin(theta)*math.cos(phi),math.sin(theta)*math.sin(phi),math.cos(theta))
    for i in range(ntheta):
        t0,t1=i*math.pi/ntheta,(i+1)*math.pi/ntheta
        for j in range(nphi):
            if i<ntheta//2 and j<nphi//4: continue
            p0,p1=j*2*math.pi/nphi,(j+1)*2*math.pi/nphi
            face([sphere(t0,p0),sphere(t1,p0),sphere(t1,p1),sphere(t0,p1)],1)
    rings=sorted(set(np.r_[np.linspace(0,1,65),.25,.713]))
    for axis in range(3):
        other=[i for i in range(3) if i!=axis]
        def point(radius,angle):
            p=[0.,0.,0.];p[other[0]]=radius*math.cos(angle);p[other[1]]=radius*math.sin(angle);return p
        for lo,hi in zip(rings[:-1],rings[1:]):
            for j in range(64):
                a0,a1=j*math.pi/128,(j+1)*math.pi/128
                points=[point(lo,a0),point(hi,a0),point(hi,a1),point(lo,a1)]
                if axis==1:points.reverse()
                face(points,0)
    mesh=bpy.data.meshes.new('Closed octant cutaway geometry');mesh.from_pydata(vertices,[],faces);mesh.update()
    obj=bpy.data.objects.new('Sun | exact 7/8 solid',mesh);bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(interior_mat);obj.data.materials.append(surface_mat)
    for polygon,index in zip(mesh.polygons,materials):polygon.material_index=index;polygon.use_smooth=index==1
    obj['removed_volume_fraction']=.125;obj['solar_radius_km']=696000.
    obj.pass_index=1
    obj['cut_faces']='x=0, y=0, z=0; positive quadrants; true sphere volume cut'
    for name,lo,hi in [('Core',0.,.25),('Radiative zone',.25,.713),('Convection zone',.713,1.)]:
        group=obj.vertex_groups.new(name=name)
        ids=[i for i,p in enumerate(vertices) if lo-1e-8<=np.linalg.norm(p)<=hi+1e-8]
        group.add(ids,1.,'REPLACE')
    return obj


def curve(name,points,material,collection,width=.0015):
    shape=bpy.data.curves.new(name,'CURVE');shape.dimensions='3D';shape.resolution_u=1
    spline=shape.splines.new('POLY');spline.points.add(len(points)-1)
    for p,co in zip(spline.points,points):p.co=(*co,1.)
    shape.bevel_depth=width;shape.bevel_resolution=2
    obj=bpy.data.objects.new(name,shape);collection.objects.link(obj);shape.materials.append(material)
    return obj


def guide_geometry(collection):
    dark=emission_material('Guide | dark ink',(.010,.018,.030))
    edge=emission_material('Guide | pale cut edges',(.38,.45,.58))
    for axis in range(3):
        other=[i for i in range(3) if i!=axis]
        for radius in (.25,.713,1.):
            points=[]
            for angle in np.linspace(0,math.pi/2,161):
                p=[0.,0.,0.];p[axis]=.0012;p[other[0]]=radius*math.cos(angle);p[other[1]]=radius*math.sin(angle);points.append(p)
            curve('Boundary %.3f on axis %d'%(radius,axis),points,edge if radius==1 else dark,
                  collection,.0012 if radius==1 else .0020)
        p=[0.,0.,0.];p[axis]=1.
        curve('Exposed cut seam '+str(axis),[(.001,.001,.001),p],edge,collection,.001)


def setup_camera(scene,data):
    right,up,toward=(Vector(data[k]) for k in ('right','up','toward'))
    camera_data=bpy.data.cameras.new('Solar cutaway camera');camera_data.type='ORTHO';camera_data.ortho_scale=5.3
    camera=bpy.data.objects.new('Camera | annotated overview',camera_data);scene.collection.objects.link(camera)
    target=right*.73
    camera.location=target+toward*6.
    camera.rotation_euler=Matrix((right,up,toward)).transposed().to_euler()
    scene.camera=camera
    return right,up,toward,camera


def typography(scene,axes,sources,data,group,comparison):
    right,up,toward,camera=axes
    collection=bpy.data.collections.new('Annotations | hide for clean render');scene.collection.children.link(collection)
    fg=emission_material('Type | white',(.73,.79,.88));muted=emission_material('Type | secondary',(.28,.36,.47))
    accent=emission_material('Type | ice',(.37,.52,.75));warm=emission_material('Type | pink emission',(.60,.24,.34))
    rot=Matrix((right,up,toward)).transposed().to_euler()
    # Blender's built-in font travels with the scene on every platform.
    font=None
    def world(x,y,z=.01):return right*x+up*y+toward*z
    def text(name,body,x,y,size=.040,mat=fg):
        block=bpy.data.curves.new(name,'FONT');block.body=body;block.size=size*1.5;block.space_line=1.25
        if font is not None:block.font=font
        block.align_x='LEFT';block.resolution_u=8
        obj=bpy.data.objects.new(name,block);collection.objects.link(obj)
        obj.location=world(x,y);obj.rotation_euler=rot;block.materials.append(mat)
        return obj
    text('Title','THE SUN',-1.55,1.50,.150)
    text('Subtitle','LIGHT, TEXTURE & STRUCTURE',-1.55,1.37,.035,accent)
    text('Octant','1/8 CUTAWAY',1.50,1.53,.062)
    text('Scale note','Physical radii  |  luminous cut faces',1.50,1.44,.028,muted)
    cards=[('01  CORE','0 - 0.25 solar radii','15.67 million K at the center',1.08),
           ('02  RADIATIVE ZONE','0.25 - 0.713 solar radii','Energy carried by radiative diffusion',.84),
           ('03  CONVECTION ZONE','0.713 - 1.0 solar radii','Heat transported by plasma motion',.60),
           ('04  TACHOCLINE','Near 0.713 solar radii','Thin rotational shear region',.36),
           ('05  PHOTOSPHERE','Near 1.0 solar radii','5,778 K  |  HMI + illustrative granulation',.12)]
    for title,sub,detail,y in cards:
        text(title,title,1.50,y,.050)
        text(title+' range',sub,1.50,y-.063,.032,accent)
        text(title+' note',detail,1.50,y-.116,.028,muted)
    # Number markers are diagrams, never false layer hues in the Sun material.
    points=[(0.,.10,.07),(0.,.43,.19),(0.,.79,.30),(.64,0.,.31),(-.30,.55,.7794)]
    marker_mat=emission_material('Guide | label badges',(.012,.020,.033))
    for n,p in enumerate(points,1):
        vec=Vector(p);x,y=vec.dot(right),vec.dot(up)
        # Place annotations in front of the sphere, so curved surfaces do not
        # cut through the glyphs. Orthographic projection preserves anchors.
        vertices=[world(x+.033*math.cos(a),y+.033*math.sin(a),2.)
                  for a in np.linspace(0,2*math.pi,33)[:-1]]
        mesh=bpy.data.meshes.new('Badge '+str(n));mesh.from_pydata(vertices,[],[list(range(32))]);mesh.update()
        badge=bpy.data.objects.new('Layer badge '+str(n),mesh);collection.objects.link(badge);mesh.materials.append(marker_mat)
        obj=text('Layer marker '+str(n),str(n),x-.012,y-.018,.046,fg)
        obj.location=world(x-.012,y-.018,2.003)
    text('Brightness heading','CORE / SURFACE BRIGHTNESS',1.50,-.24,.039,accent)
    for label,x,source_rgb in [('CORE CENTER',1.77,data['rgb'][0]),('PHOTOSPHERE',2.53,data['rgb'][-1])]:
        mat,tree,position,destination=radiance_material('Comparison | '+label,group)
        fixed=tree.nodes.new('ShaderNodeCombineXYZ')
        for i,value in enumerate(source_rgb):fixed.inputs[i].default_value=float(value)
        tree.links.new(fixed.outputs[0],destination)
        vertices=[world(x+.115*math.cos(a),-.46+.115*math.sin(a),2.)
                  for a in np.linspace(0,2*math.pi,129)[:-1]]
        mesh=bpy.data.meshes.new('Equal-area brightness swatch');mesh.from_pydata(vertices,[],[list(range(128))]);mesh.update()
        obj=bpy.data.objects.new('Comparison swatch | '+label,mesh);collection.objects.link(obj);mesh.materials.append(mat)
        text(label+' swatch',label,x-.205,-.665,.030,muted)
    text('Intrinsic contrast','Modeled visible luminance: about 55,000 : 1',1.50,-.81,.035,fg)
    text('Displayed contrast',f"Reference luminance: {comparison['displayed_ratio']:.2f} : 1",1.50,-.925,.048,accent)
    text('Curve explanation','Log + gentle power scaling (0.60)',1.50,-1.01,.030,muted)
    text('Swatch qualification','Equal-area swatches before emission boost, texture and glare.',1.50,-1.085,.026,muted)
    text('Emission note','Sun illustration: 2.5x emission + cut-face optical glare.',1.50,-1.16,.029,accent)
    text('Atmosphere heading','WHITE-LIGHT CORONA',1.50,-1.30,.035,accent)
    text('Atmosphere caveat','Faint white streamers, enhanced gently for visibility.',1.50,-1.37,.029,muted)
    text('Readme','Visible spectral color: Model S + CIE 1931. The interior is a hypothetical cutaway, with illustrative plasma texture.',-1.55,-1.53,.030,muted)
    text('Source note','Emission is boosted for display. Glare and highlight softening produce pale blue-white light; spectral source data is retained.',-1.55,-1.605,.028,muted)
    curve('Scale line',[world(-1.18,-1.285),world(-.68,-1.285)],muted,collection,.001)
    text('Scale','0.5 solar radius',-1.09,-1.35,.028,muted)
    return collection


def write_readme(sources):
    body='''SOLAR CUTAWAY - BLENDER SCENE

The Sun is a closed three-dimensional sphere with exactly its positive xyz
octant removed. There are three perpendicular exposed quarter-disc faces.
Core / radiative / convection boundaries use physical radii .25 and .713.

BRIGHTNESS
Select the object "Solar brightness controls". In Object > Custom Properties,
edit compression, reference_luminance, display_peak, exposure_ev, display_power,
surface_texture, interior_texture, corona_strength, solar_emission_gain and
glare_strength.
Every solar material uses the same driven log + power node group. The default
power of 0.60 gently scales contrast beyond logarithmic compression: the
center/model-photosphere ratio is about 55,000:1 in visible thermal radiance
and about 1.98:1 in reference display luminance (swatches before effects).
The source brightness is visible spectral radiance, NOT bolometric T^4 power.

The Sun illustration has 2.5x emission after the reference curve. Blender's
compositor uses a separate cut-face material pass for stronger Fog Glow and
faint streaks, with gentler glow from the photosphere. A highlight shoulder
softens HDR luminance and reduces out-of-gamut highlight saturation toward
pale blue-white. The illustrated highlights therefore differ from the
unaltered spectral chromaticity in the reference swatches.

Texture is illustrative scalar detail, preserving local RGB proportions.
Surface detail also gently recovers HMI contrast suppressed by the global
curve; the positions of observed features remain unchanged.
The white corona is a separate optically thin emissive display illustration;
it does not imply calibrated coronal photometry. Glare adds soft optical bloom
and faint streaks only from the solar object, excluding annotation sources.
Use solar_emission_gain=1, surface_texture=0, interior_texture=0,
corona_strength=0 and glare_strength=0
to inspect the bare display model. The reference PNG is also exported with
all these effects disabled. Reducing display_power lifts dimmer material
further; 1.0 restores the simple log curve. The core remains brighter.

Keep Color Management at Standard / None / Exposure 0 / Gamma 1. The shader
already performs the global luminance transform before sRGB display encoding.
AgX or Filmic would apply an additional transform and change the presentation.

VIEWING
Numpad 0 enters the camera. Use Material Preview with Scene World or Rendered
view to see emission; Solid view uses viewport swatches only. F12 renders.
Hide "Annotations | hide for clean render" and "Layer guides | annotations"
to view the clean presentation. All images and effect modules are packed.

The HMI image is projected onto only its observed hemisphere. The source disk
mean is anchored to the model photosphere for display, not calibrated as an
absolute broadband spectrum. The far side has illustrative granulation but
no inferred observed sunspots. Model S is spherically symmetric, not an
actual observed 3D solar interior. The visible corona is nearly white
scattered light; its hot gas is not colored as a hot blackbody.
'''
    bpy.data.texts.new('READ ME | solar brightness and controls').write(body)
    bpy.data.texts.new('SOURCE PROVENANCE.json').write(json.dumps(sources,indent=2))
    bpy.data.texts.new('BUILD SCRIPT.py').write(Path(__file__).read_text(encoding='utf-8'))
    for filename in ('blender_corona.py','blender_glare.py','blender_display.py'):
        bpy.data.texts.new(filename).write((Path(__file__).parent/filename).read_text(encoding='utf-8'))


def save_preview(scene, source_path, target_path):
    """Keep full 16-bit renders; export compact sRGB previews for the app."""
    image=bpy.data.images.load(str(source_path),check_existing=False)
    width,height=image.size
    scale=min(1.,1600/max(width,height))
    if scale<1.:image.scale(round(width*scale),round(height*scale))
    scene.render.image_settings.color_depth='8'
    image.save_render(str(target_path),scene=scene)
    scene.render.image_settings.color_depth='16'
    bpy.data.images.remove(image)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',default=str(ROOT/'assets'))
    parser.add_argument('--output-dir',default=str(ROOT/'output'))
    parser.add_argument('--device',choices=('AUTO','CPU','GPU'),default='AUTO')
    parser.add_argument('--resolution',type=int,default=2400)
    parser.add_argument('--samples',type=int,default=96)
    parser.add_argument('--no-render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    data_root=Path(args.data_dir).expanduser()
    if not data_root.is_absolute():data_root=ROOT/data_root
    output=Path(args.output_dir).expanduser()
    if not output.is_absolute():output=ROOT/output
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    (output/'cache').mkdir(exist_ok=True)
    os.environ.setdefault('OPTIX_CACHE_PATH',str(output/'cache'))
    data=np.load(data_root/'solar_blender_data.npz',allow_pickle=False)
    sources=json.loads((data_root/'solar_blender_sources.json').read_text(encoding='utf-8'))
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.context.preferences.filepaths.save_version=0
    scene=bpy.context.scene;scene.name='Solar octant cutaway | spectral brightness'
    scene.world.use_nodes=True;scene.world.node_tree.nodes.get('Background').inputs[0].default_value=(.003,.006,.011,1.)
    scene.world.node_tree.nodes.get('Background').inputs[1].default_value=1.
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    scene.view_settings.exposure=0.;scene.view_settings.gamma=1.;scene.display_settings.display_device='sRGB'
    scene.render.engine='CYCLES';scene.cycles.samples=args.samples;scene.cycles.use_denoising=True
    scene.cycles.device='CPU'
    if args.device!='CPU':
        try:
            preferences=bpy.context.preferences.addons['cycles'].preferences
            preferences.compute_device_type='OPTIX';preferences.get_devices()
            available=[device for device in preferences.devices if device.type=='OPTIX']
            if not available:raise RuntimeError('No OptiX device detected')
            for device in preferences.devices:device.use=device in available
            scene.cycles.device='GPU'
        except Exception as error:
            if args.device=='GPU':raise RuntimeError('Requested OptiX GPU is unavailable; use --device CPU or AUTO') from error
            print('GPU unavailable; using CPU:',error)
    scene.render.resolution_x=args.resolution;scene.render.resolution_y=round(args.resolution*2/3)
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA';scene.render.image_settings.color_depth='16'
    scene.render.film_transparent=False
    controller=bpy.data.objects.new('Solar brightness controls',None);scene.collection.objects.link(controller)
    for prop,value,bounds,description in (
        ('compression',1e7,(1.,1e12),'One global log compression; larger values reveal dimmer structures.'),
        ('reference_luminance',60000.,(1.,1e8),'Fixed visible radiance reference; core is about 55,182.'),
        ('display_peak',.40,(.001,.45),'Shared display-linear Y ceiling; .40 leaves texture and glare headroom.'),
        ('exposure_ev',0.,(-20.,20.),'Exposure in stops before the shared compression curve.'),
        ('display_power',.60,(.1,2.),'Additional gentle contrast scaling; below1 reveals dim material, 1 is simple log.'),
        ('surface_texture',.14,(0.,.4),'Illustrative granulation and restrained HMI contrast recovery; zero retains only shared-curve HMI intensity.'),
        ('interior_texture',.04,(0.,.15),'Illustrative plasma grain; convection receives three times this amplitude.'),
        ('corona_strength',.025,(0.,.10),'Separately scaled illustrative white-light corona.'),
        ('solar_emission_gain',2.5,(1.,10.),'Sun emission after the reference curve; HDR light seeds cut-face glare. Swatches retain gain 1.'),
        ('glare_strength',.35,(0.,1.),'Cut-face optical glare with a softer solar halo; zero disables added glare.')):
        controller[prop]=value;controller.id_properties_ui(prop).update(min=bounds[0],max=bounds[1],description=description)
    controller.empty_display_type='PLAIN_AXES';controller.empty_display_size=.2;controller.hide_render=True
    from src.blender_display import brightness_comparison
    from src.blender_corona import create_corona
    from src.blender_glare import setup_glare
    comparison=brightness_comparison(data['rgb'][0],data['rgb'][-1])
    presentation={'display_controls':{key:controller[key] for key in controller.keys()},
                  'brightness_comparison':comparison,
                  'comparison_scope':'Center / model photosphere; reference display luminance before emission boost, texture, corona, glare and highlight softening.',
                  'emission':'Sun materials emit 2.5 times the reference display RGB; comparison swatches retain gain 1.',
                  'texture':'Illustrative scalar granulation/plasma structure with gentle HMI contrast recovery; not a recovered physical 3D field.',
                  'corona':'White, optically thin 3D emissive illustration with separately scaled brightness.',
                  'glare':'Dedicated cut-face Fog Glow and faint streaks, gentler solar halo, then a soft HDR highlight shoulder; annotation sources excluded.',
                  'reference_image':'solar_blender_reference.png: emission gain 1, no texture, atmosphere, annotations or compositor effects.',
                  'camera_reference':{'ortho_scale':3.05,'target':[0.,0.,0.]}}
    sources['presentation']=presentation
    sources['atmosphere']=presentation['corona']
    (output/'solar_blender_presentation.json').write_text(json.dumps(presentation,indent=2),encoding='utf-8')
    (output/'solar_blender_sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
    group=brightness_group(controller)
    solar_mesh(thermal_material(data,group,controller),photosphere_material(data,group,controller))
    corona=create_corona(scene,controller,data)
    guides=bpy.data.collections.new('Layer guides | annotations');scene.collection.children.link(guides);guide_geometry(guides)
    axes=setup_camera(scene,data);annotation=typography(scene,axes,sources,data,group,comparison)
    setup_glare(scene,controller)
    write_readme(sources)
    bpy.ops.file.pack_all()
    # Useful starting view in an interactive Blender window.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.shading.type='MATERIAL'
                area.spaces.active.shading.use_scene_world=True
                area.spaces.active.overlay.show_overlays=False
            elif area.type=='PROPERTIES': area.spaces.active.context='OBJECT'
    bpy.ops.object.select_all(action='DESELECT');controller.select_set(True);bpy.context.view_layer.objects.active=controller
    # The saved scene stays portable when its folder is cloned or moved.
    scene.render.filepath='//solar_blender_annotated.png'
    bpy.ops.wm.save_as_mainfile(filepath=str(output/'solar_cutaway.blend'))
    if not args.no_render:
        bpy.ops.render.render(write_still=True)
        save_preview(scene,output/'solar_blender_annotated.png',output/'solar_blender_annotated_preview.png')
        annotation.hide_render=True;guides.hide_render=True
        # A centered square portrait uses the exact same solar shader and
        # brightness settings, with the explanatory overlays hidden.
        axes[3].location=axes[2]*6.
        axes[3].data.ortho_scale=3.05
        scene.render.resolution_y=scene.render.resolution_x
        scene.render.filepath=str(output/'solar_blender_clean.png')
        bpy.ops.render.render(write_still=True)
        save_preview(scene,output/'solar_blender_clean.png',output/'solar_blender_clean_preview.png')
        # Keep an independent numeric reference with every illustrative effect
        # disabled, while retaining the exact log + power display transform.
        corona.hide_render=True
        scene.render.use_compositing=False;scene.cycles.use_denoising=False
        controller['surface_texture']=0.;controller['interior_texture']=0.;controller['solar_emission_gain']=1.
        controller.update_tag();scene.frame_set(scene.frame_current);bpy.context.view_layer.update()
        scene.render.filepath=str(output/'solar_blender_reference.png')
        bpy.ops.render.render(write_still=True)
        annotation.hide_render=False;guides.hide_render=False
    print('SOLAR_BLEND_COMPLETE',output/'solar_cutaway.blend')


if __name__=='__main__':main()
