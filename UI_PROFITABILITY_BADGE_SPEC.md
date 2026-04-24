# UI 'Profitability Verified' Badge Specification

## Design System Specification

### Component Name
**ProfitabilityVerifiedBadge**

### Component Type
Status indicator / Confirmation badge

---

## Visual Design Specifications

### Primary Badge (Desktop/Web)

#### Dimensions
- **Width**: Auto (content-based, typically 220-280px)
- **Height**: 48px (compact), 72px (expanded with details)
- **Border Radius**: 8px
- **Position**: Fixed, top-right corner
  - Desktop: `top: 60px, right: 20px`
  - Mobile: `top: 50px, right: 10px, left: 10px`

#### Colors (Light Mode)

**Success State (Verified)**
```
Primary Background: linear-gradient(135deg, #10b981 0%, #059669 100%)
Secondary Background: rgba(16, 185, 129, 0.1)
Border: 4px solid #34d399 (left edge)
Text: #ffffff
Icon Background: rgba(255, 255, 255, 0.2)
Button Background: rgba(255, 255, 255, 0.2)
Button Hover: rgba(255, 255, 255, 0.3)
Shadow: 0 4px 12px rgba(16, 185, 129, 0.3)
```

**Failed State (Not Profitable)**
```
Primary Background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%)
Secondary Background: rgba(239, 68, 68, 0.1)
Border: 4px solid #f87171 (left edge)
Text: #ffffff
Icon Background: rgba(255, 255, 255, 0.2)
Error Background: rgba(0, 0, 0, 0.2)
Shadow: 0 4px 12px rgba(239, 68, 68, 0.3)
```

#### Colors (Dark Mode)
```
Success Background: linear-gradient(135deg, #059669 0%, #047857 100%)
Failed Background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%)
Text: #ffffff (same as light mode)
```

#### Typography
```
Badge Title: 
  - Font Family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto
  - Font Size: 15px
  - Font Weight: 600 (Semi-bold)
  - Letter Spacing: 0.3px
  - Line Height: 20px

Exchange Label:
  - Font Size: 12px
  - Font Weight: 500 (Medium)
  - Letter Spacing: 0.2px

Details Text:
  - Font Size: 13px
  - Font Weight: 400 (Regular)
  - Line Height: 1.6 (20.8px)

Detail Labels:
  - Font Weight: 500 (Medium)
  - Opacity: 0.9

Detail Values:
  - Font Weight: 600 (Semi-bold)
  - Background: rgba(255, 255, 255, 0.15)
  - Padding: 2px 8px
  - Border Radius: 4px
```

#### Icons
```
Success Icon: ✓ (Unicode U+2713)
  - Size: 20px
  - Font Weight: Bold
  - Circular background: 28px × 28px
  - Border Radius: 50%

Failed Icon: ⚠ (Unicode U+26A0)
  - Size: 20px
  - Font Weight: Bold
  - Same background styling
```

---

## Component States

### State 1: Compact (Initial Display)
```
┌─────────────────────────────────────────┐
│ ✓  Profitability Verified  [COINBASE] ▼│
└─────────────────────────────────────────┘
```

**Layout:**
- Icon (left): 28px circle with checkmark
- Text (center): "Profitability Verified"
- Exchange badge (right-center): Rounded pill with exchange name
- Toggle button (right): "Details ▼"

### State 2: Expanded (With Details)
```
┌─────────────────────────────────────────┐
│ ✓  Profitability Verified  [COINBASE] ▲│
├─────────────────────────────────────────┤
│ Risk/Reward Ratio:        1.83:1       │
│ Net Reward:               +4.40%       │
│ Net Risk:                 -2.40%       │
│ Breakeven Win Rate:       35.3% ✓      │
│ Round-Trip Fees:          1.60%        │
└─────────────────────────────────────────┘
```

**Layout:**
- Details section slides in with smooth animation (0.3s ease)
- Separator line between header and details
- Two-column layout for detail rows:
  - Left column: Label (aligned left)
  - Right column: Value (aligned right, highlighted background)
- Bottom padding: 12px

### State 3: Failed Validation
```
┌─────────────────────────────────────────┐
│ ⚠  Profitability Check Failed [COINBASE]│
├─────────────────────────────────────────┤
│ Profit targets too low for exchange    │
│ fees. Increase to 2.5%+ or use Kraken.  │
└─────────────────────────────────────────┘
```

**Layout:**
- Warning icon instead of checkmark
- Red gradient background
- Error message in dark overlay box
- No details toggle (always shows error)

### State 4: Faded (After 10 seconds)
```
Same as State 1, but with:
- Opacity: 0.7
- Transition: opacity 0.5s ease-out
- Still interactive on hover (returns to opacity: 1.0)
```

---

## Animations

### Entry Animation
```css
@keyframes slideInFromRight {
  from {
    transform: translateX(400px);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

Animation: slideInFromRight 0.5s ease-out
```

### Expansion Animation
```css
Details panel:
  max-height: 0 → 200px
  opacity: 0 → 1
  padding: 0 → 15px
  transition: all 0.3s ease-in-out
```

### Hover Effects
```css
Button hover:
  background: rgba(255, 255, 255, 0.2) → rgba(255, 255, 255, 0.3)
  transition: background 0.2s ease

Badge hover (when faded):
  opacity: 0.7 → 1.0
  transition: opacity 0.2s ease
```

---

## Responsive Breakpoints

