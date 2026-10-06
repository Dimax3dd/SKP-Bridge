# <pep8-80 compliant>

__author__ = 'Martijn Berger'
__license__ = "GPL"

'''
This program is free software; you can redistribute it and
or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 3
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, see http://www.gnu.org/licenses
'''

import math
import os
import tempfile
import time
import traceback
from types import SimpleNamespace

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import AddonPreferences, Operator
from bpy_extras.io_utils import ImportHelper, unpack_list
from mathutils import Matrix, Vector

from . import compat_reader as sketchup
from .SKPutil import *

bl_info = {
    "name": "SKP Bridge",
    "author": "Martijn Berger, Sanjay Mehta, Arindam Mondal",
    "version": (1, 0, 8),
    "blender": (5, 2, 0),
    "description": "Import of native SketchUp (.skp) files",
    # "warning": "Very early preview",
    "wiki_url": "https://github.com/martijnberger/pyslapi",
    "tracker_url": "",
    "category": "Import-Export",
    "location": "File > Import"
}


class SketchupAddonPreferences(AddonPreferences):

    bl_idname = __name__

    camera_far_plane: FloatProperty(
        name="Camera Clip Ends At :",
        default=250,
        unit='LENGTH'
    )

    def draw(self, context):

        layout = self.layout
        layout.label(text="- Basic Import Options -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "camera_far_plane")
        layout = self.layout
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "draw_bounds")


def skp_log(*args):

    if len(args) > 0:
        print('SKP | ' + ' '.join(['%s' % a for a in args]))


