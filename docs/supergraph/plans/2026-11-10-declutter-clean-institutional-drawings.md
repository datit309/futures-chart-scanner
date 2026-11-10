# Plan: Declutter & Clarify Institutional Chart Drawings (Zero Overlap)

## Problem Statement
The user explicitly pointed out: "CÁC đường vẽ, ký hiệu chồng chéo nhau khó nhìn quá" (The drawn lines, symbols are overlapping and messy, very hard to read!).
Root cause analysis of the screenshot:
1. **BOS / CHoCH Stacking**: 6 structure break lines were extending into future time `time_end + 3600*2` with `showLabel: true`. Because multiple breaks shared similar price and time coordinates, the text labels (`BOS`, `CHoCH`, `CHoCH`...) rendered directly on top of each other into an unreadable clump `BOSCHoCHCHoCH` right over the current candles.
2. **Order Block Clutter**: Multiple historical unmitigated blocks were rendered across all price levels, overlapping each other and cluttering the chart.
3. **Trendline Crosses**: 2 opposing trendlines intersected right through the candles at current market price.
4. **Text Positioning**: Lines extending past the breakout bar into the live candle area obscured real-time candle wicks and bodies.

## Professional Institutional Solution (LuxAlgo SMC Standard)
1. **BOS & CHoCH (Strict Separation & Finite Span)**:
   - Line connects from the `swing point` directly to the `breakout bar` (`time_start` -> `time_end`), stopping at the break bar! It does **NOT** project into the future over live candles.
   - Filter down to at most **2 most recent structure breaks** (e.g. 1 BOS and 1 CHoCH), so lines never stack.
   - Elegant styling: 1px subtle dashed line with a clean non-overlapping badge.
2. **Order Blocks (Nearest 1 Demand + 1 Supply Only)**:
   - Only render the **single closest Unmitigated Demand Block (below current price)** and the **single closest Unmitigated Supply Block (above current price)**.
   - Eliminate redundant stacked boxes.
   - Keep translucent 10% fill with thin 1px border.
3. **Clean Trendlines**:
   - Limit to the **1 most active, relevant trendline** (or broken line if active signal).
4. **Position Tool**:
   - Clean Long/Short Position Box rendered on active signal without obstructing historical bars.
5. **Overlay Controls Defaults**:
   - Keep defaults clean, giving the user full toggle control.

## Tasks
- **Task 1:** Update `technical_engine.py` to filter `structure_breaks` to the latest 2 distinct shifts, and filter `order_blocks` to nearest 1 Demand + 1 Supply.
- **Task 2:** Update `formatStructureBreakShape` in `static/chart_stream.js` so line terminates precisely at `time_end` (breakout candle).
- **Task 3:** Update `renderTradingViewDrawings` in `static/index.html` to prevent overlap and ensure clean aesthetic.
- **Task 4:** Unit test verification and browser live QA screenshot inspection.
