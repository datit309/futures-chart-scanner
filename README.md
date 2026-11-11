# 🎯 Crypto Futures Chart Scanner & Telegram Alert Bot

> Hệ thống tự động phân tích đồ thị nến, vẽ Trendline, phát hiện Breakout/Cản và bắn ảnh đồ thị kèm điểm vào lệnh (Entry / Stop Loss / Take Profit) về Telegram cho các cặp coin **Binance USDT-M Futures**.

---

## ⚡ 1. Tính Năng Cốt Lõi

1. **Auto-Trendline & Cấu Trúc Đồ Thị**:
   * Tự động lọc đỉnh/đáy chuẩn xác bằng thuật toán Fractal $N$-nến (`find_swing_points`).
   * Tự động kẻ các đường Trendline Hỗ trợ / Kháng cự; loại bỏ đường rác và chỉ giữ lại những đường có $\ge 3$ lần chạm kiểm định mà không bị thân nến đâm thủng.
   * Tự động phát hiện vùng Hỗ trợ/Kháng cự ngang và vùng mất cân bằng thanh khoản **FVG (Fair Value Gap)**.
2. **Nhận Diện Tín Hiệu Breakout Kèm Volume**:
   * Phát hiện nến đóng cửa đâm thủng đường cản chéo (Downtrend Resistance $\rightarrow$ Breakout LONG; Uptrend Support $\rightarrow$ Breakdown SHORT).
3. **Quản Trị Rủi Ro Khắt Khe ($R:R \ge 1:2.0$)**:
   * Tự động đo khoảng cách cắt lỗ (Stop Loss) theo râu nến/đáy Swing gần nhất.
   * Tính toán sẵn 2 mốc chốt lời: **TP1 ($1.5R$)** và **TP2 ($2.5R$)**.
   * Chỉ phát tín hiệu khi tỷ lệ lời/lỗ $R:R \ge 1:2.0$; tự động loại bỏ các kèo rủi ro cao.
4. **Vẽ Ảnh Đồ Thị Dark Mode & Gửi Telegram**:
   * Dùng Matplotlib vẽ nến xanh/đỏ, volume, kẻ sẵn các đường Trendline, tô bóng vùng cản, đánh dấu các mốc Entry, SL, TP.
   * Bắn trực tiếp ảnh chart sắc nét + bản kế hoạch giao dịch vào Telegram cá nhân / Group.
5. **An Toàn Tuyệt Đối**:
   * Sử dụng 100% dữ liệu Public từ Binance Futures API — **Không cần cung cấp API Key / Secret Key sàn**, không lo lộ tài khoản.

---

## 📁 2. Cấu Trúc Dự Án

```
futures-chart-scanner/
├── config.py             # Quản lý cấu hình (Telegram Token, Timeframe, R:R...)
├── config.example.json   # Mẫu file cấu hình
├── binance_client.py     # Module kết nối bất đồng bộ Binance Futures Public API
├── technical_engine.py   # Bộ não hình học: Fractal Swing, Auto-Trendline, FVG, Breakout
├── risk_manager.py       # Quản trị rủi ro, lọc tỷ lệ R:R >= 2.0, format caption Telegram
├── chart_renderer.py     # Vẽ đồ thị Dark Mode (nến, trendline, zones, entry/SL/TP)
├── telegram_notifier.py  # Gửi ảnh chart + thông báo qua Telegram Bot API
├── main.py               # Runner chính: CLI scan-once hoặc loop 24/7
├── run.sh                # Script khởi động nhanh 1-click
├── requirements.txt      # Danh sách thư viện Python
├── saved_charts/         # Thư mục lưu ảnh đồ thị đã xuất
└── tests/                # Bộ kiểm thử tự động TDD (13 tests)
```

---

## 🚀 3. Hướng Dẫn Sử Dụng

### Bước 1: Cấu hình Telegram (Tùy chọn)
Mở file `config.json` (tự động tạo từ `config.example.json`) và điền thông tin:
```json
{
    "telegram_bot_token": "YOUR_BOT_TOKEN_FROM_BOTFATHER",
    "telegram_chat_id": "YOUR_CHAT_ID",
    "timeframe": "15m",
    "top_n_coins": 30,
    "min_rr": 2.0,
    "min_trendline_touches": 3,
    "scan_interval_seconds": 300
}
```
*(Nếu chưa có Telegram Bot, bot vẫn quét bình thường và lưu ảnh chart vào thư mục `saved_charts/` để fen xem trực tiếp).*

### Web Dashboard (Realtime)