class SceneImporter():
    def __init__(self):

        self.filepath = '/tmp/untitled.skp'
        self.name_mapping = {}
        self.component_meshes = {}
        self.scene = None
        self.layers_skip = []

    def set_filename(self, filename):

        self.filepath = filename
        self.basepath, self.skp_filename = os.path.split(self.filepath)
        return self  # allow chaining

    def load(self, context, **options):
        """load a sketchup file"""

        self.context = context
        self.reuse_material = options['reuse_material']
        self.split_materials = options['split_materials']
        self.component_collections = options['component_collections']
        self.merge_mode = options.get('merge_mode', 'NONE')
        self.track_layers = self.merge_mode == 'LAYER'
        self.collections = {}
        self.render_engine = options['render_engine']
        self.component_stats = defaultdict(list)
        self.component_skip = proxy_dict()
        self.component_depth = proxy_dict()
        self.group_written = {}
        ren_res_x = context.scene.render.resolution_x
        ren_res_y = context.scene.render.resolution_y
        self.aspect_ratio = ren_res_x / ren_res_y

        skp_log(f'Importing: {self.filepath}')

        addon_name = __name__.split('.')[0]
        self.prefs = context.preferences.addons[addon_name].preferences

        _time_main = time.time()

        try:
            self.skp_model = sketchup.Model.from_file(
                self.filepath, cameras=options['scenes_as_camera'] or options['import_camera'])
        except Exception as e:
            skp_log(f'Error reading input file: {self.filepath}')
            skp_log(e)
            raise

        if not self.layers_skip:
            self.layers_skip = [
                l for l in self.skp_model.layers if not l.visible
            ]

        skp_log('Skipping Layers ... ')

        for l in sorted([l.name for l in self.layers_skip]):
            skp_log(l)

        self.skp_components = proxy_dict(
            self.skp_model.component_definition_as_dict)

        skp_log(f'Parsed in {(time.time() - _time_main):.4f} sec.')

        if options['scenes_as_camera']:
            for s in self.skp_model.scenes:
                self.write_camera(s.camera, s.name)

        if options['import_camera']:
            if self.scene:
                active_cam = self.write_camera(self.scene.camera,
                                               name=self.scene.name)
                context.scene.camera = active_cam
            else:
                active_cam = self.write_camera(self.skp_model.camera)
                context.scene.camera = active_cam

        _t1 = time.time()
        self.write_materials(self.skp_model.materials)

        skp_log(f'Materials imported in {(time.time() - _t1):.4f} sec.')

        _t1 = time.time()
        self.root_collection = bpy.data.collections.new(os.path.splitext(self.skp_filename)[0])
        context.collection.children.link(self.root_collection)
        scale = max(context.scene.unit_settings.scale_length, 1e-12)
        self.write_entities(self.skp_model.entities, "Sketchup", Matrix.Scale(1.0 / scale, 4))

        skp_log(f'Entities imported in {(time.time() - _t1):.4f} sec.')
        skp_log('Finished importing in %.4f sec.\n' %
                (time.time() - _time_main))

        return {'FINISHED'}

    def write_materials(self, materials):
        self.materials = {}
        self.materials_scales = {}
        default = bpy.data.materials.get('Material') if self.reuse_material else None
        if default is None:
            default = bpy.data.materials.new('Material')
            default.diffuse_color = (.8, .8, .8, 1.0)
            default.use_nodes = True
            default.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = default.diffuse_color
        self.materials['Material'] = default
        for mat in materials:
            name, tex = mat.name, mat.texture
            self.materials_scales[name] = tex.dimensions[2:] if tex else (1.0, 1.0)
            bmat = bpy.data.materials.get(name) if self.reuse_material else None
            if bmat is None:
                bmat = bpy.data.materials.new(name)
                r, g, b, a = mat.color
                rgba = ((r / 255.0) ** 2.2, (g / 255.0) ** 2.2,
                        (b / 255.0) ** 2.2, a / 255.0)
                bmat.diffuse_color = rgba
                bmat.use_nodes = True
                bsdf = bmat.node_tree.nodes.get('Principled BSDF')
                bsdf.inputs['Base Color'].default_value = rgba
                bsdf.inputs['Alpha'].default_value = rgba[3]
                if tex:
                    with tempfile.TemporaryDirectory(prefix='skp_texture_') as directory:
                        path = os.path.join(directory, tex.name)
                        tex.write(path)
                        img = bpy.data.images.load(path, check_existing=False)
                        img.pack()
                    node = bmat.node_tree.nodes.new('ShaderNodeTexImage')
                    node.image = img
                    bmat.node_tree.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
                    if rgba[3] < 1.0:
                        multiply = bmat.node_tree.nodes.new('ShaderNodeMath')
                        multiply.operation = 'MULTIPLY'
                        multiply.inputs[1].default_value = rgba[3]
                        bmat.node_tree.links.new(node.outputs['Alpha'], multiply.inputs[0])
                        bmat.node_tree.links.new(multiply.outputs[0], bsdf.inputs['Alpha'])
                    else:
                        bmat.node_tree.links.new(node.outputs['Alpha'], bsdf.inputs['Alpha'])
            self.materials[name] = bmat

    def write_mesh_data(self,
                        entities=None,
                        name="",
                        default_material='Material'):

        mesh_key = (getattr(entities, 'cache_key', id(entities)), default_material)
        if mesh_key in self.component_meshes:
            return self.component_meshes[mesh_key]
        verts = []
        loops_vert_idx = []
        mat_index = []
        smooth = []
        mats = keep_offset()
        seen = keep_offset()
        uv_list = []
        alpha = False
        uvs_used = False

        for f in entities.faces:
            f.st_scale = (1.0, 1.0)
            if f.material:
                mat_number = mats[f.material.name]
            else:
                mat_number = mats[default_material]
                if default_material != 'Material':
                    try:
                        f.st_scale = self.materials_scales[default_material]
                    except KeyError as _e:
                        pass
            
            vs, tri, uvs = f.tessfaces
            num_loops = 0

            mapping = {}
            for i, (v, uv) in enumerate(zip(vs, uvs)):
                l = len(seen)
                mapping[i] = seen[v]
                if len(seen) > l:
                    verts.append(v)

            smooth_edge = False

            for edge in f.edges:
                if edge.GetSmooth() == True:
                    smooth_edge = True
                    break

            for face in tri:
                f0, f1, f2 = face[0], face[1], face[2]
                num_loops += 1

                if mapping[f2] == 0:
                    loops_vert_idx.extend([mapping[f2],
                                           mapping[f0],
                                           mapping[f1]])

                    uv_list.append((uvs[f2][0], uvs[f2][1],
                                    uvs[f0][0], uvs[f0][1],
                                    uvs[f1][0], uvs[f1][1]))

                else:
                    loops_vert_idx.extend([mapping[f0],
                                           mapping[f1],
                                           mapping[f2]])

                    uv_list.append((uvs[f0][0], uvs[f0][1],
                                    uvs[f1][0], uvs[f1][1],
                                    uvs[f2][0], uvs[f2][1]))

                smooth.append(smooth_edge)
                mat_index.append(mat_number)

        if len(verts) == 0:
            return None, False

        me = bpy.data.meshes.new(name)

        if len(mats) >= 1:
            mats_sorted = OrderedDict(sorted(mats.items(), key=lambda x: x[1]))
            for k in mats_sorted.keys():
                try:
                    bmat = self.materials[k]
                except KeyError as _e:
                    bmat = self.materials["Material"]
                me.materials.append(bmat)
                # if bmat.alpha < 1.0:
                #     alpha = True
                try:
                    if self.render_engine == 'CYCLES':
                        if 'Image Texture' in bmat.node_tree.nodes.keys():
                            uvs_used = True
                    else:
                        for ts in bmat.texture_slots:
                            if ts is not None and ts.texture_coords is not None:
                                uvs_used = True
                except AttributeError as _e:
                    uvs_used = False
        else:
            skp_log(f"WARNING: Object {name} has no material!")

        tri_faces = list(zip(*[iter(loops_vert_idx)] * 3))
        tri_face_count = len(tri_faces)

        loop_start = []
        i = 0
        for f in tri_faces:
            loop_start.append(i)
            i += len(f)

        loop_total = list(map(lambda f: len(f), tri_faces))

        me.vertices.add(len(verts))
        me.vertices.foreach_set("co", unpack_list(verts))

        me.loops.add(len(loops_vert_idx))
        me.loops.foreach_set("vertex_index", loops_vert_idx)

        me.polygons.add(tri_face_count)
        me.polygons.foreach_set("loop_start", loop_start)
        me.polygons.foreach_set("loop_total", loop_total)
        me.polygons.foreach_set("material_index", mat_index)
        me.polygons.foreach_set("use_smooth", smooth)

        if uv_list:
            k, l = 0, 0
            me.uv_layers.new()
            for i in range(len(tri_faces)):
                for j in range(3):
                    uv_cordinates = (uv_list[i][l], uv_list[i][l + 1])
                    me.uv_layers[0].data[k].uv = Vector(uv_cordinates)
                    k += 1
                    if j != 2:
                        l += 2
                    else:
                        l = 0

        me.update(calc_edges=True)
        me.validate()
        self.component_meshes[mesh_key] = me, alpha

        return me, alpha

    @staticmethod
    def _effective_layer_name(layer_name, inherited_layer=None):
        """Return the effective SketchUp Tag for nested geometry.

        SketchUp normally keeps component-definition geometry on Layer0
        (the default/untagged drawing layer) while the Component Instance or
        Group carries the meaningful Tag. Layer0 must therefore inherit the
        nearest non-default parent Tag. An explicitly assigned non-default
        Tag always overrides the inherited one.
        """
        default_layers = {'Layer0', 'Layer 0', 'Untagged', 'Untaged', ''}
        name = layer_name or 'Untagged'
        if name in default_layers and inherited_layer:
            return inherited_layer
        return name

    def write_entities(self, entities, name, parent_tranform,
                       default_material="Material", etype=None, collection=None, stack=(), layer_context=None):
        identity = id(entities)
        if identity in stack:
            raise RuntimeError('Recursive component reference: ' + name)
        stack = stack + (identity,)
        collection = collection or self.root_collection
        if etype == EntityType.component and self.component_collections:
            if name not in self.collections:
                child = bpy.data.collections.new(name)
                self.root_collection.children.link(child)
                self.collections[name] = child
            collection = self.collections[name]
        if self.split_materials or self.track_layers:
            buckets = defaultdict(list)
            for face in entities.faces:
                material = face.material.name if face.material else default_material
                layer_obj = getattr(face, 'layer', None)
                face_layer = (getattr(layer_obj, 'name', None) or (layer_obj if isinstance(layer_obj, str) else None) or 'Untagged')
                # SketchUp's default Layer0/Untagged is normally the internal
                # drawing layer of a component. The meaningful Tag belongs to
                # the containing instance/group. Inherit that Tag instead of
                # creating a separate Layer0 object.
                layer = self._effective_layer_name(face_layer, layer_context)
                key = (material, layer) if self.track_layers else material
                buckets[key].append(face)
            chunks = []
            for key, faces in buckets.items():
                if self.track_layers:
                    material, layer = key
                    chunk_name = name + ' | ' + material + ' | ' + layer
                    cache_key = (identity, material, layer, layer_context)
                else:
                    material, layer = key, None
                    chunk_name = name + ' | ' + material
                    cache_key = (identity, material)
                chunks.append((chunk_name, SimpleNamespace(faces=faces, cache_key=cache_key)))
        else:
            chunks = [(name, entities)]
        for mesh_name, chunk in chunks:
            me, alpha = self.write_mesh_data(chunk, mesh_name, default_material)
            if me:
                ob = bpy.data.objects.new(mesh_name, me)
                if self.track_layers:
                    face_layers = set()
                    for face in chunk.faces:
                        layer_obj = getattr(face, 'layer', None)
                        face_layer = (getattr(layer_obj, 'name', None) or (layer_obj if isinstance(layer_obj, str) else None) or 'Untagged')
                        face_layers.add(self._effective_layer_name(face_layer, layer_context))
                    ob['sketchup_layer'] = next(iter(face_layers)) if len(face_layers) == 1 else 'Mixed'
                ob.matrix_world = parent_tranform
                collection.objects.link(ob)
        for group in entities.groups:
            if group.hidden or group.layer in self.layers_skip:
                continue
            self.write_entities(group.entities, "G-" + group_safe_name(group.name),
                                parent_tranform @ Matrix(group.transform),
                                inherent_default_mat(group.material, default_material),
                                EntityType.group, collection, stack,
                                self._effective_layer_name(
                                    getattr(getattr(group, 'layer', None), 'name', None),
                                    layer_context))
        for instance in entities.instances:
            if instance.hidden or instance.layer in self.layers_skip:
                continue
            cdef = self.skp_components[instance.definition.name]
            self.write_entities(cdef.entities, cdef.name,
                                parent_tranform @ Matrix(instance.transform),
                                inherent_default_mat(instance.material, default_material),
                                EntityType.component, collection, stack,
                                self._effective_layer_name(
                                    getattr(getattr(instance, 'layer', None), 'name', None),
                                    layer_context))

    def write_camera(self, camera, name="Active Camera"):

        pos, target, up = camera.GetOrientation()
        scale = max(self.context.scene.unit_settings.scale_length, 1e-12)
        pos, target = Vector(pos) / scale, Vector(target) / scale
        bpy.ops.object.add(type='CAMERA', location=pos)
        ob = self.context.object
        ob.name = name

        z = (Vector(pos) - Vector(target))
        x = Vector(up).cross(z)
        y = z.cross(x)

        x.normalize()
        y.normalize()
        z.normalize()

        matrix = ob.matrix_world.copy()
        matrix.col[0] = x.resized(4)
        matrix.col[1] = y.resized(4)
        matrix.col[2] = z.resized(4)
        ob.matrix_world = matrix

        cam = ob.data
        aspect_ratio = camera.aspect_ratio
        fov = camera.fov
        if aspect_ratio == False:
            # skp_log(f"Camera:'{name}' uses dynamic/screen aspect ratio.")
            aspect_ratio = self.aspect_ratio
        if fov == False:
            skp_log(f"Camera:'{name}'' is in Orthographic Mode.")
            cam.type = 'ORTHO'
        else:
            cam.sensor_fit = 'VERTICAL'
            cam.angle = math.radians(fov)
        cam.clip_end = self.prefs.camera_far_plane
        cam.name = name
        return ob


