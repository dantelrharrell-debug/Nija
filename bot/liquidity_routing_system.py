"""NIJA exchange-aware smart liquidity routing."""
import logging, math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.liquidity_routing")

class Exchange(Enum):
    COINBASE="coinbase"; KRAKEN="kraken"; BINANCE="binance"; OKX="okx"
class OrderType(Enum):
    MARKET="market"; LIMIT="limit"

@dataclass
class LiquidityLevel:
    exchange: Exchange; price: Decimal; size: Decimal
    def __lt__(self, other): return self.price < other.price

@dataclass
class OrderBook:
    exchange: Exchange; symbol: str; bids: List[LiquidityLevel]; asks: List[LiquidityLevel]; timestamp: datetime
    def get_best_bid(self): return self.bids[0] if self.bids else None
    def get_best_ask(self): return self.asks[0] if self.asks else None
    def to_dict(self):
        return {"exchange":self.exchange.value,"symbol":self.symbol,
                "best_bid":float(self.bids[0].price) if self.bids else None,
                "best_ask":float(self.asks[0].price) if self.asks else None,
                "bid_depth":sum(float(x.size) for x in self.bids),
                "ask_depth":sum(float(x.size) for x in self.asks),"timestamp":self.timestamp.isoformat()}

@dataclass
class RouteSegment:
    exchange: Exchange; price: Decimal; size: Decimal; side: str; estimated_fee: Decimal
    def total_cost(self): return self.price*self.size+self.estimated_fee
    def to_dict(self):
        return {"exchange":self.exchange.value,"price":float(self.price),"size":float(self.size),
                "side":self.side,"estimated_fee":float(self.estimated_fee),"total_cost":float(self.total_cost())}

@dataclass
class RoutedOrder:
    symbol:str; side:str; total_size:Decimal; segments:List[RouteSegment]; avg_price:Decimal
    total_cost:Decimal; total_fees:Decimal; slippage_pct:float; created_at:datetime
    def to_dict(self):
        return {"symbol":self.symbol,"side":self.side,"total_size":float(self.total_size),
                "segments":[x.to_dict() for x in self.segments],"avg_price":float(self.avg_price),
                "total_cost":float(self.total_cost),"total_fees":float(self.total_fees),
                "slippage_pct":self.slippage_pct,"num_venues":len({x.exchange for x in self.segments}),
                "created_at":self.created_at.isoformat()}

