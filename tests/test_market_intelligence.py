"""Adversarial checks of strategy-neutral facts, provenance, no-lookahead and KPIs."""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from bankis_scout.intelligence import (
    evaluate_intelligence, evaluate_detection_kpis, IntelDataError, read_csv, OBS_COLUMNS,
)
from bankis_scout.intel_demo import synthetic_intel
from bankis_scout.intel_report import render_html, render_markdown, write_intelligence

ASOF='2026-10-09T08:00:00+09:00'


def ob(**kwargs):
    row={'id':'one','entity':'Synthetic A','category':'SURPRISE','metric':'profit',
         'fact':'Synthetic observation only','value':'100','unit':'KRW','previous_value':'90',
         'expected_value':'80','expected_asof':'2026-10-07T09:00:00+09:00',
         'expected_source_url':'https://example.invalid/prior-consensus',
         'previous_observed_at':'2026-10-07T14:00:00+09:00',
         'previous_source_url':'https://example.invalid/prior-observation','observed_at':'2026-10-08T14:00:00+09:00',
         'available_at':'2026-10-08T15:00:00+09:00',
         'ingested_at':'2026-10-08T15:01:00+09:00',
         'source_url':'https://example.invalid/synthetic','source_name':'Fictional source',
         'source_class':'PRIMARY','venue':'KRX','severity':'HIGH','potential_impact':'unknown',
         'counter_ids':'','followup_at':''}
    row.update(kwargs)
    return row


def evaluate(rows=None, calendar=None, prev=None, asof=ASOF):
    return evaluate_intelligence(rows if rows is not None else [ob()],calendar or [],asof,previous=prev,sample=True)


def test_surprise_vs_previous_distinct():
    rec=evaluate()['observations'][0]
    assert rec['delta']==10 and rec['surprise']==20
    assert rec['delta_pct']==pytest.approx(100*(10/90))
    assert rec['surprise_pct']==25


def test_expected_zero_has_absolute_surprise_no_percentage():
    x=evaluate([ob(expected_value='0')])['observations'][0]
    assert x['surprise']==100 and x['surprise_pct'] is None


def test_missing_expected_not_assumed_zero():
    x=evaluate([ob(expected_value='')])['observations'][0]
    assert x['expected_value'] is None and x['surprise'] is None


def test_future_publication_never_leaks_fact():
    x=ob(id='future-secret',fact='Never display this private future fact',
         available_at='2026-10-09T08:01:00+09:00', ingested_at='2026-10-09T08:01:01+09:00')
    r=evaluate([ob(),x])
    assert r['quality']['excluded']['FUTURE_NOT_AVAILABLE']==1
    assert 'Never display' not in json.dumps(r)


def test_future_ingestion_never_leaks():
    x=ob(id='unseen',ingested_at='2026-10-09T08:00:01+09:00')
    r=evaluate([x])
    assert r['observations']==[]


def test_bad_naive_timestamp_fails_closed():
    r=evaluate([ob(observed_at='2026-10-08T13:00:00')])
    assert r['quality']['invalid_rows']==1
    assert len(r['observations'])==0


def test_publication_earlier_than_observation_rejected():
    r=evaluate([ob(available_at='2026-10-08T13:00:00+09:00')])
    assert r['quality']['invalid_rows']==1


def test_missing_source_rejected_not_fictional():
    r=evaluate([ob(source_url='')])
    assert r['quality']['invalid_rows']==1


def test_malicious_source_scheme_fails():
    r=evaluate([ob(source_url='javascript:alert(1)')])
    assert len(r['observations'])==0


def test_original_claim_not_independently_verified():
    r=evaluate([ob(source_class='PRIMARY')])
    assert r['quality']['independently_verified_sources']==0
    assert r['observations'][0]['reliability']=='SOURCE_DECLARED_NOT_INDEPENDENTLY_CHECKED'


def test_source_conflict_not_averaged():
    a=ob(id='a',value='10')
    b=ob(id='b',value='20',source_url='https://example.invalid/other')
    r=evaluate([a,b])
    assert r['quality']['conflicts']==2
    assert {x['value'] for x in r['observations']}=={10.0,20.0}
    assert all(x['status']=='CONFLICT' for x in r['observations'])


def test_distinct_observation_sessions_do_not_conflict():
    a=ob(id='a',value='10',observed_at='2026-10-08T14:00:00+09:00')
    b=ob(id='b',value='20',observed_at='2026-10-08T14:01:00+09:00')
    assert evaluate([a,b])['quality']['conflicts']==0


def test_exact_duplicates_not_double_counted():
    r=evaluate([ob(),copy.deepcopy(ob())])
    assert r['quality']['visible_observations']==1
    assert r['quality']['excluded']['EXACT_DUPLICATE']==1


def test_same_id_different_values_quarantined():
    r=evaluate([ob(),ob(value='200')])
    assert r['quality']['conflicts']==2
    assert all(x['status']=='CONFLICT' for x in r['observations'])


def test_counterevidence_only_visible_if_available():
    a=ob(id='a',counter_ids='future|b')
    b=ob(id='b',fact='Contrary',metric='',value='',unit='',previous_value='',expected_value='')
    future=ob(id='future',fact='Not yet observed',available_at='2026-10-10T08:00:00+09:00',ingested_at='2026-10-10T08:00:01+09:00')
    r=evaluate([a,b,future])
    a_rec=next(x for x in r['observations'] if x['id']=='a')
    assert a_rec['counterevidence']==['b']
    assert 'COUNTEREVIDENCE_UNRESOLVED' in a_rec['issues']


def test_old_observation_marked_stale_not_current():
    r=evaluate([ob(category='LIQUIDITY')])
    assert r['observations'][0]['quality']=='STALE'
    assert r['quality']['current_nonconflicting']==0


