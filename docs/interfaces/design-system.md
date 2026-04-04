# Design System -- "Electric Charcoal v2"

The dashboard's visual identity is dark-only, designed to feel like professional mission control for AI agents -- powerful, precise, intentional. Not generic, not templated.

**The anchor**: Electric lime (#c8ff00) on deep charcoal. Immediately distinctive.

**The constraint**: Ternary border-radius. Elements are sharp (0px), micro-rounded (2px), or fully round (pill). No middle ground.

## Color System

All colors are defined as CSS custom properties in `dashboard/src/app.css` inside the `@theme` block using OKLCH notation.

### 60-30-10 Distribution

- **60%** -- Charcoal surfaces (background, cards, panels)
- **30%** -- Text hierarchy (white through warm grays)
- **10%** -- Accent colors (lime, cyan) + status colors

### Accent Colors

| Token | OKLCH | Usage |
|-------|-------|-------|
| `--color-accent-primary` | `oklch(0.91 0.20 128)` | Primary CTAs, active nav indicator |
| `--color-accent-primary-hover` | `oklch(0.95 0.18 128)` | Hover state for primary buttons |
| `--color-accent-primary-muted` | `oklch(0.91 0.20 128 / 0.15)` | Tinted backgrounds |
| `--color-accent-primary-dim` | `oklch(0.75 0.15 128)` | Desaturated lime for borders, secondary emphasis, focus rings |
| `--color-accent-primary-wash` | `oklch(0.91 0.20 128 / 0.04)` | Barely-visible background tint (sidebar hover) |
| `--color-accent-secondary` | `oklch(0.82 0.14 195)` | Trigger type names, secondary highlights |
| `--color-accent-secondary-muted` | `oklch(0.82 0.14 195 / 0.12)` | Tinted backgrounds for secondary accent |

### Surface Scale

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-surface-0` | `#0a0a0c` | Page background, deepest layer |
| `--color-surface-05` | `#111113` | Sidebar, table headers, subtle elevation |
| `--color-surface-1` | `#161618` | Cards, input backgrounds |
| `--color-surface-2` | `#1c1c20` | Hover states, elevated surfaces |
| `--color-surface-3` | `#28282e` | Pressed states, tertiary surfaces |

### Text Hierarchy

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-fg` | `#f0f0f0` | Primary text, headings, active labels |
| `--color-fg-muted` | `#c0c0c8` | Secondary text, descriptions, data values |
| `--color-fg-faint` | `#70707c` | Tertiary text, section headers, placeholders, disabled |

### Borders

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-edge-strong` | `#353540` | Primary container boundaries |
| `--color-edge` | `#2a2a30` | Standard card/table borders |
| `--color-edge-subtle` | `#1e1e22` | Dividers within cards, table row separators |
| `--color-edge-ghost` | `#161618` | Barely-visible structural lines |

### Status Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-ok` | `#34d399` | Success indicators, health checks passing |
| `--color-warn` | `#fbbf24` | Warnings, overwrite confirmations |
| `--color-fail` | `#ff4d6a` | Errors, failed runs, destructive actions |
| `--color-info` | `#60a5fa` | Informational notices, explanations |

## Typography

Fonts are loaded from Google Fonts in `dashboard/src/app.html`.

### Font Pairing

| Role | Font | Weights | Usage |
|------|------|---------|-------|
| Display / Body | Space Grotesk | 300-700 | Page titles, section headers, body text, buttons |
| Data / Code | IBM Plex Mono | 400, 500 | Agent names, stat numbers, code blocks, metadata values |

### Type Scale

| Element | Size | Weight | Tracking | Example |
|---------|------|--------|----------|---------|
| Page title (h1) | `text-2xl` (24px) | `font-semibold` (600) | `-0.03em` | "Launchpad", "Agents" |
| Section header | `.section-label` CSS class | `font-semibold` (600) | `0.14em` | "AGENT FLEET", "BUILD" (sans, uppercase) |
| Stat number | `.metric-value` CSS class | `font-semibold` (600) | `-0.02em` | "1,234" (mono, tabular-nums) |
| Body text | `text-[13px]` | `font-normal` (400) | default | Descriptions, prompts |
| Small label | `.section-label` | `font-semibold` (600) | `0.14em` | Section headers (sans, uppercase) |
| Badge / tag | `text-[12px]` | `font-normal` (400) | default | Feature pills, tag filters (mono) |

### Rules

- Section labels use `font-sans` (Space Grotesk), NOT `font-mono`
- Use `font-variant-numeric: tabular-nums` on all numeric data
- Use `text-wrap: balance` on multi-line headings
- Monospace (`font-mono`) reserved for: agent names, model identifiers, file paths, config values, stat numbers, table data

## Shared CSS Utility Classes

Defined in `dashboard/src/app.css`:

| Class | Purpose |
|-------|---------|
| `.section-label` | Uppercase section headers (sans, 11px, 600 weight, 0.14em tracking, fg-faint) |
| `.metric-value` | Large stat numbers (mono, 22px, 600 weight, tabular-nums) |
| `.metric-label` | Stat labels (12px, fg-faint) |
| `.status-dot` | 6px solid-color circle (no box-shadow glow) |
| `.active-border` | Restrained streaming/running indicator (dim lime border + subtle 6% shadow) |
| `.card-surface` | Container border with left-accent slot (transparent by default, colored on hover) |
| `.card-surface-error` | Error variant with red left border |

## Border Radius

Ternary system:

### Sharp (0px)

- Cards and panels
- Input fields, textareas, select dropdowns
- Table containers
- Command palette panel
- Sidebar
- Drawer panels
- Code blocks and pre elements

### Micro (2px -- `rounded-[2px]`)

- Primary action buttons
- Secondary action buttons
- Kbd hint badges
- Inline code badges

### Pill (`rounded-full`)

- Tag filter pills (CapabilityFilterBar)
- Status badge/chip elements
- Version pills
- Count badges
- Scrollbar thumb

### Exception

Danger/destructive buttons stay sharp (no rounding). The angular shape signals irreversibility.

## Surface Treatments

### Card Surface

The `.card-surface` utility creates a border with a left-accent slot:

```css
.card-surface {
  border: 1px solid var(--color-edge);
  border-left: 2px solid transparent;
  transition: border-color 200ms;
}
.card-surface:hover {
  border-color: var(--color-accent-primary-dim);
}
```

### Card Surface -- Error Variant

```css
.card-surface-error {
  border: 1px solid var(--color-edge);
  border-left: 2px solid var(--color-fail);
  transition: border-color 200ms;
}
```

### Active Border (Streaming/Running State)

```css
.active-border {
  border-color: var(--color-accent-primary-dim);
  box-shadow: 0 0 8px oklch(0.91 0.20 128 / 0.06);
}
```

Used only on: streaming ConversationThread container, active flow nodes.

## Layout Architecture

### Shell Structure

```
+---sidebar (220px/48px)---+---header-bar (48px)----+
|                          |  breadcrumbs    search  |
|  BRAND (logo, home)      +-------------------------+
|  BUILD (agents, flows,   |                         |
|    teams, skills)        |  PAGE CONTENT            |
|  OPERATE (audit)         |  (max-w-1400, px-8/10)  |
|  META (system, toggle)   |                         |
+--------------------------+-------------------------+
```

### HeaderBar (`HeaderBar.svelte`)

- Left: Breadcrumb trail from `breadcrumb.svelte.ts` store
- Right: Cmd+K search trigger button, system health indicator
- Height: 48px, `border-b border-edge bg-surface-0`

### Sidebar Navigation

Three zones separated by `border-edge-subtle` dividers:

**Active indicator**: Left-edge 2px lime bar (`border-l-2 border-accent-primary`) + `text-fg`. No background highlight.

**Hover**: Directional gradient: `bg-gradient-to-r from-accent-primary-wash to-transparent`.

**Section labels**: `.section-label` class at 10px/0.15em tracking/60% opacity. Only visible when sidebar is expanded.

**Collapsed**: 48px width, icons only. Section labels hidden. No flyout menus.

### Breadcrumb System

Store: `dashboard/src/lib/stores/breadcrumb.svelte.ts`

Pages call `setCrumbs()` in `$effect` once data is loaded:
- List pages: `setCrumbs([{ label: 'Agents' }])`
- Detail pages: `setCrumbs([{ label: 'Agents', href: '/agents' }, { label: detail.name }])`
- Creation pages: `setCrumbs([{ label: 'Agents', href: '/agents' }, { label: 'New Agent' }])`

Fallback: HeaderBar derives placeholder crumbs from URL segments while store is empty.

### Command Palette

State: `dashboard/src/lib/stores/command-palette.svelte.ts`

Shared between CommandPalette.svelte (keyboard trigger) and HeaderBar.svelte (visible button).

## Component Patterns

### Buttons

| Variant | Classes | Notes |
|---------|---------|-------|
| Primary | `rounded-[2px] bg-accent-primary text-surface-0 font-medium` | Dark text on lime. No hover glow. |
| Secondary | `rounded-[2px] border border-edge bg-transparent text-fg-muted` | Border shifts to accent-primary-dim on hover. |
| Danger | Sharp (no rounding), `border border-fail text-fail` | Angular shape signals irreversibility. |

### Inputs

Sharp corners (0px). Focus state: `focus:border-accent-primary-dim/60 focus:shadow-[0_0_0_3px_oklch(0.75_0.15_128/0.08)]`.

### Tables

- No outer border wrapper
- Header row: `bg-surface-05`, `.section-label` column headers
- Row hover: `hover:bg-surface-1`
- Row separators: `border-edge-subtle`
- Status dots: `.status-dot` with solid color (no box-shadow glow)

### Metrics Strip

Stats rendered as a horizontal row in a single container (`bg-surface-1 border border-edge`). Stats separated by `border-l border-edge-subtle`. Each stat: `.metric-label` on top, `.metric-value` below. No individual card borders, no per-stat icons.

### Filter Bars

**Dense multi-item (9+ items, wraps)**: `rounded-full` pills. Active: `border-accent-primary-dim/40 bg-accent-primary-wash text-fg`. Inactive: `border-edge bg-transparent text-fg-faint`.

**Few items (2-3)**: Flat underline tabs. Active: `border-b-2 border-accent-primary-dim text-fg`. Inactive: `border-b-2 border-transparent text-fg-faint`.

### Command Palette

Sharp panel with dim lime border (`border-accent-primary-dim/40`). Positioned at `mt-[20vh]`. Group headers use `.section-label`. Kbd badges use `rounded-[2px]`.

## Animation

All animations are defined in `dashboard/src/app.css` and respect `prefers-reduced-motion`.

### fade-in-up

Subtle entry animation (4px translateY, 400ms duration). Staggered via `animation-delay`.

### fade-in

Opacity-only fade (300ms). For secondary elements.

### Reduced Motion

All animations and transitions collapse to 0.01ms.

## Anti-Patterns (Banned)

These patterns are explicitly banned:

1. **Colored glow shadows** -- no `box-shadow` with accent colors on cards
2. **Status dot glows** -- solid circles only, no `box-shadow`
3. **Top-edge colored borders on cards** -- use left-accent or full-border hover
4. **Pill-shaped primary buttons** -- use `rounded-[2px]`
5. **Monospace section labels** -- use `.section-label` (sans-serif)
6. **Gradient hover overlays on cards** -- use border-color transitions
7. **Noise/grain texture overlays** -- removed entirely
8. **Pulsing animations** -- removed entirely

## Token Source

All design tokens live in `dashboard/src/app.css`:

- **`@theme` block** -- Tailwind CSS v4 custom theme tokens (fonts, colors, surfaces, borders)
- **`@theme inline` block** -- Bridge from shadcn-svelte CSS variables to Tailwind tokens
- **`:root` block** -- shadcn-svelte CSS variable values
- **Utility classes** -- `.section-label`, `.metric-value`, `.metric-label`, `.status-dot`, `.active-border`, `.card-surface`, `.card-surface-error`, `.scrollbar-none`, `.animate-fade-in-up`, `.animate-fade-in`
- **SvelteFlow overrides** -- Custom CSS variables for dark mode canvas, minimap, controls
