import test from 'node:test';
import assert from 'node:assert/strict';
import { upsertKline, createThrottle, chooseMarketStructure, trendlinePoints, drawZoneBands, shouldShowConnectingStatus, clientReconnectDelay, structureToOverlays, formatOutcomeBadge, filterSignals, formatCandleCountdown, symbolToTradingView, timeframeToTradingView, formatTrendlineShape, formatOrderBlockShape, createTradingViewDatafeed, formatStructureBreakShape, formatPositionShape, formatSignalPlainExplanation, filterSymbols, formatHistoryTrades } from '../static/chart_stream.js';

test('structureToOverlays normalizes a server structure message', () => {
  const payload = {
    type: "structure", symbol: "BTCUSDT", timeframe: "15m",
    trendlines: [
      {time1: 100, price1: 10, next_time: 200, next_price: 12, is_resistance: true, touches: 5},
      {time1: 100, price1: 8, next_time: 200, next_price: 6, is_resistance: false, touches: 4},
    ],
    sr_zones: [[10, 12], [6, 8]],
    zone_bands: [{bottom: 10, top: 12, kind: "SUPPORT_RESISTANCE"}],
    fvgs: [{index: 5, bottom: 10, top: 11, type: "BULLISH", end_index: 9}],
    signal: {symbol: "BTCUSDT", signal_type: "LONG", entry_price: 11, stop_loss: 9, tp1: 12, tp2: 13},
  };
  const overlays = structureToOverlays(payload);
  assert.deepEqual(overlays.trendlines, payload.trendlines);
  assert.deepEqual(overlays.zone_bands, payload.zone_bands);
  assert.deepEqual(overlays.fvgs, payload.fvgs);
  assert.equal(overlays.signal["signal_type"], "LONG");
});

test('structureToOverlays tolerates missing fields', () => {
  const overlays = structureToOverlays({type: "structure", symbol: "BTCUSDT"});
  assert.deepEqual(overlays.trendlines, []);
  assert.deepEqual(overlays.zone_bands, []);
  assert.deepEqual(overlays.fvgs, []);
  assert.equal(overlays.signal, null);
});

test('upsertKline replaces matching candle and appends a newer candle', () => {
  const original = [{ time: 100, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 }];
  const updated = upsertKline(original, { time: 100, open: 1, high: 3, low: 0.5, close: 2.5, volume: 11 });
  assert.equal(updated.length, 1);
  assert.equal(updated[0].close, 2.5);
  const appended = upsertKline(updated, { time: 200, open: 2.5, high: 3, low: 2, close: 2.8, volume: 12 });
  assert.equal(appended.length, 2);
  assert.equal(appended[1].time, 200);
});

test('client reconnect delay increases and caps at thirty seconds', () => {
  assert.deepEqual([1,2,3,4,5,6,7].map(clientReconnectDelay),[1000,2000,4000,8000,16000,30000,30000]);
});

test('loadChart does not overwrite a connected market status', () => {
  assert.equal(shouldShowConnectingStatus({marketReadyState:1}),false);
  assert.equal(shouldShowConnectingStatus({marketReadyState:0}),true);
});

test('market reconnect backoff grows and caps', () => {
  const delays=[0,1,2,3,4,5,6,7].map(n=>Math.min(2**Math.max(0,n-1),30));
  assert.deepEqual(delays,[1,1,2,4,8,16,30,30]);
});

test('upsertKline keeps a bounded candle history after rollover', () => {
  const candles=[{time:100,open:1,high:2,low:1,close:2,volume:4}];
  const merged=upsertKline(candles,{time:200,open:3,high:3,low:3,close:3,volume:0,closed:false});
  assert.equal(merged.at(-1).time,200);
  assert.equal(merged.at(-1).open,3);
});

test('upsertKline ignores an out-of-order older candle', () => {
  const original = [{ time: 200, open: 2, high: 3, low: 1, close: 2.5, volume: 8 }];
  assert.equal(upsertKline(original, { time: 100, open: 1, high: 2, low: 0, close: 1, volume: 4 }), original);
});

