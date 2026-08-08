# Sentient Design System (premium)

Dark-first intelligence-platform UI language. Architecture is frozen; this is
presentation only.

## Tokens (src/styles.css)
- Surfaces: `--surface`, `--surface-2`, `--surface-3` (rising elevation),
  `--hairline` (1px separators). Deep indigo-black base, cool neutrals.
- Type: Inter (UI) + JetBrains Mono (numerics/keys). Tabular numerals via
  `.tabular`. Feature settings enabled for cleaner glyphs.
- Motion: `--animate-fade-in/rise/scale-in/shimmer`, all cubic-bezier(0.16,1,0.3,1).
  Global `prefers-reduced-motion` guard.
- Utilities: `.glass`, `.elevated`, `.text-gradient`, `.skeleton`, `.grid-lines`.

## Primitives (src/components/premium/primitives.tsx)
- `Reveal` — viewport-triggered staggered entrance (reduced-motion aware).
- `Panel` — canonical elevated surface; `interactive` adds hover lift.
- `Skeleton` / `SkeletonCard` — shimmer loading.
- `ConfidenceMeter` — signature radial trust gauge (green/amber/red by band).
- `Sparkline` — dependency-free inline trend.
- `EmptyState` — never a dead end.
- `Kbd` — keyboard hint chip.

## Interactions
- `CommandPalette` (⌘K) — navigation + live workspace search.
- Grouped sidebar with active indicator rail; collapsible.
- Refined focus rings, custom scrollbars, selection color.

## Usage rule
Compose screens from `Panel` + `Reveal` + the primitives. Prefer
`ConfidenceMeter` over flat badges for trust. Every async surface needs
loading (skeleton), empty, and error states.