class ImportSKP(Operator, ImportHelper):
    """Load a Trimble Sketchup SKP file"""

    bl_idname = "import_scene.skp_original_52"
    bl_label = "Import SKP"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".skp"

    filter_glob: StringProperty(
        default="*.skp",
        options={'HIDDEN'},
    )

    import_camera: BoolProperty(
        name="Last View In SketchUp As Camera View",
        description="Import last saved view in SketchUp as a Blender Camera.",
        default=False
    )

    reuse_material: BoolProperty(
        name="Use Existing Materials",
        description="Doesn't copy material IDs already in the Blender Scene.",
        default=True
    )

    split_materials: BoolProperty(
        name="Split by Materials", default=True,
        description="Separate materials within each component; no joining or Edit Mode")

    component_collections: BoolProperty(
        name="Collections for Components", default=True,
        description="Place component meshes into collections named after their definitions")

    scenes_as_camera: BoolProperty(
        name="Scene(s) As Camera(s)",
        description="Import SketchUp Scenes As Blender Camera.",
        default=False
    )

    merge_objects: BoolProperty(
        name="Merge Objects",
        description="Merge imported mesh objects after the SKP import",
        default=False
    )

    merge_mode: EnumProperty(
        name="Merge Mode",
        description="How imported mesh objects are grouped when merging",
        items=[
            ('ALL', "All Objects", "Merge everything into one mesh"),
            ('MATERIAL', "By Materials", "Create one merged mesh per material"),
            ('LAYER', "By Layers", "Create one merged mesh per SketchUp Layer/Tag"),
        ],
        default='ALL'
    )

    convert_quads: BoolProperty(
        name="Convert Triangles to Quads",
        description="Try to combine compatible adjacent triangles into quads after merging",
        default=False
    )

    cube_project_uv: BoolProperty(
        name="Cube Project UV",
        description="After merging, replace the UVs with Cube Projection using the specified UV scale",
        default=False
    )

    cube_project_uv_scale: FloatProperty(
        name="UV Scale",
        description="Cube Projection size / UV scale",
        default=1.0,
        min=0.001,
        max=1000.0,
        soft_min=0.01,
        soft_max=20.0,
        precision=3
    )

    pivot_base_center: BoolProperty(
        name="Pivot: Center at Base",
        description="After merging, place the object origin at the center of the bounding box on its lowest point",
        default=False
    )

    apply_rotation_scale: BoolProperty(
        name="Apply Rotation & Scale",
        description="After merging, apply the object's rotation and scale transforms without changing its location",
        default=False
    )

    auto_smooth: BoolProperty(
        name="Auto Smooth",
        description="After merging, apply Blender's Shade Auto Smooth using a 30 degree angle",
        default=False
    )

    limited_dissolve: BoolProperty(
        name="Limited Dissolve by Material",
        description="After merging and converting triangles to quads, run Limited Dissolve separately for each material",
        default=False
    )

    limited_dissolve_angle: FloatProperty(
        name="Max Angle",
        description="Maximum angle for Limited Dissolve",
        default=math.radians(0.1),
        min=0.0,
        max=math.radians(180.0),
        soft_min=0.0,
        soft_max=10.0,
        precision=3,
        unit='ROTATION'
    )

    def _set_pivot_base_center(self, ob):
        if not ob or ob.type != 'MESH' or not ob.data:
            return

        # Calculate the desired origin in world space: X/Y center of the
        # bounding box and its lowest Z point. The geometry is then shifted
        # in local space so the world-space geometry does not move.
        world_corners = [ob.matrix_world @ Vector(corner) for corner in ob.bound_box]
        min_x = min(v.x for v in world_corners)
        max_x = max(v.x for v in world_corners)
        min_y = min(v.y for v in world_corners)
        max_y = max(v.y for v in world_corners)
        min_z = min(v.z for v in world_corners)

        target_world = Vector((
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            min_z,
        ))

        target_local = ob.matrix_world.inverted() @ target_world
        ob.data.transform(Matrix.Translation(-target_local))
        ob.matrix_world.translation = target_world
        ob.data.update()

    def _cleanup_merged_source_meshes(self, before_meshes):
        """Remove orphan Mesh datablocks created by the SKP import and consumed by join().

        Blender removes the source objects during Object Join, but their Mesh
        datablocks can remain orphaned in bpy.data.meshes. Keep pre-existing
        meshes untouched and remove only newly created meshes with no users.
        """
        removed = 0
        for mesh in list(bpy.data.meshes):
            if mesh in before_meshes:
                continue
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
                removed += 1
        return removed

    def _limited_dissolve_by_material(self, context, merged):
        """Run Blender's native Limited Dissolve exactly like a manual
        Material-slot Select -> Limited Dissolve workflow.

        Each material slot is activated, its faces are selected with
        bpy.ops.object.material_slot_select(), and then the native
        dissolve_limited operator is called with Delimit=Normal and
        All Boundaries disabled.
        """
        if not self.limited_dissolve or not merged:
            return

        angle = self.limited_dissolve_angle

        for ob in merged:
            if not ob or ob.type != 'MESH' or not ob.data:
                continue

            mesh = ob.data
            material_count = len(mesh.materials)

            bpy.ops.object.select_all(action='DESELECT')
            ob.select_set(True)
            context.view_layer.objects.active = ob

            try:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_mode(type='FACE')
                bpy.ops.mesh.select_all(action='DESELECT')

                if material_count == 0:
                    bpy.ops.mesh.select_all(action='SELECT')
                    bpy.ops.mesh.dissolve_limited(
                        angle_limit=angle,
                        use_dissolve_boundaries=False,
                        delimit={'NORMAL'},
                    )
                else:
                    # Match Blender's manual Material Slot -> Select workflow.
                    # Setting the active slot in OBJECT mode and calling the
                    # native material-slot selector in EDIT mode is important;
                    # directly toggling polygon.select does not always reproduce
                    # the same BMesh selection state as the UI operator.
                    bpy.ops.object.mode_set(mode='OBJECT')
                    for mat_index in range(material_count):
                        ob.active_material_index = mat_index
                        bpy.ops.object.mode_set(mode='EDIT')
                        bpy.ops.mesh.select_mode(type='FACE')
                        bpy.ops.mesh.select_all(action='DESELECT')
                        bpy.ops.object.material_slot_select()
                        bpy.ops.mesh.dissolve_limited(
                            angle_limit=angle,
                            use_dissolve_boundaries=False,
                            delimit={'NORMAL'},
                        )
                        bpy.ops.object.mode_set(mode='OBJECT')

                bpy.ops.object.mode_set(mode='OBJECT')
                mesh.update()
            except Exception:
                if ob.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                raise

    def _merge_imported(self, context, imported_objects, target_collection):
        base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        if self.merge_mode == 'ALL':
            groups = [('ALL', imported_objects)]
        elif self.merge_mode == 'MATERIAL':
            grouped = {}
            for ob in imported_objects:
                mats = tuple(m.name for m in ob.data.materials) or ('No Material',)
                grouped.setdefault(mats, []).append(ob)
            groups = list(grouped.items())
        else:
            grouped = {}
            for ob in imported_objects:
                layer = ob.get('sketchup_layer', 'Untagged')
                grouped.setdefault(layer, []).append(ob)
            groups = list(grouped.items())

        merged = []
        for key, objects in groups:
            if not objects:
                continue
            bpy.ops.object.select_all(action='DESELECT')
            for ob in objects:
                ob.select_set(True)
            active = objects[0]
            context.view_layer.objects.active = active
            bpy.ops.object.join()
            if self.merge_mode == 'ALL':
                name = base_name
            elif self.merge_mode == 'MATERIAL':
                label = key[0] if isinstance(key, tuple) else str(key)
                name = f"{base_name} | {label}"
            else:
                name = f"{base_name} | {key}"
            active.name = name
            active.data.name = name
            if 'sketchup_layer' in active:
                del active['sketchup_layer']
            for col in list(active.users_collection):
                if col != target_collection:
                    col.objects.unlink(active)
            if active.name not in target_collection.objects:
                target_collection.objects.link(active)
            merged.append(active)

        if self.convert_quads and merged:
            bpy.ops.object.select_all(action='DESELECT')
            for ob in merged:
                ob.select_set(True)
            context.view_layer.objects.active = merged[0]
            for ob in merged:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    bpy.ops.mesh.tris_convert_to_quads(use_uvs=True, use_vcols=True, use_seam=True, use_sharp=True, use_materials=True)
                except TypeError:
                    try:
                        bpy.ops.mesh.tris_convert_to_quads()
                    except Exception:
                        pass
                bpy.ops.object.mode_set(mode='OBJECT')
                ob.data.update()

        if self.limited_dissolve and merged:
            self._limited_dissolve_by_material(context, merged)

        if self.cube_project_uv and merged:
            bpy.ops.object.select_all(action='DESELECT')
            for ob in merged:
                ob.select_set(True)
            context.view_layer.objects.active = merged[0]
            for ob in merged:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    bpy.ops.uv.cube_project(cube_size=self.cube_project_uv_scale, correct_aspect=True, clip_to_bounds=False, scale_to_bounds=False)
                except TypeError:
                    # Compatibility fallback for Blender builds with a reduced operator signature.
                    bpy.ops.uv.cube_project(cube_size=self.cube_project_uv_scale)
                bpy.ops.object.mode_set(mode='OBJECT')
                ob.data.update()

        if self.apply_rotation_scale and merged:
            bpy.ops.object.select_all(action='DESELECT')
            for ob in merged:
                ob.select_set(True)
            context.view_layer.objects.active = merged[0]
            for ob in merged:
                bpy.ops.object.select_all(action='DESELECT')
                ob.select_set(True)
                context.view_layer.objects.active = ob
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

        if self.pivot_base_center and merged:
            for ob in merged:
                self._set_pivot_base_center(ob)

        if self.auto_smooth and merged:
            bpy.ops.object.select_all(action='DESELECT')
            for ob in merged:
                ob.select_set(True)
            context.view_layer.objects.active = merged[0]
            for ob in merged:
                bpy.ops.object.select_all(action='DESELECT')
                ob.select_set(True)
                context.view_layer.objects.active = ob
                try:
                    bpy.ops.object.shade_auto_smooth(use_auto_smooth=True, angle=0.523599)
                except AttributeError:
                    # Fallback for builds exposing the newer explicit operator.
                    bpy.ops.object.shade_smooth_by_angle(angle=0.523599, keep_sharp_edges=True)

        bpy.ops.object.select_all(action='DESELECT')
        for ob in merged:
            ob.select_set(True)
        if merged:
            context.view_layer.objects.active = merged[0]
        return merged

    def execute(self, context):
        if context.mode != 'OBJECT':
            self.report({'ERROR'}, "Switch to Object Mode before importing SKP")
            return {'CANCELLED'}
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob", "split_mode"))
        keywords['component_collections'] = False if self.merge_objects else keywords.get('component_collections', True)
        keywords['merge_mode'] = self.merge_mode if self.merge_objects else 'NONE'
        keywords['render_engine'] = 'CYCLES'
        importer = SceneImporter().set_filename(self.filepath)
        pools = ('objects', 'collections', 'meshes', 'cameras', 'materials', 'images')
        before = {key: set(getattr(bpy.data, key)) for key in pools}
        target_collection = context.collection
        old_camera = context.scene.camera
        old_selected = list(context.selected_objects)
        old_active = context.view_layer.objects.active
        context.window_manager.progress_begin(0, 100)
        try:
            result = importer.load(context, **keywords)
            if self.merge_objects:
                imported_objects = [ob for ob in bpy.data.objects if ob not in before['objects'] and ob.type == 'MESH']
                if imported_objects:
                    merged = self._merge_imported(context, imported_objects, target_collection)
                    removed_meshes = self._cleanup_merged_source_meshes(before['meshes'])
                    for col in list(bpy.data.collections):
                        if col not in before['collections']:
                            bpy.data.collections.remove(col)
                    self.report({'INFO'}, "SketchUp import complete: %d merged mesh object(s) created; %d source mesh datablock(s) cleaned" % (len(merged), removed_meshes))
                else:
                    self.report({'WARNING'}, "SketchUp import complete: no mesh objects to merge")
            else:
                self.report({'INFO'}, "SketchUp import complete")
            return result
        except Exception as error:
            traceback.print_exc()
            context.scene.camera = old_camera
            for key in pools:
                pool = getattr(bpy.data, key)
                for item in list(pool):
                    if item not in before[key]:
                        pool.remove(item, do_unlink=True)
            for ob in old_selected:
                ob.select_set(True)
            context.view_layer.objects.active = old_active
            self.report({'ERROR'}, str(error)[-1800:])
            return {'CANCELLED'}
        finally:
            if hasattr(importer, 'skp_model'):
                importer.skp_model.close()
            context.window_manager.progress_end()

    def draw(self, context):
        for prop in ('split_materials', 'component_collections', 'reuse_material',
                     'scenes_as_camera', 'import_camera', 'merge_objects'):
            self.layout.prop(self, prop)
        if self.merge_objects:
            self.layout.prop(self, 'merge_mode', expand=True)
            self.layout.prop(self, 'convert_quads')
            self.layout.prop(self, 'limited_dissolve')
            if self.limited_dissolve:
                self.layout.prop(self, 'limited_dissolve_angle')
            self.layout.prop(self, 'cube_project_uv')
            if self.cube_project_uv:
                self.layout.prop(self, 'cube_project_uv_scale')
            self.layout.prop(self, 'pivot_base_center')
            self.layout.prop(self, 'apply_rotation_scale')
            self.layout.prop(self, 'auto_smooth')


def menu_func_import(self, context):
    self.layout.operator(ImportSKP.bl_idname, text="SKP Bridge — SketchUp (.skp)")


def register():
    bpy.utils.register_class(SketchupAddonPreferences)
    bpy.utils.register_class(ImportSKP)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ImportSKP)
    bpy.utils.unregister_class(SketchupAddonPreferences)


if __name__ == "__main__":
    register()