Khởi chạy chart UI, scanner controls và dữ liệu nến realtime:
```bash
./venv/bin/python server.py
```
Mở `http://127.0.0.1:8766` trong trình duyệt. Nến realtime (OHLC đầy đủ: open/high/low/close/volume) của cặp đang chọn được lấy từ Binance USDⓈ-M REST `/fapi/v1/klines`, server poll mỗi 3 giây rồi đẩy qua `/ws/market`. Binance `@kline_*` WebSocket handshake thành công nhưng không phát frame trong môi trường mạng này, nên REST polling là nguồn realtime thay thế. Phân tích cấu trúc (trendline, vùng S/R, FVG, tín hiệu) do server `TechnicalEngine` tính và gửi cùng stream. Khi trạng thái là `RECONNECTING`/`STALE`, UI sẽ báo rõ; khi kết nối lại sẽ tải lại lịch sử. Không cần Binance API key; app chỉ đọc dữ liệu thị trường công khai và không đặt lệnh. Tín hiệu chỉ để nghiên cứu, không đảm bảo lợi nhuận.

### Bước 2: Chạy Thử Nghiệm

* **Quét 1 vòng thử nghiệm (Scan Once):**
  ```bash
  ./run.sh --scan-once
  ```

* **Soi chart 1 con coin cụ thể (ví dụ: BTCUSDT hoặc SOLUSDT):**
  ```bash
  ./run.sh --symbol BTCUSDT
  # Hoặc:
  ./run.sh --symbol SOLUSDT --timeframe 15m
  ```

* **Chạy vòng lặp quét thị trường tự động 24/7:**
  ```bash
  ./run.sh --loop
  ```

* **Chạy toàn bộ Unit Tests:**
  ```bash
  ./run.sh --test
  ```

---

## 🔴 Crypto News RSS Advisory — Publisher Terms Gate (BLOCKED, chờ user quyết)

> Trạng thái: **KHÔNG ĐƯỢC IMPLEMENT**. Gate bắt buộc của plan `docs/supergraph/plans/2026-11-10-crypto-news-risk-advisory.md` đang ở trạng thái **unclear → STOP**, chờ user phê duyệt nguồn hoặc cấp phép.

**Ngày kiểm tra:** 2026-11-11 (Asia/Saigon)

**Nguồn dự kiến (fixed allowlist):**

| Nguồn | RSS URL | robots.txt | Feed check |
|---|---|---|---|
| CoinDesk | `https://www.coindesk.com/arc/outboundfeeds/rss` | `User-agent: *` → `Allow:` rỗng; chỉ `Disallow` `/api/`, `/search*`, `/auth/*`, `/layer2/`, `/consensus-magazine/`, `/*/amp`. **Path `/arc/outboundfeeds/rss` KHÔNG bị chặn.** Lưu ý: robots.txt có nhóm rule riêng chặn gần như toàn bộ cho AI crawler (GPTBot, ClaudeBot, CCBot, v.v.) — app poll bằng UA thường, không dùng UA AI-crawler. | ✅ HTTP 200 `application/xml` |
| Cointelegraph | `https://cointelegraph.com/rss` | `User-Agent: *`; chỉ `Disallow` `/api/`, `/wp-admin/`, `/profile`, tracking params. **Path `/rss` KHÔNG bị chặn.** | ✅ HTTP 200 `application/xml; charset=utf-8` |

**Kết luận theo từng nguồn:**

* **CoinDesk — UNVERIFIABLE (chặn verify):** Trang terms-of-use (`https://www.coindesk.com/terms-of-use/`, `/terms-of-service/`, `/terms/`) trả **HTTP 429 Vercel Security Checkpoint** cho mọi lần thử (cả `web_fetch` và `curl` với UA trình duyệt). Không đọc được ToS hiện hành → **không thể xác nhận allow**.
* **Cointelegraph — UNCLEAR:** ToS tại `https://cointelegraph.com/terms-and-privacy` (§3 Content Usage Rights): *"Users may access the Content for personal and informational purposes only. Redistribution, reproduction, automated scraping, or creation of independent content pipelines based on Cointelegraph reputation is strictly prohibited without prior written authorization. Quoting Cointelegraph Content is permitted when it reflects fair use and includes clear attribution to Cointelegraph as the source."*
  → Trích dẫn headline + summary ngắn (≤600 ký tự) có attribution + link outbound cho dashboard cá nhân **có thể** rơi vào fair-use quoting, nhưng **poll RSS tự động 5 phút/lần** có thể bị coi là "automated scraping / content pipeline" → **vùng xám, không rõ ràng**.

**Quyết định:** Theo đúng acceptance của Task 0 (*"terms are unclear → STOP and ask user; no silent substitution or scraping"*), **dừng toàn bộ Tasks 1–3**. Không thay thẻ nguồn im lặng, không scraping.

**Cần user quyết:** chọn 1 trong các hướng (xem hội thoại) — ví dụ: (a) xin phép viết cả 2 publisher, (b) đổi sang nguồn có ToS rõ ràng cho phép hiển thị headline+summary (ví dụ feed chính chủ có license rõ), (c) chỉ hiển thị **title + link** không summary và coi là fair-use quoting, (d) huỷ feature.
