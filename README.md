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

## ✅ Crypto News RSS Advisory — Publisher Terms Gate (PASSED với nguồn thay thế)

> Trạng thái: **CHO PHÉP IMPLEMENT**. Gate Task 0 đã chạy (2026-11-11): bộ nguồn gốc CoinDesk/Cointelegraph bị **BLOCKED** (xem lịch sử bên dưới), user đã duyệt chuyển sang bộ nguồn **verified-allow** + **có tác động thị trường thực tế** (không lấy tin vịt).

**Nguồn chính thức (fixed allowlist, chỉ đổi được trong code):**

| Nguồn | URL | Cơ sở pháp lý | Kiểm tra |
|---|---|---|---|
| SEC (Ủy ban Chứng khoán Mỹ) | `https://www.sec.gov/news/pressreleases.xml` | Tác phẩm của chính phủ liên bang Mỹ — public domain theo luật (17 U.S.C. §105) | ✅ HTTP 200 XML |
| Federal Reserve | `https://www.federalreserve.gov/feeds/press_all.xml` | Tác phẩm chính phủ liên bang Mỹ — public domain | ✅ HTTP 200 XML |
| Google News (crypto) | `https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+ethereum+when:2d&hl=en-US&gl=US&ceid=US:en` | License ghi ngay trong feed: *"made available solely for the purpose of rendering Google News results within a personal feed reader for personal, non-commercial use"* | ✅ HTTP 200 XML |
| Google News (regulation) | `https://news.google.com/rss/search?q=crypto+regulation+OR+sec+OR+cftc+when:3d&hl=en-US&gl=US&ceid=US:en` | Như trên | ✅ HTTP 200 XML |

**Chống tin vịt:** item từ Google News chỉ được giữ nếu hậu tố nguồn trong title thuộc allowlist tier-1: `Bloomberg, Reuters, CNBC, WSJ, Financial Times, Fortune, Forbes, Barron's, MarketWatch, Benzinga, CoinDesk, Cointelegraph, The Block, Decrypt, Bitcoin Magazine`. Item SEC/Fed đi thẳng (nguồn chính thức).

**Cách dùng tuân thủ license:** chỉ hiển thị headline + tên nguồn + thời gian + link outbound; không lưu full text, không hình ảnh, không summary; text render bằng `textContent`; link HTTPS `rel="noopener noreferrer"`; dashboard local, phi thương mại.

**Lịch sử gate (2026-11-11):** Sweep 11 nguồn ban đầu — CoinDesk (ToS không verify được, HTTP 429 Vercel checkpoint), Cointelegraph (ToS §3 cấm automated scraping/content pipelines nếu không có authorization), The Block (Cloudflare 403), Bitcoin Magazine (cấm reproduction without written consent), CryptoSlate/U.Today/NewsBTC (cấm tuyên bố republish/scrape), Blockworks (redistribution phải trả phí), Bitcoin.com (cấm automated extraction), Decrypt (không có license grant), Treasury/DOJ/CFTC (feed unreachable/404 từ mạng này). Không nguồn editorial nào verified-allow → chuyển sang SEC + Fed + Google News tier-1 filtered.
