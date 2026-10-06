"""Run the user's original CPython 3.11 reader in an isolated interpreter.

No Blender imports. The JSON protocol contains data only, never executable code.
Compatibility modifications: 2026, GPL-3.0-or-later.
"""
import json
import os
from pathlib import Path
import sys
import traceback


def snapshot(model, directory, cameras=False):
    materials = []
    for index, material in enumerate(model.materials):
        texture = material.texture
        tex = None
        if texture:
            # Always use an internal filename; source filenames may contain paths.
            filename = 'texture_%06d.png' % index
            texture.write(str(directory / filename))
            tex = dict(name=filename, dimensions=list(texture.dimensions))
        color = list(material.color)
        color[3] = round(max(0, min(1, material.opacity)) * 255)
        materials.append(dict(name=material.name, color=color, texture=tex))

    def material_name(item):
        mat = item.material
        return mat.name if mat else None

    def entities(source):
        faces = []
        for face in source.faces:
            # A fresh face wrapper has unit scale; Blender applies inheritance.
            face.st_scale = (1.0, 1.0)
            verts, triangles, uvs = face.tessfaces
            face_layer = getattr(face, 'layer', None)
            faces.append(dict(material=material_name(face), layer=(face_layer.name if face_layer else None), vertices=verts,
                              triangles=triangles, uvs=uvs,
                              smooth=any(e.GetSmooth() for e in face.edges)))
        groups = []
        for group in source.groups:
            group_layer = getattr(group, 'layer', None)
            groups.append(dict(name=group.name, layer=(getattr(group_layer, 'name', None) if group_layer else None),
                               hidden=bool(group.hidden), transform=group.transform,
                               material=material_name(group),
                               entities=entities(group.entities)))
        instances = []
        for instance in source.instances:
            instance_layer = getattr(instance, 'layer', None)
            instances.append(dict(name=instance.name, layer=(getattr(instance_layer, 'name', None) if instance_layer else None),
                                  hidden=bool(instance.hidden),
                                  transform=instance.transform,
                                  material=material_name(instance),
                                  definition=instance.definition.name))
        return dict(faces=faces, groups=groups, instances=instances)

    def camera(source):
        return dict(orientation=source.GetOrientation(), fov=source.fov,
                    aspect_ratio=source.aspect_ratio)

    return dict(protocol=1, materials=materials,
                layers=[dict(name=l.name, visible=bool(l.visible)) for l in model.layers],
                definitions=[dict(name=c.name, entities=entities(c.entities))
                             for c in model.component_definitions],
                entities=entities(model.entities),
                camera=camera(model.camera) if cameras else None,
                scenes=[dict(name=s.name, layers=[l.name for l in s.layers],
                             camera=camera(s.camera) if cameras else None)
                        for s in model.scenes])


def main():
    addon_dir = Path(__file__).resolve().parent
    native_dir = addon_dir / 'native'
    # Handles must stay alive until the native reader finishes.
    dll_handles = [os.add_dll_directory(str(native_dir)),
                   os.add_dll_directory(str(Path(sys.executable).parent))]
    blender_dir = Path(sys.argv[3])
    if blender_dir.is_dir():
        dll_handles.append(os.add_dll_directory(str(blender_dir)))
    sys.path.insert(0, str(native_dir))
    import sketchup
    model = sketchup.Model.from_file(sys.argv[1])
    try:
        output = Path(sys.argv[2])
        data = snapshot(model, output.parent, sys.argv[4] == '1')
        with output.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    finally:
        # Some builds release the model internally and expose no close().
        # The reader runs in its own process, so process exit also frees it.
        close = getattr(model, 'close', None)
        if callable(close):
            close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)