export function shouldShowConnectingStatus({marketReadyState}) {
  return marketReadyState !== 1;
}

export function clientReconnectDelay(attempt) {
  return Math.min(1000 * 2 ** Math.max(0, attempt - 1), 30000);
}

export function structureToOverlays(payload) {
  if (!payload || typeof payload !== "object") {
    return {trendlines: [], zone_bands: [], fvgs: [], signal: null};
  }
  return {
    trendlines: Array.isArray(payload.trendlines) ? payload.trendlines : [],
    zone_bands: Array.isArray(payload.zone_bands) ? payload.zone_bands : [],
    fvgs: Array.isArray(payload.fvgs) ? payload.fvgs : [],
    signal: payload.signal || null,
  };
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
export function drawZoneBands(ctx,chart,candleSeries,zones,fvgs,candles,width,height,showZones=true,showFvgs=true){
  ctx.clearRect(0,0,width,height);if(!candles.length)return;
  const drawBand=(zone,color)=>{const startIndex=Math.max(0,Math.min(candles.length-1,zone.index??0)),endIndex=Math.max(startIndex,Math.min(candles.length-1,zone.end_index??candles.length-1));const x1=chart.timeScale().timeToCoordinate(candles[startIndex].time),x2=chart.timeScale().timeToCoordinate(candles[endIndex].time),y1=candleSeries.priceToCoordinate(zone.top),y2=candleSeries.priceToCoordinate(zone.bottom);if([x1,x2,y1,y2].some(v=>v===null||v===undefined))return;ctx.fillStyle=color;ctx.fillRect(Math.min(x1,x2),Math.min(y1,y2),Math.max(2,Math.abs(x2-x1)),Math.max(2,Math.abs(y2-y1)));};
  if(showZones)zones.forEach(z=>drawBand(Array.isArray(z)?{index:0,bottom:z[0],top:z[1]}:{...z,index:0,end_index:candles.length-1},'rgba(101,207,255,.05)'));
  if(showFvgs)fvgs.forEach(z=>drawBand(z,z.type==='BULLISH'?'rgba(0,214,154,.08)':'rgba(255,94,110,.08)'));
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

if(typeof window!=='undefined')window.ChartStream={upsertKline,createThrottle,chooseMarketStructure,trendlinePoints,drawZoneBands,structureToOverlays,shouldShowConnectingStatus,clientReconnectDelay,formatOutcomeBadge,filterSignals};
