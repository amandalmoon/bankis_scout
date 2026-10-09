"""Date-only DART disclosures to strategy-agnostic observation records.
Never infer bullishness, missing exact time, or economic materiality from headlines.
"""
from __future__ import annotations
import csv
from pathlib import Path
from .intelligence import OBS_COLUMNS, IntelDataError, _ts, _url
from .engine import RISK_TERMS


def disclosure_to_observations(path, *, ingested_at):
    import pandas as pd
    when=_ts(ingested_at,'ingested_at')
    p=Path(path)
    if not p.is_file():raise IntelDataError(f'No disclosure CSV at {path}')
    rows=pd.read_csv(p,dtype={'code':'string'},keep_default_na=False)
    fields={'code','published_at','event_type','title','source_url'}
    if not fields.issubset(set(rows)):
        raise IntelDataError(f'{p.name} missing disclosure columns {fields-set(rows)}')
    out=[]
    for _,r in rows.iterrows():
        pub=_ts(r['published_at'],'published_at')
        if pub>when:
            # Do not force information to be known before a conservative publication gate.
            continue
        url=str(r['source_url']).strip()
        if not _url(url):
            continue
        typ=str(r['event_type']).strip().lower()
        title=str(r['title']).strip()
        risk=(typ=='risk') or any(x in title for x in RISK_TERMS)
        issuer=str(r['code']).zfill(6)
        out.append({
            'id':f'DART-{issuer}-{url.split("rcpNo=")[-1]}',
            'entity':f'종목 {issuer}', 'category':'RISK' if risk else 'CORPORATE',
            'metric':'','fact':f'DART 공시: {title}. 제목만으로 수익 영향 미확정. 공개 시각이 없으면 23:59:59 KST 보수적 게이트.',
            'value':'','unit':'','previous_value':'','previous_observed_at':'','previous_source_url':'',
            'expected_value':'','expected_asof':'','expected_source_url':'',
            'observed_at':pub.isoformat(),'available_at':pub.isoformat(),
            'ingested_at':when.isoformat(),
            'source_url':url,'source_name':'OpenDART / 공식공시 (본문 독립 검토 필요)',
            'source_class':'PRIMARY','venue':'KRX','severity':'HIGH' if risk else 'MEDIUM',
            'potential_impact':'위험 공시 상세 조항 확인 필요' if risk else '영향 방향과 크기 미확정',
            'counter_ids':'','followup_at':'',
        })
    return out


def save_observations_csv(path, observations):
    out=Path(path);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=OBS_COLUMNS,extrasaction='ignore')
        writer.writeheader();writer.writerows(observations)
    return out
