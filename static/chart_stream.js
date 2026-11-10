export function shouldShowConnectingStatus({marketReadyState}) {
  return marketReadyState !== 1;
}

export function clientReconnectDelay(attempt) {
  return Math.min(1000 * 2 ** Math.max(0, attempt - 1), 30000);
}

export function structureToOverlays(payload) {
  if (!payload || typeof payload !== "object") {
    return {trendlines: [], zone_bands: [], fvgs: [], order_blocks: [], regression_channel: {}, forecast_path: [], structure_breaks: [], signal: null};
  }
  return {
    trendlines: Array.isArray(payload.trendlines) ? payload.trendlines : [],
    zone_bands: Array.isArray(payload.zone_bands) ? payload.zone_bands : [],
    fvgs: Array.isArray(payload.fvgs) ? payload.fvgs : [],
    order_blocks: Array.isArray(payload.order_blocks) ? payload.order_blocks : [],
    regression_channel: payload.regression_channel || {},
    forecast_path: Array.isArray(payload.forecast_path) ? payload.forecast_path : [],
    structure_breaks: Array.isArray(payload.structure_breaks) ? payload.structure_breaks : [],
    signal: payload.signal || null,
  };
}

export function formatCandleCountdown(nowMs, timeframe = '15m') {
  const secMap = { '1m': 60, '3m': 180, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400 };
  const intervalSec = secMap[timeframe] || 900;
  const nowSec = Math.floor(nowMs / 1000);
  const remainingSec = intervalSec - (nowSec % intervalSec);
  const h = Math.floor(remainingSec / 3600);
  const m = Math.floor((remainingSec % 3600) / 60);
  const s = remainingSec % 60;
  if (h > 0) {
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function upsertKline(candles, candle) {
  if (!Array.isArray(candles) || !candle || !Number.isFinite(candle.time)) return candles;
  if (!candles.length) return [candle];
  const lastIndex=candles.length-1,last=candles[lastIndex];
  if(candle.time<last.time)return candles;
  if(candle.time===last.time){const next=candles.slice();next[lastIndex]=candle;return next;}
  return [...candles,candle];
}
export function createThrottle(callback,intervalMs=250,clock=()=>performance.now()){
  let lastRun=-Infinity;return(...args)=>{const now=clock();if(now-lastRun<intervalMs)return false;lastRun=now;callback(...args);return true;};
}
export function chooseMarketStructure(trendlines){
  const chosen=[];for(const resistance of [true,false]){const lines=trendlines.filter(line=>line.is_resistance===resistance);lines.sort((a,b)=>(b.touches-a.touches)||((b.anchor_index??b.point2?.[0]??-1)-(a.anchor_index??a.point2?.[0]??-1))||((a.residual??Infinity)-(b.residual??Infinity)));if(lines.length)chosen.push(lines[0]);}return chosen;
}
export function trendlinePoints(line){
  if(!Number.isFinite(line?.time1)||!Number.isFinite(line?.price1)||!Number.isFinite(line?.next_time)||!Number.isFinite(line?.next_price))return [];
  return [{time:line.time1,value:line.price1},{time:line.next_time,value:line.next_price}];
}
export function drawZoneBands(ctx,chart,candleSeries,zones,fvgs,candles,width,height,showZones=true,showFvgs=true,orderBlocks=[],showOB=true){
  ctx.clearRect(0,0,width,height);if(!candles.length)return;
  const drawBand=(zone,color,border=null,label=null)=>{
    const startIndex=Math.max(0,Math.min(candles.length-1,zone.index??0)),endIndex=Math.max(startIndex,Math.min(candles.length-1,zone.end_index??candles.length-1));
    const x1=chart.timeScale().timeToCoordinate(candles[startIndex].time),x2=chart.timeScale().timeToCoordinate(candles[endIndex].time),y1=candleSeries.priceToCoordinate(zone.top),y2=candleSeries.priceToCoordinate(zone.bottom);
    if([x1,x2,y1,y2].some(v=>v===null||v===undefined))return;
    const rx=Math.min(x1,x2),ry=Math.min(y1,y2),rw=Math.max(2,Math.abs(x2-x1)),rh=Math.max(2,Math.abs(y2-y1));
    ctx.fillStyle=color;
    ctx.fillRect(rx,ry,rw,rh);
    if(border){ctx.strokeStyle=border;ctx.lineWidth=1;ctx.strokeRect(rx,ry,rw,rh);}
    if(label&&rw>40&&rh>10){ctx.fillStyle=border||color;ctx.font='9px monospace';ctx.fillText(label,rx+4,ry+rh-3);}
  };
  if(showZones&&zones)zones.forEach(z=>drawBand(Array.isArray(z)?{index:0,bottom:z[0],top:z[1]}:{...z,index:0,end_index:candles.length-1},'rgba(101,207,255,.05)'));
  if(showFvgs&&fvgs)fvgs.forEach(z=>drawBand(z,z.type==='BULLISH'?'rgba(0,214,154,.08)':'rgba(255,94,110,.08)'));
  if(showOB&&orderBlocks)orderBlocks.forEach(ob=>drawBand({...ob,end_index:candles.length-1},ob.type==='BULLISH_OB'?'rgba(0,214,154,.10)':'rgba(255,94,110,.10)',ob.type==='BULLISH_OB'?'rgba(0,214,154,.35)':'rgba(255,94,110,.35)',ob.type==='BULLISH_OB'?'OB [Demand]':'OB [Supply]'));
}
export function formatOutcomeBadge(signal) {
  if (!signal) return { text: 'UNKNOWN', color: '#788795', className: 'badge-unknown' };
  const status = (signal.status || 'OPEN').toUpperCase();
  if (status === 'WIN') {
    const r = signal.pnl_r != null ? Number(signal.pnl_r).toFixed(1) : Number(signal.risk_reward || 2.0).toFixed(1);
    return { text: `WIN +${r}R`, color: '#00d69a', className: 'badge-win' };
  }
  if (status === 'LOSS') {
    const r = signal.pnl_r != null ? Number(signal.pnl_r).toFixed(1) : '-1.0';
    return { text: `LOSS ${r > 0 ? '-' + r : r}R`, color: '#ff5e6e', className: 'badge-loss' };
  }
  if (signal.floating_r != null) {
    const r = Number(signal.floating_r).toFixed(1);
    return { text: `ACTIVE (${r > 0 ? '+' : ''}${r}R)`, color: '#65cfff', className: 'badge-open' };
  }
  return { text: 'ACTIVE', color: '#65cfff', className: 'badge-open' };
}

export function filterSignals(signals, tab = 'ALL') {
  if (!Array.isArray(signals)) return [];
  const t = tab.toUpperCase();
  if (t === 'ACTIVE') return signals.filter(s => (s.status || 'OPEN').toUpperCase() === 'OPEN');
  if (t === 'HISTORY') return signals.filter(s => ['WIN', 'LOSS', 'EXPIRED'].includes((s.status || '').toUpperCase()));
  return signals;
}

export function symbolToTradingView(symbol) {
  const s = (symbol || 'BTCUSDT').toUpperCase().trim();
  if (!s) return 'BINANCE:BTCUSDT.P';
  if (s.startsWith('BINANCE:')) return s.endsWith('.P') ? s : s + '.P';
  return `BINANCE:${s}.P`;
}

export function timeframeToTradingView(timeframe) {
  const tf = (timeframe || '15m').toLowerCase().trim();
  const map = {
    '1m': '1',
    '3m': '3',
    '5m': '5',
    '15m': '15',
    '30m': '30',
    '1h': '60',
    '2h': '120',
    '4h': '240',
    '6h': '360',
    '12h': '720',
    '1d': 'D',
    '1w': 'W',
  };
  return map[tf] || '15';
}

export function formatTrendlineShape(line) {
  return {
    points: [
      { time: line.time1, price: line.price1 },
      { time: line.next_time || line.time2, price: line.next_price || line.price2 }
    ],
    options: {
      shape: 'trend_line',
      lock: true,
      disableSelection: false,
      overrides: {
        linecolor: line.is_resistance ? '#f5b84b' : '#65cfff',
        linewidth: 2,
      }
    }
  };
}

export function formatOrderBlockShape(ob, lastTime) {
  const t1 = Math.floor((ob.timestamp || Date.now()) / 1000);
  const t2 = lastTime || t1 + 3600 * 4;
  const isBull = ob.type === 'BULLISH_OB';
  return {
    points: [
      { time: t1, price: ob.top },
      { time: t2, price: ob.bottom }
    ],
    options: {
      shape: 'rectangle',
      text: isBull ? '+OB [Demand]' : '-OB [Supply]',
      lock: true,
      disableSelection: false,
      overrides: {
        color: isBull ? 'rgba(0, 214, 154, 0.45)' : 'rgba(255, 94, 110, 0.45)',
        backgroundColor: isBull ? 'rgba(0, 214, 154, 0.20)' : 'rgba(255, 94, 110, 0.20)',
        fillBackground: true,
        linewidth: 1,
        textcolor: isBull ? '#00d69a' : '#ff5e6e',
        fontsize: 10,
        showLabel: true,
      }
    }
  };
}

export function formatStructureBreakShape(item) {
  const isBOS = item.type === 'BOS';
  const color = item.is_bullish ? '#00d69a' : '#ff5e6e';
  const textLabel = isBOS ? 'BOS' : 'CHoCH';
  return {
    points: [
      { time: item.time_start, price: item.price },
      { time: item.time_end + 3600 * 2, price: item.price }
    ],
    options: {
      shape: 'trend_line',
      text: textLabel,
      lock: true,
      disableSelection: false,
      overrides: {
        linecolor: isBOS ? '#788795' : color,
        linewidth: 1,
        linestyle: 2, // dashed
        textcolor: isBOS ? '#a7b2bd' : color,
        fontsize: 10,
        showLabel: true,
      }
    }
  };
}

export function formatPositionShape(signal, lastCandle) {
  if (!signal || !signal.entry_price || !lastCandle) return null;
  const entry = Number(signal.entry_price);
  const sl = Number(signal.stop_loss);
  const tp = Number(signal.tp2 || signal.take_profit || signal.tp1);
  const isShort = signal.signal_type === 'SHORT';
  const shape = isShort ? 'short_position' : 'long_position';
  const timeStep = 900;
  return {
    points: [
      { time: lastCandle.time, price: entry },
      { time: lastCandle.time + timeStep * 8, price: entry }
    ],
    options: {
      shape,
      lock: true,
      disableSelection: false,
      overrides: {
        stopLevel: { price: sl },
        profitLevel: { price: tp },
        stopBackground: 'rgba(255, 94, 110, 0.22)',
        profitBackground: 'rgba(0, 214, 154, 0.22)',
        linecolor: '#65cfff',
        showPriceLabels: true,
      }
    }
  };
}

export function createTradingViewDatafeed(fetchChartFn, onRealtimeSubscription = null) {
  const subscribers = new Map();
  return {
    onReady: (cb) => {
      setTimeout(() => cb({
        supported_resolutions: ['1', '5', '15', '60', '240', 'D'],
        supports_marks: false,
        supports_timescale_marks: false,
        supports_time: true,
      }), 0);
    },
    searchSymbols: (userInput, exchange, symbolType, onResult) => {
      onResult([]);
    },
    resolveSymbol: (symbolName, onResolve, onError) => {
      const s = (symbolName || 'BTCUSDT').toUpperCase().replace('BINANCE:', '').replace('.P', '').trim();
      let scale = 100;
      if (s.includes('PEPE') || s.includes('SHIB') || s.includes('BONK') || s.includes('FLOKI')) {
        scale = 100000;
      } else if (s.includes('DOGE') || s.includes('ADA') || s.includes('XRP') || s.includes('TRX')) {
        scale = 10000;
      }
      setTimeout(() => onResolve({
        name: s,
        ticker: s,
        description: `${s} Perpetual`,
        type: 'crypto',
        session: '24x7',
        exchange: 'Binance',
        listed_exchange: 'Binance',
        timezone: 'Asia/Ho_Chi_Minh',
        format: 'price',
        pricescale: scale,
        minmov: 1,
        has_intraday: true,
        supported_resolutions: ['1', '5', '15', '60', '240', 'D'],
        intraday_multipliers: ['1', '5', '15', '60', '240'],
        has_daily: true,
      }), 0);
    },
    getBars: async (symbolInfo, resolution, periodParams, onHistory, onError) => {
      try {
        const tfMap = { '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m', '60': '1h', '120': '2h', '240': '4h', 'D': '1d' };
        const tf = tfMap[resolution] || '15m';
        const endTime = (!periodParams.firstDataRequest && periodParams.to) ? Math.floor(periodParams.to * 1000) : null;
        const payload = await fetchChartFn(symbolInfo.name, tf, endTime);
        if (!payload?.candles?.length) {
          onHistory([], { noData: true });
          return;
        }
        const bars = payload.candles.map(k => ({
          time: k.time * 1000,
          open: parseFloat(k.open),
          high: parseFloat(k.high),
          low: parseFloat(k.low),
          close: parseFloat(k.close),
          volume: parseFloat(k.volume || 0),
        }));
        bars.sort((a, b) => a.time - b.time);
        onHistory(bars, { noData: false });
      } catch (err) {
        onError(err.message || 'Error fetching bars');
      }
    },
    subscribeBars: (symbolInfo, resolution, onTick, listenerGuid) => {
      subscribers.set(listenerGuid, { symbol: symbolInfo.name, resolution, onTick });
      if (onRealtimeSubscription) onRealtimeSubscription(symbolInfo.name, resolution, onTick);
    },
    unsubscribeBars: (listenerGuid) => {
      subscribers.delete(listenerGuid);
    }
  };
}

export function formatSignalPlainExplanation(signal) {
  if (!signal) return '';
  const type = (signal.signal_type || 'LONG').toUpperCase();
  const pattern = (signal.pattern || '').toUpperCase();
  const isLong = type === 'LONG';

  if (pattern.includes('LINA') || pattern.includes('RSI_PULLBACK')) {
    if (isLong) {
      return '🟢 Sóng Lina RSI (LONG) — Giá hồi về vùng Cầu (40-55) rồi bật tăng tiếp diễn.';
    } else {
      return '🔴 Sóng Lina RSI (SHORT) — Giá hồi về vùng Cung (45-60) rồi đảo chiều giảm tiếp diễn.';
    }
  }

  if (pattern.includes('ORDER_BLOCK') || pattern.includes('SMC')) {
    if (isLong) {
      return '🟢 Đánh LÊN (LONG) — Giá chạm vùng cá voi gom hàng (+OB), kỳ vọng bật tăng.';
    } else {
      return '🔴 Đánh XUỐNG (SHORT) — Giá chạm vùng cá voi xả hàng (-OB), kỳ vọng rơi giá.';
    }
  }

  if (pattern.includes('MEAN_REVERSION')) {
    if (isLong) {
      return '🟢 Đánh LÊN (LONG) — Phe bán cạn lực chạm cản dưới quá bán, kỳ vọng giật ngược về giá trung bình.';
    } else {
      return '🔴 Đánh XUỐNG (SHORT) — Phe mua hụt hơi chạm cản trên quá mua, kỳ vọng ép giảm về giá trung bình.';
    }
  }

  if (pattern.includes('BREAKOUT') || pattern.includes('TRENDLINE')) {
    if (isLong) {
      return '🟢 Phá vỡ cản (Breakout) — Giá bứt phá mạnh qua cản trên, đánh thuận sóng tăng.';
    } else {
      return '🔴 Gãy hỗ trợ (Breakdown) — Giá sập thủng cản dưới, đánh thuận sóng giảm.';
    }
  }

  return isLong ? '🟢 Kèo Mua (LONG) theo cấu trúc thị trường' : '🔴 Kèo Bán (SHORT) theo cấu trúc thị trường';
}

export function filterSymbols(symbols, query, limit = 50) {
  if (!Array.isArray(symbols)) return [];
  const rawQ = (query || '').toUpperCase().trim();
  if (!rawQ) return symbols.slice(0, limit);
  const q = rawQ.endsWith('USDT') && rawQ.length > 4 ? rawQ.slice(0, -4) : rawQ;

  const prefixMatches = [];
  const substringMatches = [];

  for (const s of symbols) {
    const norm = String(s).toUpperCase();
    const base = norm.replace(/USDT$/, '').replace(/^1000/, '');
    if (norm.startsWith(q) || base.startsWith(q)) {
      prefixMatches.push(s);
    } else if (norm.includes(q) || base.includes(q)) {
      substringMatches.push(s);
    }
  }

  return [...prefixMatches, ...substringMatches].slice(0, limit);
}

if(typeof window!=='undefined')window.ChartStream={upsertKline,createThrottle,chooseMarketStructure,trendlinePoints,drawZoneBands,structureToOverlays,shouldShowConnectingStatus,clientReconnectDelay,formatOutcomeBadge,filterSignals,formatCandleCountdown,symbolToTradingView,timeframeToTradingView,formatTrendlineShape,formatOrderBlockShape,createTradingViewDatafeed,formatStructureBreakShape,formatPositionShape,formatSignalPlainExplanation,filterSymbols};