class LiquidityRoutingSystem:
    """Routes using price/fees plus venue depth, spread, and realized volatility."""
    DEFAULT_PROFILE={"depth_weight":.40,"spread_weight":.25,"volatility_weight":.25,
                     "fee_weight":.10,"volatility_soft_limit_pct":1.5,"max_participation_rate":.80}
    def __init__(self, config:Dict=None):
        self.config=config or {}
        self.fee_rates={Exchange.COINBASE:Decimal("0.006"),Exchange.KRAKEN:Decimal("0.0026"),
                        Exchange.BINANCE:Decimal("0.001"),Exchange.OKX:Decimal("0.001")}
        for k,v in self.config.get("fee_rates",{}).items():
            e=self._exchange(k)
            if e: self.fee_rates[e]=Decimal(str(v))
        self.order_books={}; self._mid_history={}; self.total_orders_routed=0; self.total_savings_usd=Decimal("0")
        self._window=max(3,int(self.config.get("volatility_window",24)))
        self._max_penalty_bps=max(0.,float(self.config.get("max_microstructure_penalty_bps",20.)))
    @staticmethod
    def _exchange(v):
        if isinstance(v,Exchange): return v
        try: return Exchange(str(v).lower())
        except (ValueError,TypeError): return None
    def _profile(self,e):
        p=dict(self.DEFAULT_PROFILE); p.update(self.config.get("venue_profiles",{}).get(e.value,{}) or {}); return p
    def update_order_book(self,exchange,symbol,bids,asks):
        exchange=self._exchange(exchange)
        if exchange is None: raise ValueError("Unsupported exchange")
        b=[LiquidityLevel(exchange,p,s) for p,s in bids]; a=[LiquidityLevel(exchange,p,s) for p,s in asks]
        b.sort(key=lambda x:x.price,reverse=True); a.sort(key=lambda x:x.price)
        book=OrderBook(exchange,symbol,b,a,datetime.now()); self.order_books.setdefault(exchange,{})[symbol]=book
        if b and a and b[0].price>0 and a[0].price>0:
            h=self._mid_history.setdefault(exchange,{}).setdefault(symbol,[]); h.append((b[0].price+a[0].price)/2)
            if len(h)>self._window: del h[:-self._window]
    def _vol_pct(self,e,symbol):
        h=self._mid_history.get(e,{}).get(symbol,[]); r=[float((c-p)/p) for p,c in zip(h,h[1:]) if p>0]
        if len(r)<2:return 0.0
        m=sum(r)/len(r); return math.sqrt(sum((x-m)**2 for x in r)/len(r))*100
    def get_venue_metrics(self,exchange,symbol,side,target_size=None):
        e=self._exchange(exchange); book=self.order_books.get(e,{}).get(symbol) if e else None
        if not book or not book.bids or not book.asks:return None
        side=side.lower(); levels=book.asks if side=="buy" else book.bids
        bid,ask=book.bids[0],book.asks[0]; spread=max(0.,float((ask.price-bid.price)/bid.price*100))
        depth=sum((x.size for x in levels),Decimal("0")); target=target_size if target_size and target_size>0 else depth
        depth_score=min(1.,float(depth/target)) if target>0 else 0.; p=self._profile(e)
        vol=self._vol_pct(e,symbol); vol_score=1/(1+vol/max(.01,float(p["volatility_soft_limit_pct"])))
        spread_score=1/(1+spread/max(.01,float(self.config.get("spread_soft_limit_pct",.20))))
        fee=float(self.fee_rates.get(e,Decimal("0.001"))*100); fee_score=1/(1+fee/max(.01,float(self.config.get("fee_soft_limit_pct",.60))))
        weights=[float(p[x]) for x in ("depth_weight","spread_weight","volatility_weight","fee_weight")]; total=sum(weights) or 1
        score=sum(v*w/total for v,w in zip((depth_score,spread_score,vol_score,fee_score),weights))
        return {"exchange":e.value,"symbol":symbol,"side":side,"venue_score":max(0.,min(1.,score)),
                "spread_pct":spread,"side_depth":float(depth),"top5_depth":float(sum((x.size for x in levels[:5]),Decimal("0"))),
                "depth_score":depth_score,"realized_volatility_pct":vol,"volatility_score":vol_score,
                "fee_pct":fee,"fee_score":fee_score,"max_participation_rate":float(p["max_participation_rate"])}
    def _effective(self,level,symbol,side,size):
        m=self.get_venue_metrics(level.exchange,symbol,side,size); score=m["venue_score"] if m else 0
        fee=self.fee_rates.get(level.exchange,Decimal("0.001")); penalty=Decimal(str((1-score)*self._max_penalty_bps/10000))
        return level.price*(1+fee+penalty) if side=="buy" else level.price*(1-fee-penalty)
    def _levels(self,symbol,side):
        attr="asks" if side=="buy" else "bids"
        return [x for books in self.order_books.values() if symbol in books for x in getattr(books[symbol],attr)]
    def find_best_route(self,symbol,side,size,max_slippage_pct=1.0):
        side=side.lower()
        if side not in {"buy","sell"}: raise ValueError("side must be 'buy' or 'sell'")
        if size<=0: raise ValueError("size must be positive")
        levels=self._levels(symbol,side)
        if not levels:return None
        levels.sort(key=lambda x:self._effective(x,symbol,side,size),reverse=side=="sell")
        venues={x.exchange for x in levels}; caps={}
        for e in venues:
            m=self.get_venue_metrics(e,symbol,side,size); p=self._profile(e)
            if len(venues)==1: caps[e]=size
            elif m:
                rate=min(1.,max(.05,float(p["max_participation_rate"])*max(.25,m["volatility_score"])))
                caps[e]=min(size,Decimal(str(m["side_depth"]))*Decimal(str(rate)))
            else:caps[e]=Decimal("0")
        used={e:Decimal("0") for e in venues}; remain=size; seg=[]; total=Decimal("0"); fees=Decimal("0")
        for level in levels:
            room=max(Decimal("0"),caps[level.exchange]-used[level.exchange]); fill=min(remain,level.size,room)
            if fill<=0:continue
            fee=fill*level.price*self.fee_rates.get(level.exchange,Decimal("0.001")); s=RouteSegment(level.exchange,level.price,fill,side,fee)
            seg.append(s); used[level.exchange]+=fill; remain-=fill; total+=s.total_cost(); fees+=fee
            if remain<=0:break
        filled=size-remain
        if filled<=0:return None
        avg=(total-fees)/filled; raw=[x.price for x in levels]; best=min(raw) if side=="buy" else max(raw)
        slippage=float(abs(avg-best)/best*100); self.total_orders_routed+=1
        return RoutedOrder(symbol,side,filled,seg,avg,total,fees,slippage,datetime.now())
    def get_best_price(self,symbol,side):
        levels=self._levels(symbol,side)
        if not levels:return None
        x=min(levels,key=lambda y:y.price) if side=="buy" else max(levels,key=lambda y:y.price); return x.exchange,x.price
    def get_best_venue(self,symbol,side,target_size):
        out=[]
        for e,books in self.order_books.items():
            if symbol not in books:continue
            m=self.get_venue_metrics(e,symbol,side,target_size)
            if not m:continue
            level=books[symbol].get_best_ask() if side=="buy" else books[symbol].get_best_bid(); m=dict(m)
            m["best_price"]=float(level.price); m["effective_unit_price"]=float(self._effective(level,symbol,side,target_size)); out.append(m)
        if not out:return None
        return min(out,key=lambda x:x["effective_unit_price"]) if side=="buy" else max(out,key=lambda x:x["effective_unit_price"])
    def get_liquidity_summary(self,symbol):
        bid=sum((x.size for x in self._levels(symbol,"sell")),Decimal("0")); ask=sum((x.size for x in self._levels(symbol,"buy")),Decimal("0"))
        ex=[e.value for e,b in self.order_books.items() if symbol in b]; bb=self.get_best_price(symbol,"sell"); ba=self.get_best_price(symbol,"buy")
        return {"symbol":symbol,"total_bid_size":float(bid),"total_ask_size":float(ask),
                "best_bid":{"exchange":bb[0].value,"price":float(bb[1])} if bb else None,
                "best_ask":{"exchange":ba[0].value,"price":float(ba[1])} if ba else None,
                "spread_pct":float((ba[1]-bb[1])/bb[1]*100) if bb and ba else None,"exchanges":ex,"num_exchanges":len(ex),
                "venue_metrics":{e:{"buy":self.get_venue_metrics(Exchange(e),symbol,"buy"),"sell":self.get_venue_metrics(Exchange(e),symbol,"sell")} for e in ex}}
    def get_stats(self):
        return {"total_orders_routed":self.total_orders_routed,"total_savings_usd":float(self.total_savings_usd),
                "avg_savings_per_order":float(self.total_savings_usd/self.total_orders_routed) if self.total_orders_routed else 0.,
                "exchanges_tracked":len(self.order_books),"symbols_available":len({s for b in self.order_books.values() for s in b}),"venue_aware_routing":True}

liquidity_routing_system=LiquidityRoutingSystem()
