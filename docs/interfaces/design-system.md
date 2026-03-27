# Design System -- "Electric Charcoal"

The dashboard's visual identity is called "Electric Charcoal." It is dark-only, designed to feel like mission control for AI agents -- powerful, electric, alive. Not safe, not corporate.

**The anchor**: Electric lime (#c8ff00) on warm charcoal. Immediately distinctive.

**The constraint**: Binary border-radius. Elements are either perfectly sharp (0px) or fully round (pill). No middle ground.

## Color System

All colors are defined as CSS custom properties in `dashboard/src/app.css` inside the `@theme` block using OKLCH notation.

### 60-30-10 Distribution

- **60%** -- Charcoal surfaces (background, cards, panels)
- **30%** -- Text hierarchy (white through warm grays)
- **10%** -- Accent colors (lime, cyan) + status colors

### Accent Colors

| Token | OKLCH | Hex (approx) | Usage |
|-------|-------|-------------|-------|
| `--color-accent-primary` | `oklch(0.91 0.20 128)` | #c8ff00 | Primary CTAs, active nav, tool type names, focus rings |
| `--color-accent-primary-hover` | `oklch(0.95 0.18 128)` | -- | Hover state for primary buttons |
| `--color-accent-primary-muted` | `oklch(0.91 0.20 128 / 0.15)` | -- | Tinted backgrounds (active nav item) |
| `--color-accent-secondary` | `oklch(0.82 0.14 195)` | #00e5ff | Trigger type names, secondary highlights |
| `--color-accent-secondary-muted` | `oklch(0.82 0.14 195 / 0.12)` | -- | Tinted backgrounds for secondary accent |

### Surface Scale

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-surface-0` | `#0e0e10` | Page background, deepest layer |
| `--color-surface-1` | `#161618` | Cards, sidebar, elevated surfaces |
| `--color-surface-2` | `#1e1e22` | Hover states, active toggles |
| `--color-surface-3` | `#2a2a30` | Focus outlines, tertiary surfaces |

### Text Hierarchy

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-fg` | `#f0f0f0` | Primary text, headings, active labels |
| `--color-fg-muted` | `#c0c0c8` | Secondary text, descriptions, data values |
| `--color-fg-faint` | `#70707c` | Tertiary text, section headers, placeholders, disabled |

### Borders

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-edge` | `#2a2a30` | Primary borders on cards, tables, inputs |
| `--color-edge-subtle` | `#1e1e22` | Inner dividers, table row separators |

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
| Data / Code | IBM Plex Mono | 400, 500 | Agent names, stat numbers, code blocks, metadata labels, monospace data |

### Type Scale

| Element | Size | Weight | Tracking | Example |
|---------|------|--------|----------|---------|
| Page title (h1) | `text-xl` (20px) | `font-semibold` (600) | `-0.02em` | "Launchpad", "Agents" |
| Section header | `text-[12px]` | `font-medium` (500) | `0.1em` | "TOP AGENTS", "TOOLS" (mono, uppercase) |
| Stat number | `text-[22px]` | `font-semibold` (600) | `-0.02em` | "1,234" (mono, tabular-nums) |
| Body text | `text-[13px]` | `font-normal` (400) | default | Descriptions, prompts |
| Small label | `text-[12px]` | `font-medium` (500) | `0.1em` | Drawer metadata labels (mono, uppercase) |
| Badge / tag | `text-[12px]` | `font-normal` (400) | default | Feature pills, tag filters (mono) |

### Rules

- Use `font-variant-numeric: tabular-nums` on all numeric data (stat cards, table columns, durations, token counts)
- Use `text-wrap: balance` on multi-line headings
- Monospace (`font-mono`) for: agent names, model identifiers, file paths, config values, stat numbers, section headers, table data

## Border Radius

The binary rule eliminates the generic look of uniform medium radii.

### Sharp (0px)

Applied via `--radius: 0rem` in `:root`. All shadcn components inherit this automatically.

- Cards and panels (`card-surface`, config sections)
- Input fields, textareas, select dropdowns
- Table containers
- Command palette panel
- Sidebar
- Drawer panels
- Code blocks and pre elements
- Skeleton loading placeholders

### Pill (`rounded-full`)

Applied explicitly on each element.

- Primary and secondary buttons
- Tag filter buttons
- View mode toggle (outer container + inner items)
- Status badge/chip elements
- Kbd hint badges (ESC, arrow keys)
- Tool count badges
- Scrollbar thumb

### Exception

Danger/destructive buttons stay sharp (no `rounded-full`). The angular shape is a deliberate visual signal that the action is different and irreversible.

## Surface Treatments

### Card Surface

The `.card-surface` utility creates a border with a lime-tinted top edge, mimicking light reflecting off a surface.

```css
.card-surface {
  border: 1px solid #2a2a30;
  border-top-color: oklch(0.91 0.20 128 / 0.15);
}
.card-surface:hover {
  border-top-color: oklch(0.91 0.20 128 / 0.30);
}
```

Used on: stat cards, agent flow nodes, top-agents bars, doctor check items, starter template cards.

### Card Surface -- Error Variant

The `.card-surface-error` utility adds a red left border accent while preserving the lime top tint (dimmed). Used on agent nodes with load errors.

```css
.card-surface-error {
  border: 1px solid #2a2a30;
  border-top-color: oklch(0.91 0.20 128 / 0.10);
  border-left: 2px solid var(--color-fail);
}
.card-surface-error:hover {
  border-top-color: oklch(0.91 0.20 128 / 0.20);
}
```

### Noise Grain

A full-viewport SVG fractal noise overlay at 4.5% opacity with `mix-blend-mode: soft-light`. Applied as a `body::after` pseudo-element with `pointer-events: none` and `z-index: 9999`.

### Glow Utilities

| Class | Effect | Usage |
|-------|--------|-------|
| `.glow-lime` | 20px lime box-shadow + inset top highlight | Stream output while running |
| `.glow-cyan` | 16px cyan box-shadow + inset top highlight | Reserved for secondary accent states |
| `.glow-lime-subtle` | 1px lime outline glow | Subtle emphasis |

### Hover Gradient Wash

Agent cards use a `::after` pseudo-element (or Svelte conditional div) that applies a diagonal lime gradient on hover:

```
bg-gradient-to-br from-accent-primary/[0.04] via-transparent to-transparent
```

The gradient is invisible by default and fades in with `opacity-0 group-hover:opacity-100`.

## Animation

All animations are defined in `dashboard/src/app.css` and respect `prefers-reduced-motion`.

### fade-in-up

Staggered card entry animation. Each card in a set receives an increasing `animation-delay` (0ms, 60ms, 120ms, 180ms).

```css
@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.animate-fade-in-up { animation: fade-in-up 0.3s ease-out both; }
```

Used on: stat strip cards (Launchpad, Audit).

### glow-pulse

Breathing lime glow for active/streaming states.

```css
@keyframes glow-pulse {
  0%, 100% { box-shadow: 0 0 16px oklch(0.91 0.20 128 / 0.08); }
  50%      { box-shadow: 0 0 24px oklch(0.91 0.20 128 / 0.18); }
}
.animate-glow-pulse { animation: glow-pulse 2s ease-in-out infinite; }
```

Used on: StreamOutput container while an agent is running.

### Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### Transition Rules

- Always list explicit properties: `transition-[color,background-color] duration-150`
- Never use `transition: all`
- Only animate `transform` and `opacity` for GPU compositing (except `box-shadow` for glow effects)
- Standard duration: `150ms` for micro-interactions, `200ms` for border/shadow transitions

## Component Patterns

### Buttons

| Variant | Classes | Notes |
|---------|---------|-------|
| Primary | `rounded-full bg-accent-primary text-surface-0 px-6 py-2.5 font-medium` | Dark text on lime. Lime glow shadow on hover. |
| Secondary | `rounded-full border border-edge bg-surface-1 text-fg-muted` | Outline pill. Lime border tint on hover. |
| Danger | Sharp (no rounded-full), `border border-fail text-fail` | Angular shape signals irreversibility. |

### Inputs

Sharp corners (0px). Focus state: `focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]` (lime border + lime glow ring).

### Tables

- Container: sharp, `border border-edge`
- Header row: `border-b-2 border-edge` (double-weight for emphasis)
- Header text: `text-[12px] tracking-[0.1em]` uppercase mono
- Row hover: `hover:bg-accent-primary/[0.03]` (faintest lime tint)
- Status dots in first column: `shadow-[0_0_4px_var(--color-ok)]` or `--color-fail`

### Sidebar Navigation

Active item uses a background tint (`bg-accent-primary/10 text-accent-primary`) instead of the traditional border-left indicator. A faint lime gradient line decorates the top of the sidebar's right edge.

**Collapsible groups**: The sidebar supports collapsible nav groups (e.g. "Orchestration" containing Compose and Teams). The group header is a `<button>` with a `ChevronRight` indicator that rotates 90deg when open. When a child route is active, the group is pinned open (toggle is inert) and the group header receives `text-accent-primary` without background tint, while the active child gets the full `bg-accent-primary/10 text-accent-primary` treatment. Children are indented via a `ml-3` (12px) wrapper. Open/closed state persists to localStorage via `safeGet`/`safeSet`.

**Collapsed flyout**: In icon-only mode (48px width), groups render as a single icon button. On hover or focus, a sharp flyout (`border-edge bg-surface-1 shadow-lg`) appears with a mono uppercase section header (`text-[11px] tracking-[0.12em]`) and child links. Focus management keeps the flyout open while focus moves between its children and closes on blur outside.

### Agent Picker

Inline searchable dropdown for selecting agents in compose and team builders (`AgentPicker.svelte`). Sharp-cornered trigger and dropdown panel. Trigger shows selected agent name + model pill badge when set; when unset, shows `noneLabel` if provided (e.g. "Generate placeholder"), otherwise the `placeholder` text, with a chevron. Dropdown panel (`role="listbox"`, `tabindex="0"`): search input at top, scrollable agent list with name (mono 13px), description (12px faint, truncated), model pill (mono 10px), and up to 3 feature pills with "+N" overflow. Highlight: `bg-accent-primary/[0.06]`. Selected: left border accent + tinted background. Keyboard: arrow keys navigate, Enter selects, Escape closes. Click-outside closes via window click handler.

### Command Palette

Sharp panel with faint lime border (`border-accent-primary/10`). Selected item: `bg-accent-primary/[0.08]`. Kbd badges use `rounded-full`. Group headers: `text-[11px] tracking-[0.12em]`.

### Scope Badge

Pill badge (`rounded-full`) for skill scope classification (`ScopeBadge.svelte`). Uses the same structural pattern as capability filter pills: `border px-2 py-0.5 font-mono text-[12px]`. Color varies by scope to convey resolution priority:

| Scope | Color treatment | Rationale |
|-------|----------------|-----------|
| `role-local` | `border-accent-secondary/30 bg-accent-secondary/10 text-accent-secondary` | Cyan = closest to agent, highest priority |
| `project` | `border-accent-primary/30 bg-accent-primary/10 text-accent-primary` | Lime = project-level shared resource |
| `extra` | `border-warn/30 bg-warn/10 text-warn` | Amber = externally provided |
| `user` | `border-edge bg-surface-1 text-fg-faint` | Muted outline = global default |

Always includes a text label (never color alone).

### Seed Avatar

Deterministic identity avatar for conversation thread turns (`SeedAvatar.svelte`). Uses DiceBear Rings style (`@dicebear/core` + `@dicebear/rings`) to generate concentric ring patterns from a seed string. The same seed always produces the same avatar.

**Container**: `rounded-full overflow-hidden shrink-0`, 24px default, `aria-hidden="true"` (adjacent label conveys identity).

**Color palette**: Constrained to 6 colors drawn from the design system:

| Color | Hex | Source |
|-------|-----|--------|
| Electric lime | `c8ff00` | accent-primary |
| Muted teal | `6ec8b1` | desaturated accent-secondary |
| Warm mid-gray | `8b8b99` | fg-muted range |
| Cool charcoal | `5a5a6a` | surface-3 range |
| Desaturated blue | `a0c4ff` | info hue family |
| Warm amber | `d4a574` | warn hue family |

**Background**: `161618` (surface-1) so ring patterns sit on matching ground.

**Seeding**: User turns seed from `"You"`. Agent turns seed from the agent name (regular runs), active service name (compose), or active persona name (team). In compose/team streaming, the avatar swaps to reflect the currently active sub-agent.

**Scope**: Only used in `ConversationThread`. Not used in nav, launchpad, agent cards, or other surfaces.

### Requirement Indicator

Compact status dot with tooltip (`RequirementIndicator.svelte`). Green (`bg-ok`) dot with `box-shadow: 0 0 4px var(--color-ok)` when all requirements are met; amber (`bg-warn`) when some are unmet. Accompanied by mono `text-[12px] text-fg-faint` count text (e.g. "2/3 met"). Tooltip lists each requirement with check/cross marks. Hidden when no requirements exist.

## Token Source

All design tokens live in `dashboard/src/app.css`:

- **`@theme` block** -- Tailwind CSS v4 custom theme tokens (fonts, colors, surfaces)
- **`@theme inline` block** -- Bridge from shadcn-svelte CSS variables to Tailwind tokens
- **`:root` block** -- shadcn-svelte CSS variable values (background, foreground, primary, etc.)
- **Utility classes** -- `.card-surface`, `.card-surface-error`, `.glow-lime`, `.glow-cyan`, `.glow-lime-subtle`, `.scrollbar-none`, `.animate-fade-in-up`, `.animate-glow-pulse`
- **SvelteFlow overrides** -- Custom CSS variables for dark mode canvas, minimap, controls, background dots, and node dimming (`.svelte-flow__node.dimmed`)

To change the color scheme, update the `@theme` and `:root` blocks. All components reference tokens by name, not hardcoded values.