test('createThrottle caps expensive calculations at four per second', () => {
  let now = 0;
  const calls = [];
  const throttled = createThrottle((value) => calls.push([now, value]), 250, () => now);
  throttled('a'); now = 100; throttled('b'); now = 249; throttled('c'); now = 250; throttled('d');
  assert.deepEqual(calls, [[0, 'a'], [250, 'd']]);
});

test('trendline points consume the API payload projection fields', () => {
  const line = {time1:100,price1:10,next_time:200,next_price:12,is_resistance:true,touches:5};
  assert.deepEqual(trendlinePoints(line), [{time:100,value:10},{time:200,value:12}]);
});

test('drawZoneBands renders realistic server S/R zone across chart history', () => {
  const fills=[];
  const ctx={clearRect(){},set fillStyle(value){this.color=value},fillRect(...args){fills.push({color:this.color,args})}};
  const chart={timeScale:()=>({timeToCoordinate:t=>t})};
  const series={priceToCoordinate:p=>p};
  drawZoneBands(ctx,chart,series,[{bottom:10,top:12,kind:'SUPPORT_RESISTANCE'}],[],[{time:100},{time:200}],200,100,true,false);
  assert.equal(fills.length,1);
  assert.equal(fills[0].color,'rgba(101,207,255,.05)');
  assert.deepEqual(fills[0].args,[100,10,100,2]);
});

test('market structure selects best line by touches then recency then residual', () => {
  const weak={is_resistance:true,touches:4,point2:[5,5],residual:0.001};
  const fresh={is_resistance:true,touches:5,point2:[8,8],residual:0.005};
  const accurate={is_resistance:true,touches:5,point2:[8,8],residual:0.001};
  const support={is_resistance:false,touches:3,point2:[7,7],residual:0.01};
  assert.deepEqual(chooseMarketStructure([weak,fresh,accurate,support]),[accurate,support]);
});

test('formatOutcomeBadge returns correct styling and text for WIN, LOSS, and OPEN', () => {
  assert.deepEqual(formatOutcomeBadge({status: 'WIN', pnl_r: 2.2}), {
    text: 'WIN +2.2R',
    color: '#00d69a',
    className: 'badge-win',
  });
  assert.deepEqual(formatOutcomeBadge({status: 'LOSS', pnl_r: -1.0}), {
    text: 'LOSS -1.0R',
    color: '#ff5e6e',
    className: 'badge-loss',
  });
  assert.deepEqual(formatOutcomeBadge({status: 'OPEN', floating_r: 0.8}), {
    text: 'ACTIVE (+0.8R)',
    color: '#65cfff',
    className: 'badge-open',
  });
});

test('filterSignals partitions signals by tab filter and optional symbol', () => {
  const sigs = [
    {id: 1, status: 'OPEN', symbol: 'BTCUSDT'},
    {id: 2, status: 'WIN', symbol: 'BTCUSDT'},
    {id: 3, status: 'LOSS', symbol: 'ETHUSDT'},
  ];
  assert.equal(filterSignals(sigs, 'ALL').length, 3);
  assert.deepEqual(filterSignals(sigs, 'ACTIVE'), [{id: 1, status: 'OPEN', symbol: 'BTCUSDT'}]);
  assert.deepEqual(filterSignals(sigs, 'HISTORY'), [{id: 2, status: 'WIN', symbol: 'BTCUSDT'}, {id: 3, status: 'LOSS', symbol: 'ETHUSDT'}]);
  assert.deepEqual(filterSignals(sigs, 'HISTORY', 'BTCUSDT'), [{id: 2, status: 'WIN', symbol: 'BTCUSDT'}]);
  assert.deepEqual(filterSignals(sigs, 'HISTORY', 'ETHUSDT'), [{id: 3, status: 'LOSS', symbol: 'ETHUSDT'}]);
});

test('formatCandleCountdown computes remaining mm:ss until candle close', () => {
  assert.equal(formatCandleCountdown(850 * 1000, '15m'), '00:50');
  assert.equal(formatCandleCountdown(3475 * 1000, '1h'), '02:05');
});

