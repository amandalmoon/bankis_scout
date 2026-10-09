from datetime import datetime
from pathlib import Path
import csv
import json
import subprocess
import sys

import pytest
from bankis_scout.demo import create_demo
from bankis_scout.intel_adapter import describe_daily_bundle
from bankis_scout.intel_disclosures import disclosure_to_observations,save_observations_csv
from bankis_scout.intelligence import evaluate_intelligence, IntelDataError, OBS_COLUMNS

ASOF='2026-10-09T08:00:00+09:00'
PUB='2026-10-08T18:00:00+09:00'
IN='2026-10-08T18:10:00+09:00'
URL='https://apiportal.koreainvestment.com/apiservice-category'

@pytest.fixture
def bundle(tmp_path):
    create_demo(tmp_path)
    # Neutral layer does NOT need contest eligibility (not an attribute of a fact).
    (tmp_path/'eligibility.csv').unlink()
    return tmp_path


def test_adapter_without_trade_eligibility(bundle):
    obs,excluded=describe_daily_bundle(bundle,ASOF,source_url=URL,available_at=PUB,ingested_at=IN)
    assert obs
    assert all(x['source_class']=='USER_SUPPLIED' for x in obs)
    assert all('buy' not in x['fact'].lower() for x in obs)


def test_adapter_leaks_no_same_day_after_eod(bundle):
    obs,_=describe_daily_bundle(bundle,ASOF,source_url=URL,available_at=PUB,ingested_at=IN)
    assert all(x['observed_at'].startswith(('2026-10-08','2026-10-07')) for x in obs)


def test_adapter_rejects_future_source_availability(bundle):
    with pytest.raises(IntelDataError):
        describe_daily_bundle(bundle,ASOF,source_url=URL,
            available_at='2026-10-09T08:01:00+09:00',ingested_at='2026-10-09T08:02:00+09:00')


def test_adapter_requires_https_source(bundle):
    with pytest.raises(IntelDataError):
        describe_daily_bundle(bundle,ASOF,source_url='http://unsecure.test',available_at=PUB,ingested_at=IN)


def test_disclosures_preserve_conservative_date_gate(tmp_path):
    path=tmp_path/'disclosures.csv'
    path.write_text('code,published_at,event_type,title,source_url\n'
                    '000001,2026-10-08T23:59:59+09:00,risk,전환사채 발행,https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1111\n'
                    '000002,2026-10-09T23:59:59+09:00,contract,단일판매 공급 계약,https://dart.fss.or.kr/dsaf001/main.do?rcpNo=2222\n',encoding='utf-8')
    obs=disclosure_to_observations(path,ingested_at='2026-10-09T07:00:00+09:00')
    assert len(obs)==1
    assert obs[0]['category']=='RISK'
    assert '영향' in obs[0]['fact']
    assert obs[0]['value']==''


def test_import_to_live_report_without_declaring_verified(bundle,tmp_path):
    obs,_=describe_daily_bundle(bundle,ASOF,source_url=URL,available_at=PUB,ingested_at=IN)
    report=evaluate_intelligence(obs,[],ASOF)
    assert report['quality']['independently_verified_sources']==0
    assert report['quality']['current_nonconflicting']>=1
    assert report['mode']=='MARKET_INTELLIGENCE_STRATEGY_AGNOSTIC'


def test_cli_pipeline_no_network(bundle,tmp_path):
    out=tmp_path/'report'
    result=subprocess.run([sys.executable,'-m','bankis_scout','intel-pipeline',
        '--data-dir',str(bundle),'--source-url',URL,'--available-at',PUB,
        '--ingested-at',IN,'--asof',ASOF,'--output',str(out)],
        capture_output=True,text=True)
    assert result.returncode==0, result.stderr
    assert (out/'intelligence.json').is_file()
    assert (out/'collected_observations.csv').is_file()
    assert json.loads((out/'intelligence.json').read_text(encoding='utf-8'))['quality']['visible_observations']>=1


def test_documentation_unchanged_old_layer(bundle):
    # Critical regression: neutral reporting never changes existing momentum engine.
    from bankis_scout.engine import screen_bundle
    from bankis_scout.data import load_bundle
    # old layer intentionally depends on this independent eligibility manifest
    with pytest.raises(Exception):
        screen_bundle(load_bundle(bundle),ASOF)


def test_demo_market_data_cannot_be_published_as_non_sample(bundle,tmp_path):
    out=tmp_path/'synthetic_report'
    result=subprocess.run([sys.executable,'-m','bankis_scout','intel-pipeline',
        '--data-dir',str(bundle),'--source-url',URL,'--available-at',PUB,
        '--ingested-at',IN,'--asof',ASOF,'--output',str(out)],
        capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads((out/'intelligence.json').read_text(encoding='utf-8'))['sample'] is True
    assert 'SYNTHETIC' in (out/'intelligence.html').read_text(encoding='utf-8')


def test_intel_command_import_of_synthetic_facts_is_marked_sample(tmp_path):
    from bankis_scout.intel_demo import synthetic_intel
    folder=synthetic_intel(tmp_path/'fake_input')
    out=tmp_path/'report'
    result=subprocess.run([sys.executable,'-m','bankis_scout','intel',
        '--data-dir',str(folder),'--asof',ASOF,'--output',str(out)],
        capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads((out/'intelligence.json').read_text(encoding='utf-8'))['sample'] is True
