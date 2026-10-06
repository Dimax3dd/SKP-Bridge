"""Data adapter for the unchanged native SketchUp reader. GPL-3.0-or-later."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace as Record


class Texture:
    def __init__(self, data, directory):
        self.name = data['name']
        self.dimensions = tuple(data['dimensions'])
        self.path = directory / self.name

    def write(self, path):
        shutil.copyfile(self.path, path)


class Face:
    def __init__(self, data, materials):
        self.material = materials.get(data['material'])
        self.layer = data.get('layer')
        self.vertices = [tuple(v) for v in data['vertices']]
        self.triangles = data['triangles']
        self.uvs = data['uvs']
        self.st_scale = (1.0, 1.0)
        self.edges = [Edge(data['smooth'])]

    @property
    def tessfaces(self):
        s, t = self.st_scale
        return self.vertices, self.triangles, [(u * s, v * t) for u, v in self.uvs]


class Edge:
    def __init__(self, smooth):
        self.smooth = smooth

    def GetSmooth(self):
        return self.smooth


class Camera(Record):
    def GetOrientation(self):
        return self.orientation


class Model:
    @classmethod
    def from_file(cls, filename, cameras=False):
        if os.name != 'nt':
            raise RuntimeError('This build includes the original Windows x64 SKP reader.')
        import bpy
        addon_dir = Path(__file__).resolve().parent
        executable = addon_dir / 'runtime' / 'python.exe'
        if not executable.is_file():
            raise RuntimeError('Bundled Python is missing. Reinstall the complete ZIP.')
        temp = tempfile.TemporaryDirectory(prefix='skp_52_')
        try:
            output = Path(temp.name) / 'scene.json'
            command = [str(executable), '-I', '-X', 'utf8', str(addon_dir / 'reader_worker.py'),
                       os.path.abspath(filename), str(output),
                       str(Path(bpy.app.binary_path).parent), '1' if cameras else '0']
            result = subprocess.run(command, cwd=str(addon_dir), capture_output=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode or not output.is_file():
                detail = result.stderr.decode('utf-8', errors='replace').strip()
                if not detail:
                    detail = 'Native reader exited with code %s' % result.returncode
                raise RuntimeError('SKP reader failed: ' + detail[-2400:])
            with output.open(encoding='utf-8') as stream:
                data = json.load(stream)
            model = cls.from_data(data, Path(temp.name))
            model._temp = temp
            return model
        except BaseException:
            temp.cleanup()
            raise

    @classmethod
    def from_data(cls, data, directory):
        if data.get('protocol') != 1:
            raise RuntimeError('Unsupported SKP reader protocol')
        self = cls()
        self._temp = None
        materials = {}
        for item in data['materials']:
            tex = Texture(item['texture'], directory) if item['texture'] else None
            materials[item['name']] = Record(name=item['name'], color=item['color'], texture=tex)
        self.materials = list(materials.values())
        layers = {item['name']: Record(**item) for item in data['layers']}
        self.layers = list(layers.values())
        definitions = {item['name']: Record(name=item['name']) for item in data['definitions']}

        def entities(item):
            groups = []
            for group in item['groups']:
                fields = dict(group)
                fields.update(layer=layers.get(group['layer']), material=materials.get(group['material']),
                              entities=entities(group['entities']))
                groups.append(Record(**fields))
            instances = []
            for instance in item['instances']:
                fields = dict(instance)
                fields.update(layer=layers.get(instance['layer']), material=materials.get(instance['material']),
                              definition=definitions[instance['definition']])
                instances.append(Record(**fields))
            return Record(faces=[Face(f, materials) for f in item['faces']], groups=groups, instances=instances)

        for item in data['definitions']:
            definitions[item['name']].entities = entities(item['entities'])
        self.component_definition_as_dict = definitions
        self.component_definitions = list(definitions.values())
        self.entities = entities(data['entities'])
        self.camera = Camera(**data['camera']) if data['camera'] else None
        self.scenes = [Record(name=s['name'], layers=[layers[n] for n in s['layers'] if n in layers],
                              camera=Camera(**s['camera']) if s['camera'] else None)
                       for s in data['scenes']]
        return self

    def close(self):
        if self._temp:
            self._temp.cleanup()
            self._temp = None