// Standalone educational simulator. No brokerage, network, payment, or production trading imports.
const privateRuns = new WeakMap();
function positive(n) { return Number.isFinite(n) && n > 0; }
function money(n) { if (!Number.isFinite(n)) throw new Error('non-finite accounting'); return n; }
function candleValid(c) {
  return c && ['open','high','low','close'].every(k => positive(c[k]))
    && c.low <= c.high && c.open >= c.low && c.open <= c.high
    && c.close >= c.low && c.close <= c.high;
}
export function createRun({cash=10000,candles,feeRate=0.001,spreadRate=0.0005,maxExposure=1}={}) {
  if (!positive(cash) || !Array.isArray(candles) || candles.length < 2 || !candles.every(candleValid))
    throw new Error('invalid scenario');
  if (![feeRate,spreadRate].every(v=>Number.isFinite(v)&&v>=0&&v<1) || !positive(maxExposure) || maxExposure>1)
    throw new Error('invalid risk settings');
  const run = Object.freeze({kind:'NIJA_VIRTUAL_SIMULATOR_V1'});
  privateRuns.set(run,{cash,position:0,averageCost:0,realized:0,index:0,
    candles:candles.map(c=>Object.freeze({...c})),feeRate,spreadRate,maxExposure,events:[]});
  return run;
}
function state(run) { const s=privateRuns.get(run); if(!s)throw new Error('unknown run');return s; }
export function snapshot(run) {
  const s=state(run),mark=s.candles[s.index].close;
  return Object.freeze({index:s.index,price:mark,cash:s.cash,position:s.position,
    realized:s.realized,unrealized:s.position*(mark-s.averageCost),
    equity:money(s.cash+s.position*mark),events:s.events.length});
}
export function trade(run,side,quantity) {
  const s=state(run);
  if(!['buy','sell'].includes(side)||!positive(quantity)||!Number.isSafeInteger(quantity*1e6))
    throw new Error('invalid order');
  const mid=s.candles[s.index].close;
  const price=money(mid*(side==='buy'?1+s.spreadRate:1-s.spreadRate));
  const gross=money(price*quantity),fee=money(gross*s.feeRate);
  if(side==='buy') {
    const equity=s.cash+s.position*mid;
    if(gross+fee>s.cash+1e-9)throw new Error('insufficient virtual cash');
    if((s.position+quantity)*mid>equity*s.maxExposure+1e-9)throw new Error('exposure limit');
    const cost=money(s.averageCost*s.position+gross+fee);
    s.averageCost=money(cost/(s.position+quantity));
    s.cash=money(s.cash-gross-fee);s.position=money(s.position+quantity);
  } else {
    if(quantity>s.position+1e-9)throw new Error('insufficient virtual position');
    s.realized=money(s.realized+gross-fee-s.averageCost*quantity);
    s.cash=money(s.cash+gross-fee);s.position=money(s.position-quantity);
    if(Math.abs(s.position)<1e-9){s.position=0;s.averageCost=0;}
  }
  const event=Object.freeze({index:s.index,side,quantity,price,fee});
  s.events.push(event);return event;
}
export function advance(run) {
  const s=state(run);
  if(s.index+1>=s.candles.length)throw new Error('replay ended');
  s.index++;return snapshot(run);
}
export function history(run) { return Object.freeze(state(run).events.slice()); }
