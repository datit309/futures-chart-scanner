# 🎯 Crypto Futures Chart Scanner & Telegram Alert Bot

> Hệ thống tự động phân tích đồ thị nến, vẽ Trendline, phát hiện Breakout/Cản và bắn ảnh đồ thị kèm điểm vào lệnh (Entry / Stop Loss / Take Profit) về Telegram cho các cặp coin **Binance USDT-M Futures**.

---

## ⚡ 1. Tính Năng Cốt Lõi

### Live universe — whitelist coin tin cậy
- Toàn bộ scan, watchlist, search, live chart và market WebSocket chỉ dùng whitelist cố định: **BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT**. Không xếp hạng động theo volume.
- Coin ngoài whitelist không thể được chọn hoặc subscribe live. Historical signal/chart archive vẫn xem được cho tới purge thủ công.
- Khi whitelist có hiệu lực, `OPEN` của coin bị loại sẽ **không còn được tracker cập nhật TP/SL/PnL**. Tín hiệu vẫn hiện trong OPEN feed với nhãn **NOT MONITORED** cho tới purge.
- Khi đổi whitelist, không tự xóa DB. Nếu quyết định purge, dùng CLI preview trước; apply là thao tác riêng có backup/xác nhận và không chạy tự động. Khi purge được xác nhận, các dòng OPEN này cũng bị xóa và sẽ không còn khả năng theo dõi/khôi phục trạng thái giao dịch trừ khi restore backup.

### Purge lịch sử coin ngoài whitelist (NGUY HIỂM, tùy chọn)
- Ứng dụng **không tự xóa dữ liệu** khi whitelist thay đổi và không có purge endpoint trên web.
- Preview chỉ đọc: `python3 purge_signals.py --db signals.db` — liệt kê symbol/status/OPEN count; không tạo backup hay sửa DB.
- Khi fen chủ động muốn xóa vĩnh viễn, chạy `python3 purge_signals.py --db signals.db --apply`. CLI in toàn bộ summary trước, yêu cầu gõ đúng `PURGE`, sau đó mới tạo SQLite backup có WAL và chạy `integrity_check`/đối chiếu số dòng. Nếu backup/integrity không đạt, CLI luôn dừng và không có bỏ qua kiểm tra; nếu số dòng thay đổi giữa preview và lúc xóa thì cũng dừng. Backup thành công được giữ vô thời hạn, không tự động xóa.
- Xác nhận purge sẽ xóa tất cả signal rows của symbol ngoài whitelist (kể cả OPEN và embedded candle snapshot), làm mất tracking OPEN và đổi thống kê. Không thể khôi phục ngoài backup. Tests chỉ dùng temporary DB; production DB không bị purge tự động.

1. **Auto-Trendline & Cấu Trúc Đồ Thị**:
   * Tự động lọc đỉnh/đáy chuẩn xác bằng thuật toán Fractal $N$-nến (`find_swing_points`).
   * Tự động kẻ các đường Trendline Hỗ trợ / Kháng cự; loại bỏ đường rác và chỉ giữ lại những đường có $\ge 3$ lần chạm kiểm định mà không bị thân nến đâm thủng.
   * Tự động phát hiện vùng Hỗ trợ/Kháng cự ngang và vùng mất cân bằng thanh khoản **FVG (Fair Value Gap)**.
2. **Nhận Diện Tín Hiệu Breakout Kèm Volume**:
   * Phát hiện nến đóng cửa đâm thủng đường cản chéo (Downtrend Resistance $\rightarrow$ Breakout LONG; Uptrend Support $\rightarrow$ Breakdown SHORT).
   * Dashboard có overlay tùy chọn **Volume Profile · aggTrades 24h**: histogram ngang theo giá, POC và Value Area 70% (VAH/VAL), tính từ giá và khối lượng cơ sở của giao dịch tổng hợp Binance USDⓈ-M thật. Đây là thống kê giao dịch, không phải order book/footprint và không tham gia lọc tín hiệu.
   * Binance giới hạn truy vấn `aggTrades` trong 2 ngày; dashboard chỉ lấy cửa sổ 24h, tối đa 20 trang × 1000 dòng, cache 60 giây. Nếu chạm giới hạn, thiếu bằng chứng phủ đầu cửa sổ (trade đầu cách start quá 5 phút) hoặc upstream lỗi, profile được gắn trạng thái một phần/lỗi thay vì bị coi là đầy đủ.
   * Dữ liệu khối lượng dùng đơn vị base quantity (`q`), không phải notional quote volume. Volume Profile được tải theo yêu cầu khi bật overlay; tắt overlay không gửi request nền.
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

---

