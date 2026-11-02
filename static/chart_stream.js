export function shouldShowConnectingStatus({marketReadyState}) {
  return marketReadyState !== 1;
}

export function clientReconnectDelay(attempt) {
  return Math.min(1000 * 2 ** Math.max(0, attempt - 1), 30000);
}

export function structureToOverlays(payload) {
  if (!payload || typeof payload !== "object") {
    return {trendlines: [], zone_bands: [], fvgs: [], order_blocks: [], regression_channel: {}, forecast_path: [], signal: null};
  }
  return {
    trendlines: Array.isArray(payload.trendlines) ? payload.trendlines : [],
    zone_bands: Array.isArray(payload.zone_bands) ? payload.zone_bands : [],
    fvgs: Array.isArray(payload.fvgs) ? payload.fvgs : [],
    order_blocks: Array.isArray(payload.order_blocks) ? payload.order_blocks : [],
    regression_channel: payload.regression_channel || {},
    forecast_path: Array.isArray(payload.forecast_path) ? payload.forecast_path : [],
    signal: payload.signal || null,
  };
}

export function formatCandleCountdown(nowMs, timeframe = '15m') {
  const secMap = { '1m': 60, '3m': 180, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400 };
  const intervalSec = secMap[timeframe] || 900;
  const nowSec = Math.floor(nowMs / 1000);
  const remainingSec = intervalSec - (nowSec % intervalSec);
  const m = Math.floor(remainingSec / 60);
  const s = remainingSec % 60;
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

if(typeof window!=='undefined')window.ChartStream={upsertKline,createThrottle,chooseMarketStructure,trendlinePoints,drawZoneBands,structureToOverlays,shouldShowConnectingStatus,clientReconnectDelay,formatOutcomeBadge,filterSignals,formatCandleCountdown};
