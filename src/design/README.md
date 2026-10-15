# Pythia design system

Calm, mostly white, with a true black dark mode. One accent colour. Big
numbers, green and red only for up and down, smooth area charts, simple rows,
generous spacing. No neon, no glow, no heavy borders, no monospace for
numbers.

Import everything from `src/design`:

```tsx
import { Page, Card, ListRow, BigNumber, Change, AreaChart, RangeChips, money, seriesChange } from "../design";
```

## Files

| File | What it holds |
| --- | --- |
| `tokens.ts` | Colour palettes (light, dark), chart series colours, type scale, spacing, radii, font stacks. The only place a colour is written down. |
| `theme.ts` | Light, dark or system. `installTheme()` (called in `main.tsx`) puts the token stylesheet in `<head>`; `useTheme()`, `useThemePref()`, `setThemePref()`. |
| `format.ts` | `money`, `signedMoney`, `signedPct` (percent units), `signedRatio` (fractions), `compactMoney`, `price`, `changeTone`, `seriesChange`, `tickerOf`, `tickerHue`, `ago`. |
| `chartPath.ts` | Chart geometry (monotone smoothing, thinning, scrub lookup). No React. |
| `primitives/` | The components below. |
| `flows/` | The old stand-in kit's import path. Re-exports the primitives; keep it working, do not add to it. |

## Colour

Never write a hex colour in a component. Use the Tailwind names, which are
CSS variables and swap with the theme by themselves (no `dark:` classes
needed):

| Role | Tailwind | CSS variable | Use |
| --- | --- | --- | --- |
| bg | `bg-canvas` | `--color-bg` | the page |
| surface | `bg-surface` | `--color-surface` | cards, sheets, tab bar |
| surface-2 | `bg-surface-2` | `--color-surface-2` | inputs, chips, segmented, hover |
| raised | `bg-raised` | `--color-raised` | the selected pill in a segmented control |
| line | `border-line`, `divide-line` | `--color-line` | hairlines |
| line-strong | `border-line-strong` | `--color-line-strong` | hover borders, the scrub line |
| text | `text-ink` | `--color-text` | body text and big numbers |
| muted | `text-muted` | `--color-muted` | labels, second lines |
| faint | `text-faint` | `--color-faint` | timestamps, hints |
| accent | `text-accent`, `bg-accent/10` | `--color-accent` | links, focus, selected, research |
| up / down / warn | `text-up`, `text-down`, `text-warn` | `--color-up` ... | gains, losses, caution |
| primary | `bg-primary text-on-primary` | `--color-primary` | the one main button |

Alpha works: `bg-up/10`, `bg-accent/10`. In SVG use `style={{ stroke: "var(--color-up)" }}`
(presentation attributes do not take `var()` everywhere). Multi-series charts use
`var(--color-series-1)` to `-6`.

Every text role reads at WCAG AA (4.5:1) on bg, surface and surface-2 in
both themes; `tokens.test.ts` enforces it. Add a role there, not in a page.

The old names (`cyber-*`, `accent`, `purple-neon`, `success`, `warning`,
`danger`) are aliases of the new roles, so pages not yet rewritten already
look calm. Do not use them in new code. `font-mono` now means the sans with
tabular figures; real code uses `font-code`.

## Type and spacing

Inter when installed, the system UI font otherwise. Sizes: display 40
(portfolio total), title 28 (page title), headline 20 (sections, sheets),
body 15, caption 13, small 11. Cards pad 20 (`p-5`) with radius 20
(`rounded-card`), controls radius 12 (`rounded-control`), buttons and chips
are pills. Pages stack sections with `space-y-5`. Add `tabular` to any
number that changes in place.

## Components

Layout
- `Page({ title, subtitle?, right?, wide? })`: the page frame, a 2xl column (5xl with `wide` for tables).
- `Card({ title?, right?, padded?, label? })`: soft surface with a hairline. `padded={false}` for edge to edge rows.
- `SectionTitle({ right? })`: heading between cards.
- `List`: wraps `ListRow`s with hairlines between them.
- `ListRow({ ticker? | icon? | leading?, title, subtitle?, right?, rightSub?, onClick?, chevron?, selected? })`: the row everything is built from. With `onClick` it is a button.
- `TickerBadge({ symbol, size? })`: round letters with a stable hue per ticker.

Numbers
- `BigNumber({ value, label?, size?: "md" | "lg" | "xl", sub? })`: the amount first. Home uses `xl`.
- `Change({ usd?, pct?, tone, size?, suffix? })`: signed, green or red, always with an arrow. `pct` is in percent units.
- `Stat({ label, value, sub? })`: small label over value, for two to four side by side.
- `Chip({ tone?, selected?, onClick? })`: a label, or a toggle chip with `onClick`.
- `Badge({ tone? })`: smaller status label (`good`, `warn`, `bad`, `accent`, `neutral`).

Controls
- `Button({ variant: "primary" | "secondary" | "danger" | "ghost" | "accent", size?, icon?, full? })`: pills. One primary per screen.
- `IconButton({ icon, label })`: round, for close and more.
- `Segmented({ options, value, onChange, label })`: two to five choices, arrow keys move.
- `Tabs(...)`: underlined tabs for sections of one page.
- `RangeChips({ value, onChange, options?, disabled? })`: `1D 1W 1M 1Y Max` above or below a chart.
- `Toggle({ on, onChange, label })`, `Field({ label, hint?, error? })`, `inputCls` for inputs and selects.

Overlays
- `Sheet({ open, onClose, title, footer?, wide? })` (alias `Modal`): bottom sheet on a phone, dialog on desktop. Focus is trapped, Escape closes, focus returns.
- `ConfirmSheet(...)`: ask before anything that cannot be undone.

Feedback
- `Empty({ icon?, title, action?, compact? })`, `Skeleton({ className })`, `Spinner`, `Notice({ tone })`.

Charts
- `AreaChart({ data, label, tone?, baseline?, onScrub?, renderTip?, height? })`: the big chart. Tone defaults to up or down from first to last point. Hover, drag or arrow keys scrub; show the scrubbed value in the page's `BigNumber`.
- `Sparkline({ data, tone?, width?, height?, fill? })`: small, for rows.
- `LineChart({ series })`: several series on one scale with a legend.

Navigation
- `TabBar({ items, active, onSelect })`: the phone's bottom tabs. The shell owns it.

## Rules

1. Simple mode is the default. A page shows its essentials first; detail sits behind a row tap, a sheet or the advanced switch.
2. One number per card is the hero. Everything else is muted.
3. Green and red mean up and down, never decoration. Pair them with an arrow or a sign.
4. No borders heavier than a hairline, no shadows on cards, no glow, no gradients except the chart fill.
5. Every control is reachable by keyboard and shows the accent focus ring.
6. Nothing may scroll sideways at 360 px. Long rows truncate, tables sit in `overflow-x-auto`.
7. No em dashes in copy.

## The old kit

`src/components/ui.tsx` keeps its API (`Card`, `PageHeader`, `Button tone=...`,
`Badge`, `Notice`, `EmptyState`, `Field`, `Readout`, `StatCard`, `Sparkline`,
`MultiLineChart`, ...) and is restyled on these tokens. When rewriting a page,
move it to `src/design` and use `Page` instead of `PageHeader`. Button tones
map as: `cyan` to primary ink, `neutral` to secondary, `purple` to accent
tint, `green`/`red`/`amber` to soft tints.
