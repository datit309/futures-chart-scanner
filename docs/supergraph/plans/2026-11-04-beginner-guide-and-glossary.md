# Plan: Beginner Trader Cheat Sheet, Glossary Modal & Plain Vietnamese Signal Guide

## Problem Statement
The user explicitly stated: "nên thêm bảng chú thích chứ tao không hiểu gì cả, vì tao không biết trade" (Should add an explanation/legend panel, because I don't understand anything at all since I don't know how to trade).
Traders without financial background are overwhelmed by acronyms like `BOS`, `CHoCH`, `OB [Demand]`, `OB [Supply]`, `R:R 1:2.5`, `ADX`, `Mean Reversion`, `SL`, `TP`.
They need clear, non-technical, visual plain-Vietnamese guidance explaining:
1. **What each drawing on the chart actually means** (e.g. green box = whale buying zone, red box = whale dumping zone, dashed line BOS = price breaking out, dashed line CHoCH = market reversing).
2. **How to execute each trade** (Entry, Stop Loss, Take Profit, Risk/Reward calculation).
3. **Plain-Vietnamese human translations on every Signal Card** in the right feed so they immediately understand what the trade setup is doing without having to decode trading terms.

## Architecture & Components
1. **Plain Vietnamese Signal Translator** in `static/chart_stream.js`:
   `formatSignalPlainExplanation(signal)`:
   - Evaluates `signal_type` and `pattern`.
   - Returns a plain, actionable Vietnamese sentence (e.g. "🟢 Đánh LÊN (LONG) — Giá chạm vùng cá voi gom hàng (+OB), kỳ vọng bật tăng lên mục tiêu chốt lời.").
2. **Interactive Glossary & Trading Cheat Sheet Modal** (`#guideModal`) in `static/index.html`:
   - Accessible via **`📖 HƯỚNG DẪN & CHÚ THÍCH`** button on the topbar.
   - Clean, dark-mode, card-based popup modal with visual color chips:
     - **Mục 1: Ý nghĩa các đường vẽ trên biểu đồ (Chart Drawings)**:
       - 📈 `BOS (Break of Structure)`: Vừa phá vỡ cản tiếp diễn xu hướng.
       - 🔄 `CHoCH (Change of Character)`: Tín hiệu đảo chiều xu hướng (quay xe).
       - 📦 `+OB Demand (Hộp xanh)`: Vùng gom hàng của Cá voi -> Giá về đây thường bật tăng.
       - 📦 `-OB Supply (Hộp đỏ)`: Vùng xả hàng của Cá voi -> Giá lên đây thường bị đạp xuống.
       - 🎯 `Hộp Vị Thế Xanh / Đỏ`: Xanh là lãi (TP), Đỏ là lỗ (SL), Vạch giữa là giá vào (Entry).
     - **Mục 2: Hướng dẫn vào lệnh & đọc tỷ lệ R:R**:
       - `LONG` vs `SHORT`.
       - Tỷ lệ `R:R 1:2.5`: Bỏ 1 đồng rủi ro để ăn 2.5 đồng lãi.
       - `ADX`: Đo thị trường đang Giằng co (Ranging) hay Chạy sóng mạnh (Trending).
     - **Mục 3: Nguyên tắc sống còn khi trade Futures (Không cháy tài khoản)**:
       - Tuyệt đối không tất tay (All-in).
       - Luôn tuân thủ Stop Loss (SL).
       - Khi đạt TP1, kéo SL về Entry (Breakeven) để không bị lỗ ngược.
3. **Enhanced Signal Feed UI**:
   - Every signal item displays the plain-language explanation line beneath the pair and badge.

## Tasks
- **Task 1:** `formatSignalPlainExplanation` helper and unit tests in `chart_stream.js` (RED -> GREEN).
- **Task 2:** Add `#guideModal` HTML, CSS, and Topbar trigger button in `static/index.html`.
- **Task 3:** Wire plain-language explanations into Signal Feed cards and add interactive click handler.
- **Task 4:** Browser Live QA & Visual Inspection.
