# Plan: Institutional Pro Trader Chart Drawings (BOS/CHoCH, Unmitigated OBs, Native Position Tool)

## Problem Statement
The user explicitly demanded: "nghiên cứu cách vẽ cho chuẩn dân trade xem, hiện tại nhìn chưa chuyên nghiệp" (Research how to draw properly for real traders to see, currently it still doesn't look professional).
Amateur chart traits identified:
1. Lone diagonal trendline cutting across bars with garish colors.
2. Cluttered, overlapping historical Order Blocks that were already penetrated/mitigated by price.
3. Infinite horizontal price lines spanning the entire screen width instead of the iconic TradingView Risk/Reward position box.
4. Complete absence of core Price Action / SMC milestones: BOS (Break of Structure) and CHoCH (Change of Character).

Professional trader standard:
1. **BOS & CHoCH Markers**: Horizontal dashed structural lines with neat labels `BOS` and `CHoCH` at swing levels where structure broke.
2. **Fresh / Unmitigated Order Blocks Only**: Exclude or clip Order Blocks once subsequent price action has traded through them (mitigated). Max 2-3 fresh zones. Clean pastel styling (12% fill, 1px border, `+OB [Demand]` / `-OB [Supply]` label).
3. **Native TradingView Long/Short Position Tool**: Replace full-screen order lines with TradingView's native `long_position` / `short_position` shape displaying the exact green target box, red stop loss box, entry level, and Risk/Reward ratio calculation.

## Architecture & Contracts
### 1. `technical_engine.py`
```python
@dataclass
class StructureBreak:
    type: str  # "BOS" or "CHOCH"
    price: float
    time_start: int
    time_end: int
    is_bullish: bool
    label: str

def detect_market_structure_shifts(self, klines: List[Dict[str, Any]], swings: List[SwingPoint]) -> List[Dict[str, Any]]:
    # Finds swing points where price broke past the swing level.
    # Returns list of dicts: {"type": "BOS"|"CHOCH", "price": float, "time_start": int, "time_end": int, "label": str, "is_bullish": bool}

def detect_order_blocks(self, klines: List[Dict[str, Any]], swings: List[SwingPoint], unmitigated_only: bool = True) -> List[Dict[str, Any]]:
    # Checks subsequent candles: if price touched/penetrated the OB, mark mitigated = True.
    # If unmitigated_only=True, filters out penetrated blocks.
```

### 2. `chart_stream.js`
```javascript
export function formatPositionShape(signal, lastCandle) {
  // Returns { shape: 'long_position'|'short_position', points, overrides }
}
export function formatStructureBreakShape(structureBreak) {
  // Returns { shape: 'trend_line', points, options with dashed line and BOS/CHOCH text }
}
```

### 3. `index.html`
- In `renderTradingViewDrawings(structure)`:
  - Render fresh unmitigated Order Blocks with clean opacity and borders.
  - Render BOS & CHoCH structure break dashed lines.
  - Render native `long_position` / `short_position` tool for active signal.

---

## Task 1: Unmitigated Order Blocks & BOS/CHoCH Detection in technical_engine.py (RED -> GREEN)
Wave: 1
Status: pending
Risk: low
Dependencies: none
Model: inherit

Files:
- Modify: `technical_engine.py`
- Modify: `tests/test_technical_engine.py`

Acceptance:
- `detect_order_blocks` tags `mitigated: bool` and filters for unmitigated zones.
- `detect_market_structure_shifts` detects valid BOS (continuation) and CHoCH (reversal) lines with timestamps and price levels.
- Unit tests verify mitigation checking and structure shift labeling.

## Task 2: Server Payload & Frontend Drawing Helpers in chart_stream.js (RED -> GREEN)
Wave: 2
Status: pending
Risk: low
Dependencies: Task 1
Model: inherit

Files:
- Modify: `server.py`
- Modify: `static/chart_stream.js`
- Modify: `tests/chart_stream.test.js`

Acceptance:
- `build_structure_payload` includes `structure_breaks: [...]` (BOS and CHoCH).
- `formatPositionShape` produces valid points and overrides for TradingView `long_position` / `short_position`.
- `formatStructureBreakShape` produces dashed line with `BOS` / `CHoCH` text.
- Unit tests pass.

## Task 3: TradingView Native Pro Drawings in static/index.html
Wave: 3
Status: pending
Risk: medium
Dependencies: Task 2
Model: pro

Files:
- Modify: `static/index.html`

Acceptance:
- `renderTradingViewDrawings` renders:
  - BOS and CHoCH lines with labels.
  - Fresh unmitigated Order Blocks with neat pastel colors.
  - Native `long_position` / `short_position` tool with R:R display.
- Removes obsolete screen-spanning order lines.
- Browser live QA verifies the chart looks clean, elegant, and institutional.

## Task 4: Browser Live Verification & QA Evidence
Wave: 4
Status: pending
Risk: low
Dependencies: Task 3
Model: pro

Files:
- Test: browser live verification via `agent-browser`

Acceptance:
- Verify BTCUSDT and ETHUSDT charts show clean BOS/CHoCH labels, fresh Order Blocks, and native green/red Position Tool.
- Capture screenshots as proof of institutional design quality.