### Desktop (≥1024px)
```
Position: top: 60px, right: 20px
Width: auto (220-280px)
z-index: 1000
```

### Tablet (768px - 1023px)
```
Position: top: 55px, right: 15px
Width: auto (200-260px)
z-index: 1000
```

### Mobile (≤767px)
```
Position: top: 50px, left: 10px, right: 10px
Width: calc(100% - 20px)
max-width: 400px
z-index: 1000
Font sizes: -1px reduction
Padding: 10px 16px (reduced)
```

---

## Accessibility Specifications

### ARIA Attributes
```html
<div 
  role="status" 
  aria-live="polite" 
  aria-label="Profitability verification status: verified"
  class="profitability-badge verified">
  ...
</div>
```

### Keyboard Navigation
```
Tab: Focus on Details button
Enter/Space: Toggle details panel
Esc: Collapse details panel (if expanded)
```

### Screen Reader Support
```
Verified: "Profitability verified for Coinbase exchange. 
           Risk reward ratio 1.83 to 1. Press Enter for details."

Failed: "Profitability check failed for Coinbase exchange. 
         Profit targets too low. Press Enter for recommendations."
```

### Color Contrast
```
Success state: 
  - Text (#ffffff) on green (#10b981): 4.5:1 ✓ WCAG AA
  
Failed state:
  - Text (#ffffff) on red (#ef4444): 4.5:1 ✓ WCAG AA

All text meets WCAG AA standards for readability
```

---

## Interactive Behavior

### User Actions

**Click "Details ▼" button:**
1. Rotates arrow to ▲
2. Expands details section (0.3s animation)
3. Shows profitability metrics
4. Updates aria-expanded="true"

**Click "Details ▲" button:**
1. Rotates arrow to ▼
2. Collapses details section (0.3s animation)
3. Hides profitability metrics
4. Updates aria-expanded="false"

**Hover over badge (when faded):**
1. Opacity returns to 1.0
2. Smooth transition (0.2s)

**Click outside badge:**
- No action (badge stays visible)

**Page scroll:**
- Badge remains fixed in position
- Does not scroll with page content

---

## Mobile-Specific Adaptations

### Touch Targets
```
Minimum touch target size: 44px × 44px (Apple HIG)
Details button: 48px × 36px (larger than minimum)
Padding around touchable elements: 8px minimum
```

### Gestures
```
Tap: Expand/collapse details (same as click)
Swipe right: Dismiss badge temporarily (returns on page reload)
Long press: Show tooltip with additional info
```

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  .profitability-banner {
    animation: none;
    transition: opacity 0.2s ease;
  }
  
  .banner-details {
    transition: none;
  }
}
```

---

## Component Variants

### Variant 1: Minimal (for compact displays)
```
┌───────────────────────┐
│ ✓ Verified [COINBASE] │
└───────────────────────┘

Width: 180px
Height: 40px
No details toggle
Hover shows tooltip with key metrics
```

### Variant 2: Inline (for settings pages)
```
┌─────────────────────────────────────────────────────────┐
│ ✓ Profitability Verified | R/R: 1.83:1 | Fees: 1.60%   │
└─────────────────────────────────────────────────────────┘

Display: inline-block
Background: Subtle (0.1 opacity gradient)
Border: 2px solid green
Padding: 8px 16px
```

### Variant 3: Toast Notification (temporary)
```
Appears bottom-center for 5 seconds after validation
Slides up from bottom
Auto-dismisses after 5s
User can click to dismiss early
```

---

## Integration Examples

### React Component
```jsx
<ProfitabilityBadge
  status="verified"
  exchange="COINBASE"
  metrics={{
    rrRatio: 1.83,
    netReward: 4.40,
    netRisk: 2.40,
    breakevenWr: 35.3,
    fees: 1.60
  }}
  variant="default"
  position="top-right"
  autoFade={true}
  fadeDelay={10000}
/>
```

### HTML/CSS (Pure)
```html
<div class="profitability-banner verified">
  <!-- Content as specified above -->
</div>
```

### Vue Component
```vue
<ProfitabilityBadge
  :verified="true"
  exchange="COINBASE"
  :metrics="profitabilityMetrics"
  @details-toggle="handleToggle"
/>
```

---

## Z-Index Layer
```
Layer: Notification/Status (z-index: 1000)
Above: Main content, modals (z-index: 1-999)
Below: Tooltips, popovers (z-index: 1001+)
```

---

## Print Styles
```css
@media print {
  .profitability-banner {
    position: static !important;
    page-break-inside: avoid;
    box-shadow: none;
    border: 2px solid #10b981;
  }
}
```

---

## Performance Considerations

### Rendering
- Use CSS transforms for animations (GPU accelerated)
- Avoid layout thrashing (use transform, opacity only)
- Lazy load details content until expanded

### Bundle Size
- Inline critical CSS
- Async load animation libraries if needed
- Total component size: <5KB (gzipped)

---

## Design Rationale

### Why Green?
- Universal color for "success" and "verified"
- High contrast with white text
- Positive emotional association
- Distinct from error states (red)

### Why Top-Right?
- Out of primary content flow
- Easily visible without obscuring main UI
- Standard position for notifications
- Mobile-friendly (doesn't block navigation)

### Why Expandable?
- Reduces visual clutter
- Progressive disclosure of information
- Users can get details when needed
- Maintains clean interface

### Why Auto-Fade?
- Reduces visual fatigue
- Non-intrusive after initial display
- Still accessible on hover
- Balances visibility and cleanliness
