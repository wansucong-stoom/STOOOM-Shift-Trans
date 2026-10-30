# STOOM common product identity v1

Approved reference: https://stoom.win/ and the canonical `stoom-mark-original.css`.
The original circle, diagonal geometry and light mark colour remain common.
Product labels are `SST` and `Pwh`; no per-product font scaling or manual drawing is used.
The user accepted the layered/overlapping appearance on 2026-10-30 KST.

## Shared measurements

- Icon master: 40×40 units; circle origin (3, 5.5), outer diameter29, stroke2.
- Original diagonal:14×2, centre(28,8) relative to circle origin, rotation−35°.
- Product label: Inter variable4.001, wght850, opsz14, size10.5, letter spacing0.
- Label centre relative to circle: (14.5,17). This common optical position avoids
  independently moving or resizing each product's letters. All layered overlaps
  use the same order and remain part of this shared identity.
- Colour: light #e3faff, cyan #67d8ff, glow opacity38%, backing #071019.
- Header lockup:158×48; icon48, gap10, wordmark font20, wght850, opsz14,
  letter spacing0.11em. PNG1x/3x and SVG share the same frozen font outlines.

`brand-spec.json` records exact geometry and SHA256s. Original CSS, pinned font,
OFL and provenance are included. Fonts are not installed globally.

## Format limits

`mark-full-glow.svg` and `mark-full-glow-alpha.png` retain the original18-unit
glow with generous padding. The PNG's entire outer alpha edge is zero: the full
transparent glow is not cropped. `mark-full-glow-dark.png` is the separate backed
presentation for light surrounding surfaces.

Small Windows icons use a compact4.5-unit halo within a dark rounded backing,
retaining colour/opacity and mark geometry. At16px both product labels use the
same5px minimum. Those three letters cannot be guaranteed fully legible at that
resolution; the circle, diagonal and as much cyan glow as the format permits remain.
The native-size preview checks16/20/24/32/48/64/128px on light and dark surfaces.
This is a documented small-format treatment, not a flat replacement for the original.

Qt's SVG renderer need not support the SVG filter. Native apps should use the
provided PNG/ICO, whose glow is already rendered. Web apps may use SVG or the
canonical CSS plus `stoom-product-marks.css` and included Inter font.

## Rebuild

Use Python with PySide6 and NumPy (development tools only):

```
python build_product_identity.py NEW_OUTPUT_DIRECTORY
```

Use a separate output directory. Copy built assets into each application; shipped
apps must not refer to this shared folder at runtime. The generator uses the
included font and CSS when executed from this kit. Keep OFL and provenance with
font redistribution. `original/` is the unlettered common mark, `sst/` and `pwh/`
are the product variants.
