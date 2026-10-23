# T300 building-block reference reconstruction

This is a real mesh-based, freely rotatable GLB reconstruction made from four
user-supplied renderings. It is not an original CAD asset, measured replica,
photogrammetric scan, or validated assembly/building guide. Hidden surfaces and
connections are inferred. Scene units are illustrative, not measured dimensions.

The model includes the robot chassis, mast, display, wheels, crates, studs,
warehouse shelving, walls, floor, cartons, signs, and lamps as three-dimensional
geometry. It is not a set of billboard images. Geometry is merged by material
to keep draw calls low on mobile devices.

Regenerate with `node scripts/build-t300-model.mjs` from `request_web/frontend`.
The generator uses Three.js (MIT) and the Helvetiker typeface supplied with the
Three.js r186 examples. The vendored typeface JSON retains its original license
and copyright metadata. Source:
https://github.com/mrdoob/three.js/blob/r186/examples/fonts/helvetiker_regular.typeface.json

Product context (the real industrial robot, not the size/price of this set):
https://www.pudurobotics.com/about/news/6625d9c13383390044375e78

Actual stock starts at zero. Procurement price, material, physical dimensions,
and customs classification require internal confirmation; do not derive those
values from the full-size robot's published specifications.
