"""Strategy-agnostic market intelligence layer: point-in-time facts, not trading signals.

No scores, price targets, or orders. All provenance is sourced from user-supplied
records and is NOT independently authenticated by importing a CSV.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .settings import parse_asof, KST

OBS_COLUMNS = [
    'id','entity','category','metric','fact','value','unit','previous_value','previous_observed_at','previous_source_url',
    'expected_value','expected_asof','expected_source_url','observed_at','available_at','ingested_at','source_url','source_name','source_class',
    'venue','severity','potential_impact','counter_ids','followup_at',
]
CAL_COLUMNS = [
    'id','entity','event','event_at','announced_at','ingested_at','source_url','source_name',
    'certainty','exposure','expected_value','unit',
]
CATEGORIES = {'SURPRISE','ABNORMAL','LIQUIDITY','RISK','FLOWS','MARKET','CORPORATE','DATA_QUALITY'}
SOURCE_CLASSES = {'PRIMARY','SECONDARY','PROXY','USER_SUPPLIED'}
SEVERITIES = {'HIGH','MEDIUM','LOW'}
# How long after release an *observation* is treated as current; old facts remain visible as stale.
# This is an operational display policy, not a statistical parameter.
REFRESH_HOURS = {'LIQUIDITY': 2, 'FLOWS': 48, 'MARKET': 48, 'ABNORMAL': 48,
                 'SURPRISE': 168, 'RISK': 336, 'CORPORATE': 336, 'DATA_QUALITY': 48}

class IntelDataError(ValueError):
    pass


def read_csv(path: str | Path, fields: list[str], *, optional: bool = False) -> list[dict]:
    p = Path(path)
    if not p.exists() and optional:
        return []
    if not p.is_file():
        raise IntelDataError(f'Missing input: {p}')
    with p.open(encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        missing = [f for f in fields if f not in (reader.fieldnames or [])]
        if missing:
            raise IntelDataError(f'{p.name}: missing fields {missing}')
        return list(reader)


def _ts(value, field):
    if value is None or not str(value).strip():
        raise IntelDataError(f'Missing timestamp {field}')
    try:
        d = datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
    except ValueError as exc:
        raise IntelDataError(f'Invalid timestamp {field}: {value}') from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise IntelDataError(f'Timestamp {field} must include timezone: {value}')
    return d.astimezone(KST)


def _num(s):
    if s is None or str(s).strip() == '':
        return None
    try:
        n = float(s)
    except (TypeError, ValueError) as exc:
        raise IntelDataError(f'Invalid numeric value {s!r}') from exc
    if not math.isfinite(n):
        raise IntelDataError(f'Non-finite numeric value {s!r}')
    return n


def _url(value):
    try:
        u = urlparse(str(value).strip())
        return u.scheme == 'https' and bool(u.netloc) and not u.username and not u.password
    except ValueError:
        return False


def _process_observation(raw, now):
    code = str(raw.get('id','')).strip()
    if not code:
        raise IntelDataError('Observation ID is required')
    available = _ts(raw.get('available_at'), 'available_at')
    ingested = _ts(raw.get('ingested_at'), 'ingested_at')
    observed = _ts(raw.get('observed_at'), 'observed_at')
    # Do not leak future *data*. The counter, not the record text, carries deferred rows.
    if max(available, ingested, observed) > now:
        return None, 'FUTURE_NOT_AVAILABLE'
    category = str(raw.get('category','')).strip().upper()
    severity = str(raw.get('severity','')).strip().upper()
    source_class = str(raw.get('source_class','')).strip().upper()
    if category not in CATEGORIES:
        raise IntelDataError(f'{code}: unknown category {category}')
    if severity not in SEVERITIES or source_class not in SOURCE_CLASSES:
        raise IntelDataError(f'{code}: invalid severity or source class')
    if available < observed:
        raise IntelDataError(f'{code}: publication before observation')
    if ingested < available:
        raise IntelDataError(f'{code}: ingestion before source availability')
    if not _url(raw.get('source_url','')):
        raise IntelDataError(f'{code}: missing/invalid HTTPS source URL')
    if not all(str(raw.get(c,'')).strip() for c in ('entity','fact','source_name')):
        raise IntelDataError(f'{code}: empty entity, fact or source name')
    unit = str(raw.get('unit','')).strip()
    metric = str(raw.get('metric','')).strip()
    value = _num(raw.get('value'))
    previous = _num(raw.get('previous_value'))
    expected = _num(raw.get('expected_value'))
    if any(x is not None for x in (value, previous, expected)) and not unit:
        raise IntelDataError(f'{code}: unit required for numbers')
    if any(x is not None for x in (value, previous, expected)) and not metric:
        raise IntelDataError(f'{code}: metric required for numbers')
    if value is None and (previous is not None or expected is not None):
        raise IntelDataError(f'{code}: baseline/expectation without observation')
    provenance_issues=[]
    # A prior value or consensus supplied without verifiable pre-event temporal context
    # is not a measurable change/surprise. Do not treat it as zero or a valid delta.
    prev_at=raw.get('previous_observed_at','')
    prev_url=raw.get('previous_source_url','')
    if previous is not None:
        try:
            if (not _url(prev_url)) or _ts(prev_at,'previous_observed_at') >= observed or _ts(prev_at,'previous_observed_at') > now:
                raise IntelDataError('Prior value timestamp/source missing, late or not prior')
        except IntelDataError:
            previous=None
            provenance_issues.append('PREVIOUS_BASELINE_PROVENANCE_UNVERIFIED')
    expect_at=raw.get('expected_asof','')
    expect_url=raw.get('expected_source_url','')
    if expected is not None:
        try:
            if (not _url(expect_url)) or _ts(expect_at,'expected_asof') >= observed or _ts(expect_at,'expected_asof') > now:
                raise IntelDataError('Expectation was not sourced strictly before event')
        except IntelDataError:
            expected=None
            provenance_issues.append('EXPECTATION_PROVENANCE_UNVERIFIED_OR_POST_EVENT')
    # Negative prices/volumes are invalid; negative returns, net flows, interest rates are valid.
    if (metric.lower() in {'price','close','volume','turnover_krw','bid','ask','spread_bps'}
            and value is not None and value < 0):
        raise IntelDataError(f'{code}: negative non-negative metric')
    diff = value - previous if previous is not None else None
    surprise = value - expected if expected is not None else None
    rec = {
        'id':code, 'entity':str(raw['entity']).strip(), 'category':category, 'metric':metric,
        'fact':str(raw['fact']).strip(), 'value':value, 'unit':unit, 'previous_value':previous,
        'previous_observed_at':str(prev_at).strip() if previous is not None else None,
        'previous_source_url':str(prev_url).strip() if previous is not None else None,
        'expected_value':expected, 'expected_asof':str(expect_at).strip() if expected is not None else None,
        'expected_source_url':str(expect_url).strip() if expected is not None else None,
        'delta':diff, 'surprise':surprise,
        'delta_pct':100*diff/abs(previous) if diff is not None and previous != 0 else None,
        'surprise_pct':100*surprise/abs(expected) if surprise is not None and expected != 0 else None,
        'observed_at':observed.isoformat(), 'available_at':available.isoformat(),
        'ingested_at':ingested.isoformat(), 'source_url':str(raw['source_url']).strip(),
        'source_name':str(raw['source_name']).strip(), 'source_class':source_class,
        'venue':str(raw.get('venue','')).strip().upper(), 'severity':severity,
        'potential_impact':str(raw.get('potential_impact','')).strip(),
        'counter_ids':[x.strip() for x in str(raw.get('counter_ids','')).split('|') if x.strip()],
        'followup_at':str(raw.get('followup_at','')).strip(),
        'sampled':False, 'quality':'CURRENT', 'reliability':'SOURCE_DECLARED_NOT_INDEPENDENTLY_CHECKED',
        'status':'OBSERVED', 'issues':list(provenance_issues),
    }
    age_h=(now - available).total_seconds()/3600
    if age_h > REFRESH_HOURS[category]:
        rec['quality']='STALE'
        rec['issues'].append('OLDER_THAN_CATEGORY_REFRESH_WINDOW')
    if source_class in {'PROXY','USER_SUPPLIED'}:
        rec['issues'].append('PROXY_OR_USER_SUPPLIED')
    if not rec['counter_ids']:
        rec['issues'].append('COUNTEREVIDENCE_NOT_PROVIDED')
    if rec['followup_at']:
        check_at=_ts(rec['followup_at'], 'followup_at')
        rec['followup_at']=check_at.isoformat()
    return rec, None


def _process_calendar(raw, now):
    eid=str(raw.get('id','')).strip()
    if not eid:
        raise IntelDataError('Calendar event ID missing')
    announced=_ts(raw.get('announced_at'), 'announced_at')
    ingested=_ts(raw.get('ingested_at'), 'ingested_at')
    if max(announced,ingested)>now:
        return None, 'FUTURE_NOT_AVAILABLE'
    if ingested<announced:
        raise IntelDataError(f'{eid}: calendar ingested before announced')
    event_at=_ts(raw.get('event_at'),'event_at')
    if not _url(raw.get('source_url','')):
        raise IntelDataError(f'{eid}: invalid source URL')
    if not all(str(raw.get(k,'')).strip() for k in ('entity','event','source_name')):
        raise IntelDataError(f'{eid}: missing calendar required string')
    # Events passed more than one day ago no longer belong in an upcoming calendar.
    if event_at < now:
        return None, 'PAST_EVENT'
    if event_at > now+timedelta(days=30):
        return None, 'BEYOND_30D_WINDOW'
    certainty=str(raw.get('certainty','')).upper()
    if certainty not in {'CONFIRMED','TENTATIVE'}:
        raise IntelDataError(f'{eid}: invalid calendar certainty')
    return {
        'id':eid,'entity':str(raw['entity']).strip(),'event':str(raw['event']).strip(),
        'event_at':event_at.isoformat(),'announced_at':announced.isoformat(),
        'ingested_at':ingested.isoformat(), 'source_url':str(raw['source_url']).strip(),
        'source_name':str(raw['source_name']).strip(), 'certainty':certainty,
        'exposure':str(raw.get('exposure','')).strip(),
        'expected_value':str(raw.get('expected_value','')).strip(),
        'unit':str(raw.get('unit','')).strip(),
        'source_verified':False,
    }, None


def _signature(rec):
    return json.dumps({k:rec.get(k) for k in (
        'entity','category','metric','value','unit','previous_value','previous_observed_at',
        'previous_source_url','expected_value','expected_asof','expected_source_url',
        'fact','source_url','source_class','source_name','venue','observed_at','available_at',
        'severity','potential_impact','counter_ids','status','quality')}, ensure_ascii=False, sort_keys=True)


def evaluate_intelligence(observations: list[dict], calendar: list[dict], asof,
                          *, previous: dict | None=None, sample: bool=False) -> dict:
    now=parse_asof(asof)
    eligible=[]; excludes=Counter(); invalid=[]
    for raw in observations:
        try:
            rec, reason=_process_observation(raw,now)
            if reason:
                excludes[reason]+=1
            else:
                rec['sampled']=sample
                eligible.append(rec)
        except (IntelDataError,KeyError) as e:
            invalid.append({'id':str(raw.get('id','UNIDENTIFIED')),'issue':str(e)})
    # conflicting repeated IDs are quarantined, not silently overwritten.
    id_groups=defaultdict(list)
    for rec in eligible:
        id_groups[rec['id']].append(rec)
    unique=[]
    for rec_id, arr in id_groups.items():
        signatures={_signature(r) for r in arr}
        if len(signatures)>1:
            for r in arr:
                r['status']='CONFLICT'
                r['issues'].append('DUPLICATE_ID_DIFFERENT_CONTENT')
            unique.extend(arr)
        else:
            unique.append(arr[0])
            excludes['EXACT_DUPLICATE'] += len(arr)-1
    # Detect source disagreements at exactly comparable grain; never average.
    grains=defaultdict(list)
    for r in unique:
        if r['metric']:
            grains[(r['entity'],r['metric'],r['unit'],r['observed_at'],r['venue'])].append(r)
    for items in grains.values():
        if len(items)>1 and (len({r['value'] for r in items})>1):
            for r in items:
                r['status']='CONFLICT'
                if 'SOURCE_VALUE_DISAGREEMENT' not in r['issues']:
                    r['issues'].append('SOURCE_VALUE_DISAGREEMENT')
    valid_ids={r['id'] for r in unique if r['status']!='CONFLICT'}
    counter_index={r['id']:r for r in unique if r['status']!='CONFLICT'}
    for rec in unique:
        rec['counterevidence']=[x for x in rec['counter_ids'] if x in valid_ids]
        rec['counterevidence_details']=[{'id':key, 'fact':counter_index[key]['fact'],
                                        'source_url':counter_index[key]['source_url'],
                                        'available_at':counter_index[key]['available_at']}
                                       for key in rec['counterevidence']]
        if len(rec['counterevidence']) != len(rec['counter_ids']):
            rec['issues'].append('COUNTEREVIDENCE_UNRESOLVED')
    upcoming=[]
    for raw in calendar:
        try:
            rec,reason=_process_calendar(raw,now)
            if reason:excludes['CALENDAR_'+reason]+=1
            else:upcoming.append(rec)
        except (IntelDataError,KeyError) as e:
            invalid.append({'id':str(raw.get('id','CAL_UNKNOWN')),'issue':str(e)})
    # Identical calendar events count once; conflicting duplicate IDs remain visible
    # with explicitly uncertain status, never silently prefer the latest row.
    cal_by_id=defaultdict(list)
    for e in upcoming:cal_by_id[e['id']].append(e)
    calendar_unique=[]
    for eid, items in cal_by_id.items():
        distinct={json.dumps(x,sort_keys=True,ensure_ascii=False) for x in items}
        if len(distinct)>1:
            for event in items:event['certainty']='CONFLICT'
            calendar_unique.extend(items)
        else:
            calendar_unique.append(items[0]);excludes['CALENDAR_EXACT_DUPLICATE']+=len(items)-1
    upcoming=calendar_unique
    # No fake urgency numbers or strategy-weighted total scores.
    priority={'HIGH':0,'MEDIUM':1,'LOW':2}
    unique.sort(key=lambda r:(priority[r['severity']],r['status']=='CONFLICT',
                              r['quality']=='STALE',r['available_at'],r['id']), reverse=False)
    upcoming.sort(key=lambda r:r['event_at'])
    if previous is not None and _ts(previous.get('asof'), 'previous.asof') > now:
        raise IntelDataError('previous report asof cannot be later than requested snapshot')
    prev_by_id={r['id']:_signature(r) for r in (previous or {}).get('observations',[])
                if isinstance(r,dict) and 'id' in r and r.get('status')!='CONFLICT'}
    curr_by_id={r['id']:_signature(r) for r in unique if r['status']!='CONFLICT'}
    changed={'new':[], 'revised':[], 'unchanged':[], 'not_reobserved':[]}
    for item_id,sig in curr_by_id.items():
        key='new' if item_id not in prev_by_id else ('unchanged' if sig==prev_by_id[item_id] else 'revised')
        changed[key].append(item_id)
    changed['not_reobserved']=[x for x in prev_by_id if x not in curr_by_id]
    clean=[x for x in unique if x['status']=='OBSERVED' and x['quality']=='CURRENT']
    cats=Counter(x['category'] for x in unique)
    status_counts=Counter(x['status'] for x in unique)
    qa={'input_observations':len(observations),'visible_observations':len(unique),
        'current_nonconflicting':len(clean),'conflicts':status_counts['CONFLICT'],
        'stale':sum(x['quality']=='STALE' for x in unique),
        'invalid_rows':len(invalid),'excluded':dict(excludes),
        'coverage_fraction':len(clean)/len(observations) if observations else None,
        'coverage_denominator_note':'SCOPE=SUPPLIED_ROWS_NOT_FULL_KOREAN_MARKET',
        'independently_verified_sources':0,
        'source_verification_status':'SOURCE_DECLARED_NOT_CHECKED_BY_SOFTWARE',
        'calendar_visible':len(upcoming)}
    return {'schema_version':'2.0','mode':'MARKET_INTELLIGENCE_STRATEGY_AGNOSTIC',
            'asof':now.isoformat(),'previous_provided':previous is not None,'sample':sample,'observations':unique,'calendar':upcoming,
            'changes':changed,'category_counts':dict(cats),'quality':qa,'invalid_records':invalid,
            'limitations':['Declared source URLs are not independent validation of the content',
                           'Only supplied observation universe, NOT the entire Korean equity market',
                           'Observational correlation is not causation or a trade signal',
                           'Economic impact and actual strategy PnL remain unmeasured without outcomes',
                           'A date-only DART publication must never be treated as an exact morning timestamp',
                           'KRX and NXT venue scope must never be silently combined']}


def evaluate_detection_kpis(report: dict, ground_truth: list[dict] | None=None,
                            alerts: list[dict] | None=None) -> dict:
    """Only evaluate against a manually labelled COMPLETE scoped ground-truth set.
    Never interpret missing examples as false negatives or true negatives.
    """
    if not ground_truth or alerts is None:
        return {'status':'NOT_MEASURABLE','reason':'Ground truth and timestamped alert ledger both required',
                'recall':None,'precision':None,'median_delay_minutes':None}
    # This is a retrospective benchmark, not an alpha or live fill metric.
    gt={str(row.get('id','')).strip():row for row in ground_truth if str(row.get('id','')).strip()}
    marked={a['id'] for a in alerts if str(a.get('id','')).strip()}
    if not gt or any(row.get('label') not in {'IMPORTANT','NOT_IMPORTANT'} for row in gt.values()):
        return {'status':'NOT_MEASURABLE','reason':'All scoped ground truth IDs need IMPORTANT/NOT_IMPORTANT labels'}
    if any(a not in gt for a in marked):
        return {'status':'NOT_MEASURABLE','reason':'Unlabelled alerts in evaluated scope; do not assume false positives'}
    gt_pos={x for x,row in gt.items() if row['label']=='IMPORTANT'}
    tp=gt_pos & marked
    prec=len(tp)/len(marked) if marked else None
    recall=len(tp)/len(gt_pos) if gt_pos else None
    delays=[]
    earliest={ }
    for a in alerts:
        key=str(a.get('id',''))
        if key in tp:
            try:
                stamp=_ts(a['emitted_at'],'emitted_at')
            except (IntelDataError,KeyError):
                return {'status':'NOT_MEASURABLE','reason':'Missing or invalid emitted_at'}
            if key not in earliest or stamp<earliest[key]:earliest[key]=stamp
    for key, sent in earliest.items():
        label=gt[key]
        try:
            avail=_ts(label['known_at'],'known_at')
        except (IntelDataError, KeyError):
            return {'status':'NOT_MEASURABLE','reason':'Missing/invalid alert or true-event timestamps'}
        delay=(sent-avail).total_seconds()/60
        if delay<0:
            return {'status':'NOT_MEASURABLE','reason':'Alert timestamp predates reference event availability'}
        delays.append(delay)
    return {'status':'DESCRIPTIVE_ONLY','scope_size':len(gt),'important_count':len(gt_pos),
            'alert_count':len(marked),'true_positive_count':len(tp),
            'recall':recall,'precision':prec,
            'median_delay_minutes':statistics.median(delays) if delays else None,
            'limits':'No strategy/PnL causal inference; ground_truth must be complete for the declared scope.'}


def detect_synthetic(observations, calendar):
    """Never present explicitly fictional/demo provenance as production intelligence."""
    for row in list(observations) + list(calendar):
        name = str(row.get('source_name', '')).upper()
        doc = str(row.get('source_url', '')).strip().lower()
        rid = str(row.get('id', '')).upper()
        if 'SYNTHETIC' in name or 'SYNTHETIC' in str(row.get('source', '')).upper():
            return True
        if urlparse(doc).hostname == 'example.invalid' or rid.startswith('FAKE-'):
            return True
    return False


def read_intel_folder(folder):
    p=Path(folder)
    return (read_csv(p/'observations.csv', OBS_COLUMNS),
            read_csv(p/'calendar.csv',CAL_COLUMNS,optional=True))