## 📰 Cách hoạt động của panel tin tức (advisory-only)

**Vai trò:** Tin tức chỉ là *ngữ cảnh tham khảo*. Panel **không bao giờ** tạo/sửa/xoá/bóp tín hiệu, không đổi Entry/SL/TP, không đổi sizing, không đặt lệnh. `WebServerState.run_scan` không gọi `NewsService` (có test khoá invariant). Quét kỹ thuật chạy độc lập hoàn toàn.

**Nguồn cố định (chỉ đổi được trong code `news_service.py`, không nhận URL từ query/user — chặn SSRF):**
- SEC press releases · Federal Reserve press releases (public domain)
- Google News RSS: truy vấn `cryptocurrency/bitcoin/ethereum` và `crypto regulation` — lọc theo allowlist nguồn tier-1: Bloomberg, Reuters, CNBC, WSJ, Financial Times, Fortune, Forbes, Barron's, MarketWatch, Benzinga, CoinDesk, Cointelegraph, The Block, Decrypt, Bitcoin Magazine. Tin từ nguồn ngoài allowlist bị loại (chống tin vịt).

**Chu kỳ & độ trễ:** poll mỗi 5 phút + ngay khi khởi động; mỗi feed timeout 4 giây, không redirect, giới hạn 512 KiB decompressed; cache tối đa 200 item / 24 giờ. `stale = true` nếu chưa có lần refresh thành công nào hoặc lần thành công gần nhất > 15 phút.

**Thời gian:** Ngày thiếu/không hợp lệ/tương lai → lấy thời gian fetch và gắn cờ `published_at_estimated = true`.

**Nhận diện symbol:** khớp ranh giới token trên title (không khớp URL slug); alias tường minh (BTC=bitcoin, ETH=ethereum|ether, SOL=solana, LINK=chainlink, DOT=polkadot, NEAR=near protocol, OP=optimism, ARB=arbitrum, TON=toncoin, APT=aptos, UNI=uniswap…). Các ticker dễ nhầm từ thường (`LINK, NEAR, OP, ARB, UNI, DOT, TON, APT, GAS, HOT, ARK, ATOM, ONE, ON`) **chỉ** khớp alias, không khớp ticker trần (tránh "click the link", "connect the dots", "tons of", "apt to", "university", "arbitrage", "original post"). Item không khớp symbol nào chỉ được giữ nếu khớp cụm thị trường rộng (`bitcoin`, `federal reserve`, `fomc`, `inflation`, `crypto regulation`…).

**Tag sự kiện (trung lập):** khớp cụm chính xác — `hack, exploit, security breach, lawsuit, ban, sanction, regulation, delisting, insolvency, bankruptcy, liquidation` + viết tắt **chữ hoa** `SEC, CFTC, ETF`. Tag bị triệt tiêu nếu trong 3 token trước đó có phủ định (`no, not, without, unlikely, denies, denied, rejects, false`) — ví dụ "no hack reported" không gắn tag `hack`. Chip tiếng Việt: `VĨ MÔ`, `QUY ĐỊNH`, `BẢO MẬT`, `SÀN GIAO DỊCH`. **Không** có nhãn cảm xúc/LONG/SHORT/khuyến nghị.

**Giới hạn cần biết:**
- Nhận diện symbol/tag có thể sai (false positive) và bỏ sót (negation chỉ hoạt động trong cửa sổ 3 token).
- Tin có thể cũ, thiếu, hoặc không liên quan tới cặp đang xem — luôn tự mở nguồn gốc để kiểm chứng.
- Feed có thể chậm hoặc lỗi từng nguồn; panel hiển thị rõ trạng thái stale/lỗi từng phần/lỗi toàn bộ, quét kỹ thuật vẫn chạy bình thường.
- Không khẳng định tin "gây ra" biến động giá; chỉ hiển thị nguồn + thời gian + link.
- Không có đánh giá lợi nhuận từ tin tức; mọi tuyên bố về edge cần backtest out-of-sample net-of-fees riêng.

**Endpoint:** `GET /api/news?symbol=BTCUSDT` — chỉ đọc cache (không fetch upstream trên request path), trả tối đa 50 item mới nhất gồm: tin vĩ mô + tin symbol đang chọn + tin symbol đang có tín hiệu mở, kèm `stale`, `source_status`. Thiếu `symbol` → chỉ vĩ mô + symbol đang có tín hiệu; symbol sai định dạng → 400.

**Cấu hình UA:** SEC yêu cầu User-Agent khai báo liên hệ; mặc định `futures-chart-scanner admin@example.com`, đổi được qua biến môi trường `NEWS_USER_AGENT`.
