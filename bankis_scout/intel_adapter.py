"""Optional source-labelled import from the existing BankIS daily CSV bundle.

A source URL here is a declared lineage link, not independent authentication. This
adapter produces descriptive market intelligence (both positive and negative moves)
without using momentum screen scores or future prices.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path
import statistics
import pandas as pd
from .data import csv_read, DAILY_FIELDS, INDEX_FIELDS, prepare_daily,prepare_index
from .settings import parse_asof, last_allowed_daily_date, KST
from .intelligence import IntelDataError,_url


def describe_daily_bundle(data_dir, asof, *, source_url, available_at, ingested_at, max_items=12, blocked_codes=None):
    now=parse_asof(asof)
    from .intelligence import _ts
    available=_ts(available_at,'available_at'); ingested=_ts(ingested_at,'ingested_at')
    if not _url(source_url):raise IntelDataError('HTTPS upstream source_url required')
    if available>now or ingested>now or available>ingested:
        raise IntelDataError('Raw historical bars were not made available/ingested by asof')
    folder=Path(data_dir)
    raw_daily=csv_read(folder/'daily.csv',DAILY_FIELDS)
    raw_index=csv_read(folder/'index_daily.csv',INDEX_FIELDS)
    cutoff=last_allowed_daily_date(now)
    daily,issues=prepare_daily(raw_daily,cutoff)
    index,ixissues=prepare_index(raw_index,cutoff)
    observations=[]; excluded=[]
    def emit(id_, entity, category, metric, value, unit, previous, day, fact, sev='MEDIUM',venue='KRX',impact=''):
        observed=datetime.combine(day,time(15,30),tzinfo=KST)
        if observed>available:
            excluded.append({'id':id_,'reason':'OBSERVATION_LATER_THAN_DECLARED_AVAILABLE'})
            return
        observations.append({'id':id_,'entity':entity,'category':category,'metric':metric,
                             'value':round(float(value),6),'previous_value':round(float(previous),6) if previous is not None else '',
                             'previous_observed_at':datetime.combine(day-timedelta(days=1),time(15,30),tzinfo=KST).isoformat() if previous is not None else '',
                             'previous_source_url':source_url if previous is not None else '',
                             'expected_value':'','expected_asof':'','expected_source_url':'','unit':unit,'fact':fact,
                             'observed_at':observed.isoformat(),'available_at':available.isoformat(),
                             'ingested_at':ingested.isoformat(),'source_url':source_url,
                             'source_name':'명시된 원자료 CSV / 원천 독립 확인 전',
                             'source_class':'USER_SUPPLIED','venue':venue,'severity':sev,
                             'potential_impact':impact,'counter_ids':'','followup_at':''})
    # Direct evidence from given benchmark closes, not a portfolio signal.
    for market, group in index.groupby('market'):
        if market in ixissues:excluded.append({'id':market,'reason':'INVALID_MARKET_BENCHMARK'});continue
        g=group.sort_values('date')
        if len(g)<2:continue
        a,c=g.iloc[-2],g.iloc[-1]
        day=c['date']
        ret=100*(c['close']/a['close']-1)
        prior=None  # avoid fabricating previous observation/publication timestamp
        emit(f'MARKET-{market}-{day}',market,'MARKET','일간 등락률',ret,'%',prior,day,
             f'{day} 기준 {market} 종가 변화. 비교는 제공된 해당 지수 시계열에 한정.',
             'HIGH' if abs(ret)>=2 else 'MEDIUM',venue='KRX',
             impact='시장 방향을 관측한 값이지 향후 방향 예측이나 매수 지시가 아닙니다.')
    # Both positive and negative observed anomalies. No arbitrary stock picks.
    detected=[]
    for code,g in daily.groupby('code'):
        if blocked_codes and str(code) in blocked_codes:
            excluded.append({'id':code,'reason':'INCOMPLETE_RECENT_SESSION_WINDOW'})
            continue
        if code in issues:
            excluded.append({'id':code,'reason':'INVALID_DAILY_BAR'})
            continue
        gg=g.sort_values('date'); last=gg.iloc[-1]
        if last['date'] != cutoff and (cutoff-last['date']).days>5:
            excluded.append({'id':code,'reason':'STALE_TICKER_LAST_BAR'});continue
        if len(gg)<22:continue
        p=gg.iloc[-2];prev20=gg.iloc[-21:-1]
        medvol=float(prev20['volume'].median()); medturn=float(prev20['turnover_krw'].median())
        if medvol<=0 or medturn<=0:continue
        ret=100*(last['close']/p['close']-1)
        rvol=float(last['volume'])/medvol
        turnover_ratio=float(last['turnover_krw'])/medturn
        if abs(ret)<4 and rvol<2.5 and turnover_ratio<2.5:continue
        # Ranking only controls report length; it is NOT an investment score.
        salience=max(abs(ret)/4,rvol/2.5,turnover_ratio/2.5)
        detected.append((salience,str(code),str(last['name']),str(last['date']),ret,rvol,turnover_ratio,last['date'],
                         str(last['market'])))
    for _,code,name,d,ret,rvol,tvr,day,market in sorted(detected,reverse=True)[:max_items]:
        sev='HIGH' if abs(ret)>=10 or tvr>=5 else 'MEDIUM'
        emit(f'PRICE-{code}-{d}',f'{name} ({code})','ABNORMAL','일간 등락률',ret,'%',None,day,
             f'일간 등락률 {ret:+.2f}%, 거래량 상대비 {rvol:.2f}배, 거래대금 상대비 {tvr:.2f}배 (각 과거 20일 중앙값 대비).',
             sev,venue='KRX',impact='특이 거래활동 관찰. 상승/하락 원인은 기업 공시와 별도 대조 필요.')
        emit(f'VOL-{code}-{d}',f'{name} ({code})','FLOWS','일간 거래량 상대비',rvol,'배',None,day,
             f'일간 거래량이 과거 20개 거래일 중앙값의 {rvol:.2f}배. 순매수 주체와 방향성은 확인되지 않음.',
             'HIGH' if rvol>=5 else 'MEDIUM',venue='KRX',impact='비정상 활동. 매수세 유입이나 상승을 확정하지 않음.')
    return observations,excluded
