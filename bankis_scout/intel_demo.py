"""Transparent entirely fictional Market Intelligence demo fixtures."""
from __future__ import annotations
import csv
from pathlib import Path
from .intelligence import OBS_COLUMNS, CAL_COLUMNS


def synthetic_intel(folder):
    p=Path(folder);p.mkdir(parents=True,exist_ok=True)
    core={'observed_at':'2026-10-08T15:30:00+09:00',
          'available_at':'2026-10-08T17:00:00+09:00',
          'ingested_at':'2026-10-08T17:10:00+09:00',
          'source_url':'https://example.invalid/synthetic-market-observation',
          'source_name':'SYNTHETIC ONLY · 임의 생성 정보','source_class':'USER_SUPPLIED',
          'previous_observed_at':'2026-10-07T15:30:00+09:00',
          'previous_source_url':'https://example.invalid/synthetic-prior',
          'expected_asof':'2026-10-07T09:00:00+09:00',
          'expected_source_url':'https://example.invalid/synthetic-consensus',
          'venue':'KRX','severity':'MEDIUM','potential_impact':'가설 검토 전. 투자 방향성 주장 없음.',
          'counter_ids':'','followup_at':''}
    rows=[
        dict(core,id='FAKE-MACRO-001',entity='가상 지수 K',category='SURPRISE',metric='가상 지수 변화율',fact='실제 관측값이 사전 예상치보다 높았다는 가정.',value='2.3',unit='%',previous_value='0.9',expected_value='1.5',severity='HIGH',counter_ids='FAKE-MACRO-002',potential_impact='예상보다 큰 변화는 재평가 가설을 유도할 수 있으나 방향성을 확정하지 않음.'),
        dict(core,id='FAKE-MACRO-002',entity='가상 지수 K',category='RISK',metric='',fact='비슷한 시점의 다른 가상 자료가 결과 해석과 상충한다는 가정.',value='',unit='',previous_value='',expected_value='',severity='MEDIUM',counter_ids='FAKE-MACRO-001'),
        dict(core,id='FAKE-LIQ-003',entity='가상 종목 R',category='LIQUIDITY',metric='스프레드',fact='호가 스프레드가 전일 관측보다 확대됐다는 가정.',value='55',unit='bp',previous_value='12',expected_value='',severity='HIGH'),
        dict(core,id='FAKE-VOL-004',entity='가상 업종 S',category='ABNORMAL',metric='일간 거래량 상대비',fact='거래량이 평소보다 크게 늘어난 가상 사례.',value='4.7',unit='배',previous_value='1.4',expected_value='',severity='HIGH'),
        dict(core,id='FAKE-CORP-005',entity='가상 법인 T',category='CORPORATE',metric='',fact='주식 공급 증가와 관련된 조건 변경이 발생했다는 가정.',value='',unit='',previous_value='',expected_value='',severity='MEDIUM'),
        dict(core,id='FAKE-CONFLICT-006-A',entity='가상 종목 Q',category='FLOWS',metric='순매수 추정금액',fact='출처 A의 가상 추정값.',value='90',unit='억원',previous_value='',expected_value='',source_url='https://example.invalid/synthetic-source-a'),
        dict(core,id='FAKE-CONFLICT-006-B',entity='가상 종목 Q',category='FLOWS',metric='순매수 추정금액',fact='출처 B의 가상 추정값(상충).',value='120',unit='억원',previous_value='',expected_value='',source_url='https://example.invalid/synthetic-source-b'),
    ]
    cal=[{'id':'FAKE-CALENDAR-001','entity':'가상 산업','event':'가상 정책 발표 예정',
          'event_at':'2026-10-12T10:30:00+09:00',
          'announced_at':'2026-10-07T09:00:00+09:00',
          'ingested_at':'2026-10-07T09:10:00+09:00',
          'source_url':'https://example.invalid/synthetic-calendar','source_name':'SYNTHETIC ONLY',
          'certainty':'TENTATIVE','exposure':'가상 업종','expected_value':'','unit':''}]
    for path,data,cols in [(p/'observations.csv',rows,OBS_COLUMNS),(p/'calendar.csv',cal,CAL_COLUMNS)]:
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(data)
    (p/'SYNTHETIC_DATA.txt').write_text('All observations are fictitious. Not market data, not financial advice.\n',encoding='utf-8')
    return p