def test_previous_deltas_distinguish_missing_not_retracted():
    earlier=evaluate([ob(id='a'),ob(id='b')])
    later=evaluate([ob(id='a'),ob(id='c')],prev=earlier)
    assert later['changes']['new']==['c']
    assert later['changes']['not_reobserved']==['b']
    assert later['changes']['unchanged']==['a']


def test_previous_revised_when_value_changes():
    earlier=evaluate([ob(id='a')])
    later=evaluate([ob(id='a',value='102')],prev=earlier)
    assert later['changes']['revised']==['a']


def test_calendar_future_not_future_known():
    event={'id':'cal','entity':'Made-up','event':'Announcement','event_at':'2026-10-12T09:00:00+09:00',
           'announced_at':'2026-10-08T10:00:00+09:00','ingested_at':'2026-10-08T10:01:00+09:00',
           'source_url':'https://example.invalid/cal','source_name':'synthetic',
           'certainty':'TENTATIVE','exposure':'example','expected_value':'','unit':''}
    r=evaluate([ob()],calendar=[event])
    assert r['quality']['calendar_visible']==1
    event['announced_at']='2026-10-10T10:00:00+09:00';event['ingested_at']='2026-10-10T10:01:00+09:00'
    r=evaluate([ob()],calendar=[event])
    assert r['quality']['calendar_visible']==0
    assert 'Announcement' not in json.dumps(r)


def test_event_past_not_shown_as_upcoming():
    event={'id':'cal','entity':'Made-up','event':'Already over','event_at':'2026-10-08T09:00:00+09:00',
           'announced_at':'2026-10-07T10:00:00+09:00','ingested_at':'2026-10-07T10:01:00+09:00',
           'source_url':'https://example.invalid/cal','source_name':'synthetic',
           'certainty':'CONFIRMED','exposure':'example','expected_value':'','unit':''}
    r=evaluate([ob()],calendar=[event])
    assert r['calendar']==[]


def test_empty_kpis_without_groundtruth():
    r=evaluate()
    assert evaluate_detection_kpis(r)['status']=='NOT_MEASURABLE'


def test_true_labelled_detection_math():
    r=evaluate()
    truth=[{'id':'a','label':'IMPORTANT','known_at':'2026-10-08T09:00:00+09:00'},
           {'id':'b','label':'IMPORTANT','known_at':'2026-10-08T09:00:00+09:00'},
           {'id':'c','label':'NOT_IMPORTANT','known_at':'2026-10-08T09:00:00+09:00'}]
    alerts=[{'id':'a','emitted_at':'2026-10-08T09:05:00+09:00'},
            {'id':'c','emitted_at':'2026-10-08T09:08:00+09:00'}]
    k=evaluate_detection_kpis(r,truth,alerts)
    assert k['precision']==.5 and k['recall']==.5 and k['median_delay_minutes']==5


def test_unlabelled_alert_not_counted_false_positive():
    k=evaluate_detection_kpis(evaluate(),[{'id':'a','label':'IMPORTANT','known_at':'2026-10-08T09:00:00+09:00'}],
                              [{'id':'unlabelled','emitted_at':'2026-10-08T09:01:00+09:00'}])
    assert k['status']=='NOT_MEASURABLE'


def test_negative_detection_latency_invalid():
    k=evaluate_detection_kpis(evaluate(),[{'id':'a','label':'IMPORTANT','known_at':'2026-10-08T09:05:00+09:00'}],
                              [{'id':'a','emitted_at':'2026-10-08T09:01:00+09:00'}])
    assert k['status']=='NOT_MEASURABLE'


def test_renderer_html_escapes_user_input():
    r=evaluate([ob(fact='<script>alert(123)</script>',entity='" onmouseenter="fail')])
    page=render_html(r)
    assert '<script>alert(123)</script>' not in page
    assert '&lt;script&gt;alert(123)&lt;/script&gt;' in page


def test_report_creation(tmp_path):
    r=evaluate()
    paths=write_intelligence(r,tmp_path)
    assert Path(paths['html']).is_file()
    assert Path(paths['csv']).is_file()
    assert Path(paths['json']).is_file()
    assert '전략 중립' in Path(paths['markdown']).read_text(encoding='utf-8')


def test_synthetic_demo_writes_schema(tmp_path):
    p=synthetic_intel(tmp_path)
    rows=read_csv(p/'observations.csv',OBS_COLUMNS)
    assert len(rows)==7
    r=evaluate(rows)
    assert r['quality']['conflicts']==2


def test_no_source_zero_in_reporting():
    r=evaluate([ob(value='',previous_value='',expected_value='',metric='',unit='')])
    assert '미확인' in render_markdown(r) or '반대 증거' in render_markdown(r)


def test_missing_prior_provenance_never_computes_delta():
    x=evaluate([ob(previous_observed_at='',previous_source_url='')])['observations'][0]
    assert x['delta'] is None
    assert 'PREVIOUS_BASELINE_PROVENANCE_UNVERIFIED' in x['issues']


def test_post_event_consensus_never_computes_surprise():
    x=evaluate([ob(expected_asof='2026-10-08T14:05:00+09:00')])['observations'][0]
    assert x['surprise'] is None
    assert 'EXPECTATION_PROVENANCE_UNVERIFIED_OR_POST_EVENT' in x['issues']


def test_previous_from_future_report_rejected():
    r=evaluate([ob()],asof='2026-10-09T08:00:00+09:00')
    r['asof']='2026-10-10T08:00:00+09:00'
    with pytest.raises(IntelDataError):
        evaluate([ob()],prev=r)