test('structureToOverlays includes order_blocks, regression_channel, and forecast_path', () => {
  const payload = {
    order_blocks: [{type: 'BULLISH_OB', top: 100, bottom: 98}],
    regression_channel: {upper_series: [{time: 1, value: 105}]},
    forecast_path: [{time: 10, value: 102}],
  };
  const res = structureToOverlays(payload);
  assert.deepEqual(res.order_blocks, payload.order_blocks);
  assert.deepEqual(res.regression_channel, payload.regression_channel);
  assert.deepEqual(res.forecast_path, payload.forecast_path);
});

test('symbolToTradingView maps futures symbols to Binance perp contracts', () => {
  assert.equal(symbolToTradingView('BTCUSDT'), 'BINANCE:BTCUSDT.P');
  assert.equal(symbolToTradingView('ETHUSDT'), 'BINANCE:ETHUSDT.P');
  assert.equal(symbolToTradingView('1000PEPEUSDT'), 'BINANCE:1000PEPEUSDT.P');
  assert.equal(symbolToTradingView(''), 'BINANCE:BTCUSDT.P');
});

test('timeframeToTradingView maps interval strings to TradingView format', () => {
  assert.equal(timeframeToTradingView('15m'), '15');
  assert.equal(timeframeToTradingView('1h'), '60');
  assert.equal(timeframeToTradingView('4h'), '240');
  assert.equal(timeframeToTradingView('1d'), 'D');
  assert.equal(timeframeToTradingView('unknown'), '15');
});

test('formatTrendlineShape creates valid TradingView multipoint shape descriptor', () => {
  const line = {
    time1: 1700000000,
    price1: 75000,
    next_time: 1700010000,
    next_price: 76000,
    is_resistance: true,
  };
  const shape = formatTrendlineShape(line);
  assert.equal(shape.options.shape, 'trend_line');
  assert.equal(shape.options.overrides.linecolor, '#f5b84b');
  assert.equal(shape.points.length, 2);
  assert.equal(shape.points[0].time, 1700000000);
  assert.equal(shape.points[0].price, 75000);
  assert.equal(shape.points[1].time, 1700010000);
  assert.equal(shape.points[1].price, 76000);
});

test('formatOrderBlockShape creates rectangle shape descriptor', () => {
  const ob = {
    type: 'BULLISH_OB',
    timestamp: 1700000000000,
    top: 76500,
    bottom: 76000,
  };
  const shape = formatOrderBlockShape(ob, 1700020000);
  assert.equal(shape.options.shape, 'rectangle');
  assert.equal(shape.options.overrides.backgroundColor, 'rgba(59, 130, 246, 0.16)');
  assert.equal(shape.points[0].price, 76500);
  assert.equal(shape.points[1].price, 76000);
  assert.equal(shape.points[1].time, 1700020000);
});

test('createTradingViewDatafeed resolves symbol with correct pricescale', async () => {
  const datafeed = createTradingViewDatafeed(async () => ({ candles: [] }));
  let resolved = null;
  datafeed.resolveSymbol('BTCUSDT', (info) => { resolved = info; }, () => {});
  await new Promise(r => setTimeout(r, 10));
  assert.ok(resolved);
  assert.equal(resolved.name, 'BTCUSDT');
  assert.equal(resolved.pricescale, 100);

  let pepeResolved = null;
  datafeed.resolveSymbol('1000PEPEUSDT', (info) => { pepeResolved = info; }, () => {});
  await new Promise(r => setTimeout(r, 10));
  assert.equal(pepeResolved.pricescale, 1000000);

  let pumpResolved = null;
  datafeed.resolveSymbol('PUMPUSDT', (info) => { pumpResolved = info; }, () => {});
  await new Promise(r => setTimeout(r, 10));
  assert.equal(pumpResolved.pricescale, 1000000);
});

test('createTradingViewDatafeed passes endTime on historical pagination', async () => {
  let requestedEndTime = null;
  const datafeed = createTradingViewDatafeed(async (sym, tf, endTime) => {
    requestedEndTime = endTime;
    return {
      candles: [{ time: 1700000, open: 10, high: 11, low: 9, close: 10.5, volume: 50 }]
    };
  });
  let barsReceived = null;
  await datafeed.getBars(
    { name: 'BTCUSDT' },
    '15',
    { firstDataRequest: false, to: 1700500 },
    (bars) => { barsReceived = bars; },
    () => {}
  );
  assert.equal(requestedEndTime, 1700500 * 1000);
  assert.equal(barsReceived.length, 1);
});

