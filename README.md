# SKP Bridge

<img width="463" height="696" alt="Screenshot_26" src="https://github.com/user-attachments/assets/3ff5c762-87c0-497e-b9d0-1a912153ee36" />

**SketchUp `.skp` importer for Blender 5.2+ on Windows x64.**

SKP Bridge is an enhanced Blender importer based on the open-source SketchUp importer by Martijn Berger, Sanjay Mehta and Arindam Mondal. It is designed for architectural visualization workflows where imported SketchUp geometry needs to be cleaned, merged and prepared for Blender.

## Highlights

- Native SketchUp `.skp` import
- Merge Objects: **All Objects / By Materials / By Layers**
- Split by Materials
- Collections for Components
- Use Existing Materials
- Import SketchUp scenes and last view as cameras
- Convert Triangles to Quads
- Limited Dissolve by Material with adjustable angle
- Cube Project UV with adjustable scale
- Pivot: Center at Base
- Apply Rotation & Scale
- Auto Smooth
- Recursive SketchUp tag/layer inheritance
- Cleanup of temporary imported mesh datablocks

## Requirements

- **Blender 5.2+**
- **Windows x64**
- SketchUp files supported by the bundled SketchUp SDK reader

The current native reader reports **SketchUp SDK 21.1.279**. SKP format compatibility is therefore determined by that SDK version; newer SketchUp formats are not guaranteed.

## Installation

1. Download the latest `SKP_Bridge-1.0.8-Windows-x64.zip` from **GitHub Releases**.
2. In Blender open **Edit → Preferences → Add-ons → Install from Disk**.
3. Select the downloaded ZIP.
4. Enable **SKP Bridge**.
5. Use **File → Import → SKP Bridge — SketchUp (.skp)**.

> Keep the ZIP intact during installation. The bundled Windows native reader and runtime are required by the importer.

## Usage

Open the importer from **File → Import → SKP Bridge — SketchUp (.skp)**.

The processing options are intentionally aimed at architectural visualization workflows. You can import normally or enable merging and geometry cleanup in the same import operation.

### Merge modes

- **All Objects** — combine imported geometry into one object.
- **By Materials** — combine geometry into material-based objects.
- **By Layers** — combine geometry according to the effective SketchUp tag/layer.

For nested SketchUp groups/components, an object on `Layer0` inherits the parent tag when it has no explicit tag. An explicit nested tag overrides the inherited tag.

## Project structure

```text
addon/SKP_Bridge/
├── __init__.py
├── compat_reader.py
├── reader_worker.py
└── SKPutil/
```

The `release` ZIP additionally contains the Windows x64 native reader and bundled Python runtime required for the current build.

## Credits

SKP Bridge is based on the open-source SketchUp importer by:

- Martijn Berger
- Sanjay Mehta
- Arindam Mondal

Original project:
https://github.com/martijnberger/sketchup_importer

SKP Bridge modifications and Blender 5.2 adaptation are maintained in this repository.

## License

The Python importer code is released under **GNU GPL v3 or later**. See [`LICENSE`](LICENSE).

The release package also contains third-party native components from the SketchUp SDK and a bundled Python runtime. Those components are **not relicensed as GPL by SKP Bridge**. Their respective notices and licenses remain applicable; see [`THIRD_PARTY_NOTICES.txt`](THIRD_PARTY_NOTICES.txt) and the files included in the release package.

The third-party SDK binaries are distributed as part of the Windows release build solely to provide the native `.skp` reader used by SKP Bridge. Users should review the applicable third-party terms before redistributing modified builds.

## Status

**Version 1.0.8 — stable.**

This release focuses on reliable SketchUp import and post-import preparation for Blender architectural visualization workflows.
