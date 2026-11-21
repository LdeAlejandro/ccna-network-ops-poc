# Avatar audit before changes

| Operator | 1 · Field · Level 7 | 2 · Uplink · Level 8 | 3 · Vanguard · Level 9 | 4 · Sentinel · Level 10 |
| --- | --- | --- | --- | --- |
| Rook | assets/rook.pixels | assets/rook-uplink.pixels | assets/rook-vanguard.pixels | assets/rook-sentinel.pixels |
| Relay | assets/relay.pixels | assets/relay-uplink.pixels | assets/relay-vanguard.pixels | assets/relay-sentinel.pixels |

All eight files were present, distinct, correctly ordered and named, and readable as 104 × 106 indexed sprites with a shared 32-entry palette. Index 0 is transparent. The baseline sprites match the supplied Mint Circuit references. Rook is near-front with magenta hair and an over-ear headset. Relay is three-quarter with an undercut and an earpiece. The two silhouettes are 96 pixels wide, with Relay's eyes sitting several pixels higher. Rook's later stages redraw parts of the head and add bulkier shoulder gear than Relay's. Both upper-stage visors cover part of the eye line.

The existing levels unlock at 0, 360, 1,360 and 2,360 earned XP. Operator choice lives in SQLite's operator_choice table. The E shortcut was writing a preview index into the legacy profile table, which overrode the earned stage on the dashboard and after a restart. There was no separate preview screen. The renderer used the same inline Operator panel for both paths. Invalid database indices and missing or malformed sprite files were unhandled.

Sixel uses an authored palette over a theme matte, nearest-neighbor scaling, and a cache keyed by stage, operator, palette, cell size and viewport. No stale cache entry was reproduced when those inputs changed. Its cell-aligned matte is cleared on redraw. The Unicode renderer uses a center-sampled half-block grid and cropped the lower jacket at small sizes. The app probes for Sixel and falls back to Unicode. It has no Kitty renderer.

Existing tests exercised level transitions, a saved preview override, operator swapping, Sixel negotiation, Unicode fallback, themes and terminal resizing. They did not cover every asset, invalid values, or preview isolation.

## Visual verification

The contact sheet uses the same padded portraits as the app at 2× nearest-neighbor scale. The Stage 1 and Stage 4 Mint Circuit views come from the real application running in a pseudoterminal at 140 × 45 cells. The verification harness responds to the graphics probe, then sends the regular preview keys. ImageMagick decodes the emitted Sixel, and the evidence script draws the ANSI text around it. The theme comparison shows both Sentinel portraits in all five themes. The 80 × 24 render uses the application's Unicode path. These files are offline renders of terminal output. A live graphical terminal session was not verified.

The two baseline indexed assets are intact. Four rows of transparent vertical padding bring the eye lines closer together while preserving both camera angles. The revised stage files keep the baseline faces, hair, and silhouettes. Headset lights and shoulder reinforcement distinguish Uplink. Collar ranks and brighter equipment distinguish Vanguard and Sentinel. The authored art palette stays fixed across themes.

## Relay style revision

The contact sheet and terminal renders now show the restyled Relay. The preceding visual notes describe the first refinement pass. Rook's supplied portrait was the style reference for the revision. The built-in image generation tool used the original Relay screenshot as the subject reference and Rook's screenshot for the near-front pose, face scale, expressive eyes, flat peach shading, plum outlines, magenta hair accents, and high-collar uniform. The prompt retained Relay's swept undercut, angular jaw, strong brows, and headset, and requested a single transparent bust without interface elements. The resulting source is `../source/relay-rook-style.png`.

Run `python3 -m design.avatar_refinement.build_relay` to rebuild the four Relay assets from the source with Pillow. The conversion uses nearest-neighbor sampling and the shared indexed palette. All four stages share the same face and hair. The headset, shoulder piping and collar insignia change with rank.
