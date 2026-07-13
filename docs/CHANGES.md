# BitFit Meteorite — Frontend Visual Overhaul & Google OAuth Integration

## Summary

This document describes the changes delivered on branch `feat/ui-design-system` (commits `9fcc5e1` and `392f369`). The work transforms the frontend from a functional-but-plain health dashboard into a visually stunning, motion-rich experience with a dark-mode-first design system, while also adding Google Health OAuth connectivity and manual sync controls.

---

## 1. Design System Overhaul

### 1.1 Dark Mode First
- Default theme switched from light to dark (`--background: #0a0a0f`)
- Light mode preserved via `data-theme="light"` toggle
- All color tokens updated for dark-mode readability

### 1.2 Typography
- **Inter font** replaces Arial/Helvetica system stack
- `-webkit-font-smoothing: antialiased` for crisp rendering on macOS

### 1.3 Glass Card System
- Enhanced `glass-card` with smoother hover transitions
- `glass-card-strong` variant for elevated content
- **Spotlight hover effect** — mouse-following radial gradient on cards (CSS custom properties updated on `mousemove`)
- **Noise texture overlay** — subtle SVG noise pattern at 2.5% opacity for tactile premium feel

### 1.4 Animation Tokens
```css
--ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
--ease-out-back: cubic-bezier(0.34, 1.56, 0.64, 1);
--duration-fast: 150ms;
--duration-normal: 300ms;
--duration-slow: 500ms;
```

### 1.5 Metric Colors (Inspired by Velovories / Zürich Card)
Each health signal gets a unique, saturated hue:

| Metric | Color | CSS Variable |
|--------|-------|-------------|
| Steps | Amber | `--metric-steps` |
| Resting Heart Rate | Red | `--metric-resting_heart_rate` |
| Deep Sleep | Indigo | `--metric-sleep_deep_minutes` |
| REM Sleep | Purple | `--metric-sleep_rem_minutes` |
| Total Sleep | Blue | `--metric-sleep_minutes` |
| HRV | Teal | `--metric-hrv` |
| SpO2 | Cyan | `--metric-spo2` |
| Weight | Orange | `--metric-weight` |

---

## 2. New Dependencies

```json
{
  "framer-motion": "^12.42.2",
  "gsap": "^3.15.0",
  "@gsap/react": "^2.1.2"
}
```

All animation libraries are tree-shakeable and lazy-loaded in client components only.

---

## 3. New Shared Components

### `app/components/AnimatedPage.tsx`
- `AnimatePresence` wrapper for route-level page transitions
- Fade + Y-translate + scale on enter/exit
- Uses `mode="wait"` to prevent overlapping animations

### `app/components/AnimatedCounter.tsx`
- Count-up animation from 0 to target value
- `easeOutExpo` easing via `requestAnimationFrame`
- Triggers on `useInView` (Framer Motion) — only animates when scrolled into viewport
- Supports decimals, prefix, suffix

### `app/components/SkeletonCard.tsx`
- Shimmer loading placeholder with CSS keyframe animation
- Used in SessionGate loading state

### `app/components/Toast.tsx`
- Global toast notification system
- `showToast(message, type, duration)` API
- Types: `info`, `success`, `warning`, `error`
- Auto-dismiss after 3 seconds

### `app/components/TypingIndicator.tsx`
- Wave-style bouncing dots (3 dots, staggered animation)
- Replaces Tailwind's `animate-bounce` with custom `typing-bounce` keyframe

### `app/components/AmbientBackground.tsx`
- Canvas 2D floating blob background
- 4 slowly drifting radial gradients (indigo, purple, amber, green)
- No external assets — pure Canvas rendering
- Resizes with window

---

## 4. Page-by-Page Changes

### 4.1 Home Page (`/`)
**Before:** Plain status card with colored dot.
**After:**
- Living hero section with gradient text ("Your body, **in signals.**")
- Animated connection badge with orbital rings around the status dot
- Feature cards (Trends, Anomalies, Chat) with staggered entrance animations
- Each card has unique color accent matching its function
- Spotlight hover effect on all cards