test('formatStructureBreakShape formats BOS and CHOCH dashed line descriptors', () => {
  const bos = { type: 'BOS', price: 80000, time_start: 1700000, time_end: 1700900, is_bullish: true };
  const shape = formatStructureBreakShape(bos);
  assert.equal(shape.options.shape, 'trend_line');
  assert.ok(shape.options.text.includes('BOS'));
  assert.ok(shape.options.text.includes('▲'));
  assert.equal(shape.options.overrides.linestyle, 2);
  assert.equal(shape.points[0].price, 80000);

  const choch = { type: 'CHOCH', price: 79000, time_start: 1700000, time_end: 1700900, is_bullish: false };
  const shape2 = formatStructureBreakShape(choch);
  assert.ok(shape2.options.text.includes('CHoCH'));
  assert.ok(shape2.options.text.includes('▼'));
  assert.equal(shape2.options.overrides.linecolor, '#f59e0b');
});

test('formatPositionShape creates comprehensive signal shapes with arrow, SL, TP and boxes', () => {
  const longSig = { signal_type: 'LONG', entry_price: 80000, stop_loss: 79000, tp2: 82500 };
  const lastCandle = { time: 1700000, high: 80200, low: 79800 };
  const shapes = formatPositionShape(longSig, lastCandle);
  assert.equal(shapes.signalArrow.options.shape, 'arrow_up');
  assert.equal(shapes.signalArrow.options.overrides.color, '#00d69a');
  assert.ok(shapes.signalArrow.point.price < 79800, 'LONG arrow must sit below candle low');
  assert.equal(shapes.entryLine.options.overrides.linecolor, '#ffffff');
  assert.ok(shapes.entryLine.options.text.includes('VÀO LONG'));
  assert.equal(shapes.tpLine.options.overrides.linecolor, '#00d69a');
  assert.equal(shapes.slLine.options.overrides.linecolor, '#ff4d4f');
  assert.ok(shapes.tpLine.options.text.includes('TP'));
  assert.ok(shapes.slLine.options.text.includes('SL'));

  const shortSig = { signal_type: 'SHORT', entry_price: 80000, stop_loss: 81000, tp2: 77500 };
  const shortShapes = formatPositionShape(shortSig, lastCandle);
  assert.equal(shortShapes.signalArrow.options.shape, 'arrow_down');
  assert.equal(shortShapes.signalArrow.options.overrides.color, '#ff4d4f');
  assert.ok(shortShapes.signalArrow.point.price > 80200, 'SHORT arrow must sit above candle high');
  assert.ok(shortShapes.entryLine.options.text.includes('VÀO SHORT'));
  assert.equal(shortShapes.slLine.options.overrides.linecolor, '#ff4d4f');
  assert.equal(shortShapes.tpLine.options.overrides.linecolor, '#00d69a');
});

test('formatHistoryTrades builds single outcome arrows at each entry position', () => {
  const trades = [
    { id: 1, symbol: 'BTCUSDT', signal_type: 'LONG', status: 'WIN', entry_price: 80000, sl_pct: 0.005, pnl_r: 2.2, created_at: 1700000000 },
    { id: 2, symbol: 'BTCUSDT', signal_type: 'SHORT', status: 'LOSS', entry_price: 81000, sl_pct: 0.008, pnl_r: -1, created_at: 1700007200 },
  ];
  const shapes = formatHistoryTrades(trades);
  assert.equal(shapes.length, 2);

  assert.equal(shapes[0].options.shape, 'arrow_up');
  assert.equal(shapes[0].options.text, 'WIN +2.2R');
  assert.equal(shapes[0].options.overrides.color, '#00d69a');
  assert.equal(shapes[0].point.time, 1700000000);
  assert.ok(shapes[0].point.price < 80000, 'LONG marker must sit below entry');

  assert.equal(shapes[1].options.shape, 'arrow_down');
  assert.equal(shapes[1].options.text, 'LOSS -1.0R');
  assert.equal(shapes[1].options.overrides.color, '#ff4d4f');
  assert.ok(shapes[1].point.price > 81000, 'SHORT marker must sit above entry');
});

