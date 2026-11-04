import test from 'node:test';
import assert from 'node:assert/strict';
import { upsertKline, createThrottle, chooseMarketStructure, trendlinePoints, drawZoneBands, shouldShowConnectingStatus, clientReconnectDelay, structureToOverlays, formatOutcomeBadge, filterSignals, formatCandleCountdown, symbolToTradingView, timeframeToTradingView, formatTrendlineShape, formatOrderBlockShape, createTradingViewDatafeed } from '../static/chart_stream.js';

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

test('filterSignals partitions signals by tab filter', () => {
  const sigs = [
    {id: 1, status: 'OPEN'},
    {id: 2, status: 'WIN'},
    {id: 3, status: 'LOSS'},
  ];
  assert.equal(filterSignals(sigs, 'ALL').length, 3);
  assert.deepEqual(filterSignals(sigs, 'ACTIVE'), [{id: 1, status: 'OPEN'}]);
  assert.deepEqual(filterSignals(sigs, 'HISTORY'), [{id: 2, status: 'WIN'}, {id: 3, status: 'LOSS'}]);
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
  assert.equal(shape.options.overrides.backgroundColor, 'rgba(0, 214, 154, 0.20)');
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
  assert.equal(pepeResolved.pricescale, 100000);
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