### 4.2 Login Page (`/login`)
**Before:** Plain form on white background.
**After:**
- Full-screen **mesh gradient** background with animated floating orbs
- Glass card entrance animation (scale 0.95 → 1, fade in)
- Spring-animated icon (✦) with `stiffness: 200, damping: 15`
- Glowing input focus states with `box-shadow` transition
- Submit button with hover glow using `color-mix` on `signal-active`

### 4.3 Dashboard (`/dashboard`)
**Before:** Static widget grid, plain cards, no motion.
**After:**
- **Staggered entrance** for header elements and widgets
- **Animated counter** for "signals loaded" count
- **Spotlight hover** on all widget cards (mouse-following gradient)
- **Motion layout** on WorkspacePanel cards for smooth reordering
- **Anomaly list** items animate in with stagger (`staggerChildren: 0.05`)
- **Google Health connection card** (see Section 6)
- All buttons have `whileHover={{ scale: 1.05 }}` and `whileTap={{ scale: 0.95 }}`

### 4.4 Chat Page (`/chat`)
**Before:** Static message list, basic bounce dots.
**After:**
- **Spring-animated message bubbles** — user messages slide from right, assistant from left
- **Wave typing indicator** — 3 dots with staggered `typing-bounce` animation
- **Evidence cards** slide in below assistant messages with 0.2s delay
- **Workspace proposals** animate in with 0.3s delay
- **Empty state** with spring-animated icon and staggered quick-prompt buttons
- **Error messages** animate in with `y: -8` entrance
- **Auto-scroll** with smooth behavior

### 4.5 Detail Page (`/dashboard/[metric]`)
**Before:** Static stat cards, plain table.
**After:**
- **Count-up animations** on stat cards (latest, baseline, delta)
- **Metric-colored title** — the page heading uses the signal's unique color
- **Table rows** stagger in with `delay: i * 0.03`
- **Back button** arrow animates on hover (`x: -4`)
- Chart section with delayed entrance (`delay: 0.3`)
- Raw data section with delayed entrance (`delay: 0.4`)

---

## 5. Component Changes

### 5.1 `WorkspacePanel.tsx`
- Added `motion.article` with `layout` prop for animated reordering
- `whileHover` lift effect (`y: -4`) when not in editing mode
- Spotlight hover via `onMouseMove` updating CSS custom properties
- Metric-colored `signal-mark` icon (background + text color from `panel.color`)
- `motion.button` on "Open detail" with scale feedback

### 5.2 `MetricChart.tsx`
- Re-enabled Recharts animations (`animationDuration: 800-1000ms`, `ease-out`)
- Added SVG **glow filter** — `feGaussianBlur` with `stdDeviation="3"` on line/area charts
- Enhanced gradient opacity (0.35 → 0 at bottom for area fills)
- `activeDot` styling with metric color
- Bar chart radius increased to `[4, 4, 0, 0]`

### 5.3 `FloatingUtilityDock.tsx`
- Slide-up entrance animation (`delay: 0.5s`)
- `motion.div` wrapper around each button with `whileHover={{ scale: 1.1 }}`
- Active state glow on dashboard/chat links
- Theme toggle uses `getAttribute`/`setAttribute` (avoids ESLint immutability error)

### 5.4 `SessionGate.tsx`
- Replaced plain "Loading…" text with **shimmer skeleton** (circular dot + text bar)
- `motion.div` with scale entrance animation

### 5.5 `layout.tsx`
- Added `AmbientBackground` component (z-index 0, behind all content)
- Added `ToastContainer` (fixed bottom, z-index 60)
- Updated metadata title to "BitFit Meteorite"

---

## 6. Google OAuth Integration

### 6.1 Backend: `GET /dashboard/connection`
New endpoint in `backend/app/routes/dashboard.py`:

```python
@router.get("/connection")
def connection_status() -> dict[str, Any]:
    """Return whether a Google Health OAuth token is stored and fresh."""
```

Returns:
```json
{
  "connected": true,
  "provider": "google_health",
  "token_fresh": true,
  "expires_at": "2026-07-13T12:00:00"
}
```

### 6.2 Frontend: Dashboard Header Card
Added next to the "Fitbit history" card:

- **Status indicator:** Orbital green dot when connected, red when not, yellow while loading
- **"Connect Google ↗" button:** Appears when `connected: false`. Redirects browser to `/auth/google/login` (backend handles OAuth flow)
- **"Sync now ↻" button:** Appears when `connected: true`. Triggers `POST /sync/run`
- **Sync result toast:** Animated slide-in showing either:
  - `"X records synced"` (green background)
  - Error message (red background)
- **Auto-refresh:** After sync, re-fetches metrics and connection status

### 6.3 Flow
```
User clicks "Connect Google" → Browser → GET /auth/google/login
                                    ↓
                              Google consent screen
                                    ↓
                              Callback → tokens stored encrypted
                                    ↓
User returns to dashboard → "Sync now" button visible
                                    ↓
User clicks "Sync now" → POST /sync/run → records synced
                                    ↓
                        Metrics auto-refresh → new data appears
```

---

## 7. Accessibility

- All animations respect `prefers-reduced-motion: reduce`
- When reduced motion is preferred:
  - All transitions collapse to `0.01ms`
  - All animations run once (`animation-iteration-count: 1`)
  - Noise texture overlay is hidden
- No layout shifts — all animations use `transform` and `opacity` only
- SSR-safe — all animation wrappers are `"use client"`

---

## 8. Verification

| Check | Command | Result |
|-------|---------|--------|
| Lint | `npm run lint` | ✅ Pass |
| Typecheck | `npx tsc --noEmit` | ✅ Pass |
| Build | `npm run build` | ✅ Pass |
| Backend tests | `pytest -q` | ✅ 38 passed |

---

## 9. Files Changed

### New files (17)
- `frontend/app/components/AnimatedPage.tsx`
- `frontend/app/components/AnimatedCounter.tsx`
- `frontend/app/components/SkeletonCard.tsx`
- `frontend/app/components/Toast.tsx`
- `frontend/app/components/TypingIndicator.tsx`
- `frontend/app/components/AmbientBackground.tsx`
- `frontend/app/FloatingUtilityDock.tsx`
- `frontend/app/dashboard/[metric]/page.tsx`
- `design/references/` (7 inspiration images)
- `.agents/skills/` (caveman/cavecrew skill files)
- `backend/tests/test_dashboard_raw.py`

### Modified files (15)
- `frontend/app/globals.css` — Full rewrite with animation system, dark mode, metric colors
- `frontend/app/layout.tsx` — AmbientBackground, ToastContainer, metadata
- `frontend/app/page.tsx` — Hero redesign with gradient text, feature cards
- `frontend/app/login/page.tsx` — Mesh gradient, glass card, glowing inputs
- `frontend/app/dashboard/page.tsx` — Staggered entrances, counters, OAuth card
- `frontend/app/dashboard/WorkspacePanel.tsx` — Motion layout, spotlight hover
- `frontend/app/dashboard/MetricChart.tsx` — Re-enabled animations, glow filter
- `frontend/app/dashboard/workspace.ts` — Unique metric colors
- `frontend/app/chat/page.tsx` — Spring messages, typing indicator, evidence cards
- `frontend/app/SessionGate.tsx` — Shimmer skeleton loading
- `frontend/app/LogoutButton.tsx` — Minor styling updates
- `frontend/package.json` — Added framer-motion, gsap, @gsap/react
- `backend/app/routes/dashboard.py` — Added /connection endpoint, raw data routes
- `docs/superpowers/specs/2026-07-12-bitfit-ui-design-system-design.md` — Updated

---

## 10. Design References

Inspiration images in `design/references/`:
- **Fonetika In Use** — Swiss typography, bold hierarchy
- **Geex Arts** — Card-based layouts, rounded corners, color blocking
- **New Standards for NYC Underground** — Information density, grid systems
- **Ongoing Pin** — Dark mode widgets, neon accents, data viz
- **Velovories** — Colorful metric cards, bold numbers, rounded shapes
- **Watch UI Pin** — Small sparklines, health data visualization
- **Zürich Card Revamp** — Rainbow color system, clean typography

---

*Document generated for Kimi swarm handoff. Branch: `feat/ui-design-system`*
