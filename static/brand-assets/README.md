# joga pro teens — brand assets

Visual identity assets for [jogaproteens.cz](https://jogaproteens.cz).
Generated from the brand guidelines; see `Brand Guidelines.dc.html` in the design project.

## Colors

| Token | Hex | Use |
| --- | --- | --- |
| Primary | `#F7C9B8` | Logo center, buttons, highlights |
| Light tint | `#FCE3DA` | Section backgrounds, hero panels |
| Accent | `#2E4A66` | Figures, headings, body text |
| Accent tint | `#C9D9E8` | Nav on dark, pattern details |
| Background | `#FBF8F4` | Page background, logo cutouts |

Available as `colors/colors.css` (CSS custom properties), `colors/colors.scss`, `colors/colors.json`.

## Logo

```
logo/
  icon-full-color.svg          navy figures, peach center — default
  icon-single-color-navy.svg   all navy — print, embroidery, stamps
  icon-reversed.svg            cream figures — dark backgrounds
  favicon-monogram.svg         heads + diamond only — below 24px
  favicon-monogram-bg.svg      monogram on a rounded cream tile
  wordmark.svg                 "joga pro teens" type only
  lockup-horizontal.svg        icon + two-line name — primary lockup
  lockup-horizontal-reversed.svg
  lockup-stacked.svg           icon above centered name
  lockup-stacked-reversed.svg
  png/                         512/1024px transparent PNG fallbacks
favicon/                       16, 32, 48, 180, 512px PNGs
```

The crossed-legs cutout inside each figure must always match the background it
sits on. On any background other than `#FBF8F4`, edit the cutout fill to match.

**Clear space:** one head diameter (x) on all sides.
**Minimum sizes:** icon 32px; horizontal lockup 120px wide; below 24px use the favicon monogram.

## Patterns

```
patterns/
  pattern-friends.svg          600x600 tiled preview
  pattern-friends-tile.svg     150x150 seamless tile
  pattern-crossed-legs.svg / -tile.svg    64x64 tile
  pattern-circles.svg / -tile.svg         120x120 tile
```

Tile in CSS with the `-tile.svg` files:

```css
background: #FBF8F4 url("patterns/pattern-friends-tile.svg") repeat;
```

Patterns are backgrounds only — never place the logo on top of one.

## Typography

- **Display / wordmark:** Maragsâ. Sentence case, never letter-spaced.
- **Text UI:** Nunito, weights 600–800.

The SVG lockups and wordmark reference Maragsâ by font name and will fall back
to a system sans on machines without it. For fixed-output use (email, print,
third-party platforms), convert the text to outlines or use the PNG exports.

## Don'ts

Don't stretch or squash · don't recolor outside the palette · don't rotate the
mark · don't add shadows or effects · don't place the logo on busy patterns ·
don't use low-contrast color pairings.