test('formatHistoryTrades skips incomplete or open trades', () => {
  const trades = [
    { status: 'OPEN', entry_price: 100, created_at: 1700000000 },
    { status: 'WIN', created_at: 1700000000 },
    { status: 'LOSS', entry_price: 100 },
  ];
  const shapes = formatHistoryTrades(trades);
  assert.equal(shapes.length, 0);
});

test('formatSignalPlainExplanation translates trading setup into simple Vietnamese', () => {  const longOB = { signal_type: 'LONG', pattern: 'SMC_ORDER_BLOCK_RETEST' };
  const exp1 = formatSignalPlainExplanation(longOB);
  assert.ok(exp1.includes('Đánh LÊN (LONG)'));
  assert.ok(exp1.includes('gom hàng'));

  const shortMR = { signal_type: 'SHORT', pattern: 'MEAN_REVERSION_TRAP' };
  const exp2 = formatSignalPlainExplanation(shortMR);
  assert.ok(exp2.includes('Đánh XUỐNG (SHORT)'));
  assert.ok(exp2.includes('quá bán') || exp2.includes('quá mua') || exp2.includes('trung bình'));

  const breakout = { signal_type: 'LONG', pattern: 'TRENDLINE_BREAKOUT' };
  const exp3 = formatSignalPlainExplanation(breakout);
  assert.ok(exp3.includes('Phá vỡ cản') || exp3.includes('Breakout'));
});

test('filterSymbols filters and ranks symbols by search query', () => {
  const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT', '1000PEPEUSDT', 'SUIUSDT', 'NEARUSDT'];

  // Empty query returns all up to limit
  assert.equal(filterSymbols(symbols, '').length, 7);

  // Case-insensitive prefix match
  const sol = filterSymbols(symbols, 'sol');
  assert.deepEqual(sol, ['SOLUSDT']);

  // Base substring match (e.g. "pepe" in "1000PEPEUSDT")
  const pepe = filterSymbols(symbols, 'pepe');
  assert.deepEqual(pepe, ['1000PEPEUSDT']);

  // Partial match matching multiple coins
  const eCoins = filterSymbols(symbols, 'e');
  // 'ETHUSDT' starts with E, '1000PEPEUSDT' and 'NEARUSDT' contain E
  assert.equal(eCoins[0], 'ETHUSDT'); // Prefix match prioritized
  assert.ok(eCoins.includes('1000PEPEUSDT'));
  assert.ok(eCoins.includes('NEARUSDT'));

  // Unknown symbol query returns empty array
  assert.deepEqual(filterSymbols(symbols, 'XYZNONEXISTENT'), []);
});

// ---------------------------------------------------------------------------
// News advisory panel (Task 2) — safe rendering contract
// ---------------------------------------------------------------------------

