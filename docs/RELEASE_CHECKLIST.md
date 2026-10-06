# SKP Bridge Release Checklist

Before publishing a release:

- Confirm the Blender minimum version in README and addon metadata.
- Test a representative .skp file in Blender on Windows x64.
- Test import with Merge Objects disabled.
- Test Merge Objects: All Objects.
- Test Merge Objects: By Materials.
- Test Merge Objects: By Layers, including nested components and Layer0 inheritance.
- Test Convert Triangles to Quads.
- Test Limited Dissolve by Material and angle display.
- Test Cube Project UV and UV Scale.
- Test Pivot: Center at Base.
- Test Apply Rotation & Scale.
- Test Auto Smooth.
- Confirm the release ZIP contains the native reader and runtime.
- Confirm third-party notices are included.
- Create a GitHub tag and release matching the addon version.
