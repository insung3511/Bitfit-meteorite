# SIGNAL // TERMINAL — Design Specification

## Philosophy
Transform BitFit Meteorite from a soft glass-morphism health app into a **deep-space telemetry interface**. Your body is a spacecraft. This is mission control. Every pixel is precise, data-dense, and alive with subtle signal. The aesthetic is inspired by JPL mission control, NASA telemetry displays, and modern terminal interfaces — but rendered with contemporary polish.

## Color System

```css
:root {
  --bg-primary: #000000;
  --bg-surface: #050508;
  --bg-elevated: #0c0c12;
  --bg-input: #08080c;
  
  --text-primary: #e8e8f0;
  --text-secondary: #6b6b80;
  --text-muted: #3d3d52;
  --text-disabled: #2a2a3a;
  
  --border-subtle: rgba(255, 255, 255, 0.06);
  --border-default: rgba(255, 255, 255, 0.10);
  --border-active: rgba(0, 212, 255, 0.50);
  --border-glow: rgba(0, 212, 255, 0.20);
  
  --accent-cyan: #00d4ff;
  --accent-magenta: #ff006e;
  --accent-amber: #ffb703;
  --accent-green: #00f5d4;
  --accent-rose: #ff4d6d;
  --accent-violet: #9d4edd;
  
  --signal-good: #00f5d4;
  --signal-warn: #ffb703;
  --signal-danger: #ff4d6d;
  --signal-active: #00d4ff;
  
  --metric-steps: #ffb703;
  --metric-resting_heart_rate: #ff4d6d;
  --metric-sleep_deep_minutes: #00d4ff;
  --metric-sleep_rem_minutes: #9d4edd;
  --metric-sleep_minutes: #4361ee;
  --metric-hrv: #00f5d4;
  --metric-spo2: #00d4ff;
  --metric-weight: #ff9f1c;
  
  --viz-grid: rgba(255, 255, 255, 0.04);
  --viz-muted: #4a4a5e;
  --viz-axis: rgba(255, 255, 255, 0.08);
  --viz-surface: #050508;
  
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --duration-fast: 150ms;
  --duration-normal: 300ms;
  --duration-slow: 500ms;
}
```

## Typography
- UI font: 'Inter', system-ui, sans-serif
- Data font: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace
- Headlines: 700 weight, tight tracking (-0.02em to -0.04em)
- Labels: 10px, 700 weight, uppercase, 0.12em tracking, --text-secondary
- Numbers: ALWAYS monospace, tabular-nums

## Layout Architecture
- **Left sidebar**: Fixed 56px wide, full height, --bg-surface, border-right: 1px solid --border-subtle. Contains icon-only navigation buttons (20px icons). No text labels.
- **Main content**: margin-left: 56px, full remaining width. No floating dock.
- **No ambient canvas background**: Replaced with subtle dot-grid pattern.
- **Header area**: Slim, compact status bar at top of main content. Shows connection status, signal count, current page title.
- **Widget grid**: True CSS Grid bento layout with auto-fill. Gap: 12px.
- **Detail panel**: Right-side slide-out drawer for raw data (not bottom section).

## Component Styles

### Cards / Modules (`.module-card`)
```css
.module-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  transition: border-color var(--duration-normal) var(--ease-out-expo),
              box-shadow var(--duration-normal) var(--ease-out-expo);
}
.module-card:hover {
  border-color: var(--border-default);
  box-shadow: 0 0 20px rgba(0, 212, 255, 0.06), 0 0 60px rgba(0, 212, 255, 0.02);
}
.module-card-active {
  border-color: var(--border-active);
  box-shadow: 0 0 0 1px var(--border-active), 0 0 20px rgba(0, 212, 255, 0.08);
}
```
- NO backdrop-filter blur. Sharp and precise.
- NO large border-radius. 4px max.
- NO soft shadows. Only subtle glows on hover/active.

### Widget Cards (`.widget-module`)
```css
.widget-module {
  position: relative;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  overflow: hidden;
}
.widget-module::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--metric-color, var(--accent-cyan));
  opacity: 0.8;
}
.widget-module:hover {
  border-color: var(--border-default);
  box-shadow: 0 0 0 1px rgba(0, 212, 255, 0.10), 0 0 30px rgba(0, 212, 255, 0.04);
}
.widget-module-selected {
  border-color: var(--accent-cyan);
  box-shadow: 0 0 0 1px var(--accent-cyan), 0 0 30px rgba(0, 212, 255, 0.10);
  animation: module-pulse 2s ease-in-out infinite;
}
```
- Top-edge colored strip (3px) indicating metric type via `::before` pseudo-element
- Colored strip uses the metric's accent color
- Selected state has cyan border with subtle glow pulse

### Status Indicators (`.status-pip`)
```css
.status-pip {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 999px;
}
.status-pip-good { background: var(--signal-good); box-shadow: 0 0 0 3px rgba(0, 245, 212, 0.15); }
.status-pip-warn { background: var(--signal-warn); }
.status-pip-danger { background: var(--signal-danger); }
.status-pip-active { background: var(--accent-cyan); box-shadow: 0 0 0 3px rgba(0, 212, 255, 0.15); }
```