function fakeNewsElement(tag = 'div') {
  return {
    tagName: String(tag).toUpperCase(),
    children: [],
    attrs: {},
    _text: '',
    set textContent(v) { this._text = String(v); this.children = []; },
    get textContent() { return this._text; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    appendChild(c) { this.children.push(c); return c; },
  };
}

function walkFake(node, visit) {
  visit(node);
  for (const child of node.children) walkFake(child, visit);
}

test('renderNewsItems_rendersUntrustedHeadlineAsTextAndOnlyHttpsLinks', async () => {
  const { renderNewsItems } = await import('../static/chart_stream.js');
  const now = 1_794_400_000_000; // fixed ms clock
  const container = fakeNewsElement('div');
  const payload = {
    items: [
      { id: '1', source: 'Bloomberg', title: '<img src=x onerror=alert(1)>Bitcoin ETF approved', url: 'https://news.google.com/rss/articles/abc', published_at: now - 5 * 60 * 1000, symbols: ['BTC'], scope: 'symbol', event_tags: ['SEC', 'ETF'] },
      { id: '2', source: 'Reuters', title: 'Plain http link item', url: 'http://evil.example.com/x', published_at: now - 2 * 3600 * 1000, symbols: [], scope: 'market', event_tags: [] },
      { id: '3', source: 'CNBC', title: 'No link item', url: '', published_at: now - 26 * 3600 * 1000, symbols: ['ETH'], scope: 'symbol', event_tags: [] },
    ],
    fetched_at: now,
    stale: false,
    sources_ok: true,
    source_status: [{ source: 'SEC', ok: true, error_code: null }],
  };
  const fakeDoc = { createElement: (tag) => fakeNewsElement(tag) };
  renderNewsItems(container, payload, { document: fakeDoc, now });

  // 1. Untrusted headline stays text: no IMG element is ever created
  let sawImg = false;
  walkFake(container, (n) => { if (n.tagName === 'IMG') sawImg = true; });
  assert.equal(sawImg, false);
  const rows = [];
  walkFake(container, (n) => { if (n.className === 'news-item') rows.push(n); });
  const row1 = rows.find((r) => JSON.stringify(r).includes('Bitcoin ETF approved'));
  const row2 = rows.find((r) => JSON.stringify(r).includes('Plain http link item'));
  const row3 = rows.find((r) => JSON.stringify(r).includes('No link item'));
  assert.ok(row1 && row2 && row3, 'all three rows rendered');
  assert.ok(JSON.stringify(row1).includes('<img src=x onerror=alert(1)>Bitcoin ETF approved'),
    'headline markup must survive as literal text, never parsed as HTML');

  // 2. HTTPS link becomes a safe anchor
  let anchor = null;
  walkFake(row1, (n) => { if (n.tagName === 'A') anchor = n; });
  assert.ok(anchor, 'https item renders an anchor');
  assert.equal(anchor.attrs.href, 'https://news.google.com/rss/articles/abc');
  assert.equal(anchor.attrs.target, '_blank');
  assert.equal(anchor.attrs.rel, 'noopener noreferrer');

  // 3. Non-HTTPS link renders text only, no anchor
  let anchor2 = null;
  walkFake(row2, (n) => { if (n.tagName === 'A') anchor2 = n; });
  assert.equal(anchor2, null, 'http link must not become an anchor');

  // 4. Empty url renders text only
  let anchor3 = null;
  walkFake(row3, (n) => { if (n.tagName === 'A') anchor3 = n; });
  assert.equal(anchor3, null, 'empty url must not become an anchor');

  // 5. Fixed disclaimer always present
  assert.ok(JSON.stringify(container).includes('Tin tức chỉ để tham khảo'), 'disclaimer shown');
});

test('createNewsController_aborts_in_flight_fetch_on_symbol_change', async () => {
  const { createNewsController } = await import('../static/chart_stream.js');
  let currentSymbol = 'BTCUSDT';
  const aborted = [];
  const container = { textContent: '', children: [], appendChild() {} };

  const fetchFn = (url, opts) => new Promise((resolve, reject) => {
    if (url.includes('symbol=ETHUSDT')) {
      // resolves late so the BTC fetch is provably still in flight
      setTimeout(() => resolve({ json: async () => ({ items: [], stale: false, sources_ok: true, source_status: [] }) }), 20);
    } else {
      opts.signal.addEventListener('abort', () => {
        aborted.push(url);
        const err = new Error('aborted');
        err.name = 'AbortError';
        reject(err);
      });
    }
  });

  const controller = createNewsController({
    container,
    getSymbol: () => currentSymbol,
    fetchFn,
  });

  const first = controller.refresh();               // BTCUSDT: hangs in flight
  await new Promise((r) => setTimeout(r, 5));
  currentSymbol = 'ETHUSDT';
  const second = controller.refresh();              // must abort the BTC fetch

  await Promise.all([first, second]);               // aborted promise rejects internally, never throws out
  assert.deepEqual(aborted, ['/api/news?symbol=BTCUSDT'], 'in-flight BTC fetch must be aborted on symbol change');

  controller.stop();
});
