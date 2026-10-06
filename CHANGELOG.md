# Changelog

## 1.0.8

- Fixed recursive SketchUp tag/layer inheritance for nested groups and components.
- `Layer0` now inherits the effective parent tag when appropriate.
- Explicit nested tags override inherited tags.
- Added adjustable Cube Project UV scale (default 1.0).
- Preserved the stable merge, quads, dissolve, pivot, transform and smoothing workflow from 1.0.7.

## 1.0.7

- Limited Dissolve by Material now follows Blender's material-slot selection workflow.
- Max Angle is displayed and applied in degrees (default 0.1°).
- Uses Limited Dissolve with Normal delimit and no dissolve boundaries.

## 1.0.0

- Initial semantic-versioned SKP Bridge release.
- Added merge workflow and architectural visualization cleanup tools.