### Buttons (`.cmd-btn`, `.cmd-btn-primary`)
```css
.cmd-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  transition: all var(--duration-normal) var(--ease-out-expo);
}
.cmd-btn:hover {
  border-color: var(--border-default);
  color: var(--text-primary);
  background: var(--bg-elevated);
}
.cmd-btn-primary {
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
  background: rgba(0, 212, 255, 0.08);
}
.cmd-btn-primary:hover {
  background: rgba(0, 212, 255, 0.12);
  box-shadow: 0 0 15px rgba(0, 212, 255, 0.10);
}
```

### Inputs (`.cmd-input`)
```css
.cmd-input {
  width: 100%;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-input);
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.cmd-input:focus {
  border-color: var(--accent-cyan);
  box-shadow: 0 0 0 2px rgba(0, 212, 255, 0.10);
}
.cmd-input::placeholder { color: var(--text-muted); }
```

### Labels / Eyebrows (`.cmd-label`)
```css
.cmd-label {
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  line-height: 1.2;
  text-transform: uppercase;
}
```

### Sidebar (`.nav-rail`)
```css
.nav-rail {
  position: fixed;
  top: 0;
  left: 0;
  width: 56px;
  height: 100vh;
  background: var(--bg-primary);
  border-right: 1px solid var(--border-subtle);
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
  gap: 4px;
}
.nav-rail-btn {
  display: flex;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: var(--text-muted);
  font-size: 18px;
  transition: all var(--duration-normal) var(--ease-out-expo);
}
.nav-rail-btn:hover, .nav-rail-btn-active {
  color: var(--accent-cyan);
  background: rgba(0, 212, 255, 0.08);
}
```

### Grid Background (`.grid-bg`)
```css
.grid-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image: 
    radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0);
  background-size: 24px 24px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 70%);
  -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 70%);
}
```

### Tables (`.data-table`)
```css
.data-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
}
.data-table {
  min-width: 640px;
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
}
.data-table th {
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-align: left;
  text-transform: uppercase;
  font-weight: 700;
}
.data-table th, .data-table td {
  border-bottom: 1px solid var(--border-subtle);
  padding: 8px 10px;
  white-space: nowrap;
}
.data-table tr:hover td { background: var(--bg-elevated); }
.data-table tr:last-child td { border-bottom: 0; }
.data-table td { color: var(--text-secondary); }
.data-table td.mono { color: var(--text-primary); font-family: monospace; }
```

### Animations
```css
@keyframes module-pulse {
  0%, 100% { box-shadow: 0 0 0 1px var(--accent-cyan), 0 0 30px rgba(0, 212, 255, 0.10); }
  50% { box-shadow: 0 0 0 1px var(--accent-cyan), 0 0 40px rgba(0, 212, 255, 0.15); }
}
@keyframes signal-ping {
  0% { transform: scale(0.8); opacity: 0.7; }
  100% { transform: scale(2); opacity: 0; }
}
@keyframes boot-fade {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes scanline {
  0% { transform: translateY(-100%); }
  100% { transform: translateY(100vh); }
}
```

### Widget Grid
```css
.module-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.module-grid > .widget-large {
  grid-column: span 2;
}
@media (max-width: 768px) {
  .module-grid > .widget-large { grid-column: span 1; }
}
```

### Gradient Text (`.gradient-text`)
```css
.gradient-text {
  background: linear-gradient(135deg, var(--accent-cyan), var(--accent-violet));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
```

## Responsive
- Mobile: sidebar becomes bottom tab bar or hamburger menu. Main content full width.
- Widgets: stack vertically on small screens.

## Light Theme (data-theme="light")
NOT IMPLEMENTED. Dark only for this design.

## What to PRESERVE (Widget Concept)
- Widgets showing metrics with recharts (area/line/bar)
- Add/remove/reorder widgets
- Widget sizes: small/medium/large
- Chart types: area/line/bar
- Time ranges: 7/30/90 days
- Baseline toggle
- Workspace history/undo
- Drag and drop in edit mode
- Click to select widget
- Open detail page from widget
- All data fetching logic (useEffect, fetch, state management)
- All workspace state logic (localStorage, versioning)
- Metric catalog and definitions
- Google OAuth connection and sync
- Anomaly detection display
- Raw data table display
- Chat page functionality
- Login page functionality
- Session gating

## Files to Modify
1. `globals.css` — Complete rewrite with new design system
2. `layout.tsx` — Add sidebar, remove ambient background, remove floating dock wrapper
3. `app/components/Sidebar.tsx` — NEW: Left sidebar navigation component
4. `app/components/GridBackground.tsx` — NEW: Subtle dot-grid background
5. `app/page.tsx` — Redesigned landing page
6. `app/dashboard/page.tsx` — Complete restructure
7. `app/dashboard/WorkspacePanel.tsx` — New widget design
8. `app/dashboard/MetricChart.tsx` — Updated visual style
9. `app/chat/page.tsx` — New chat design
10. `app/login/page.tsx` — New login design
11. `app/FloatingUtilityDock.tsx` — Remove or repurpose (functionality moves to sidebar)
12. `app/components/AmbientBackground.tsx` — Remove from layout
13. `app/components/SkeletonCard.tsx` — Update skeleton style
