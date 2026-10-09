"""Evidence-first, strategy-neutral reporting. Never renders guessed or absent prices."""
from __future__ import annotations
import csv
import html
import json
from collections import Counter
from pathlib import Path


def E(x):
    return html.escape(str(x if x is not None else '미확인'),quote=True)

CAT_KO={'SURPRISE':'예상 대비 충격','ABNORMAL':'비정상 움직임','LIQUIDITY':'거래·유동성',
        'RISK':'위험·거래제한','FLOWS':'수급 변화','MARKET':'시장 환경','CORPORATE':'기업 이벤트',
        'DATA_QUALITY':'데이터 품질'}

def fmt(x,unit=''):
    if x is None:return '미확인'
    if not isinstance(x,(float,int)):return E(x)
    s=f'{x:+,.2f}' if x<0 else f'{x:,.2f}'
    return E(s+' '+unit)


def render_markdown(res, kpis=None):
    q=res['quality']; sample=res['sample']; lines=[
        '# 장전 Market Intelligence | 전략 중립',
        f"- 기준: {res['asof']} (KST). 구분: {'합성 데이터 시연' if sample else '제공된 입력 기반, 원문 자동 인증 전'}",
        '- 정보 품질: '+f"관측 {q['visible_observations']}/{q['input_observations']}, "
        +f"현재·비충돌 {q['current_nonconflicting']}, 충돌 {q['conflicts']}, "
        +f"지연 {q['stale']}, 형식 오류 {q['invalid_rows']}. 전체 한국시장 커버리지 아님.",
        '- 해석: 사실·추정·불확실성을 구분. 특정 전략, 매수 추천, 실전 수익률 추정 없음.',
        '', '## 가장 중요한 관측 변화'
    ]
    if res.get('previous_provided'):
        ch=res['changes']
        lines.append(f"비교: 신규 {len(ch['new'])}, 수정 {len(ch['revised'])}, 현재 미관측 {len(ch['not_reobserved'])}. 미관측=철회 아님.")
    else:lines.append('이전 보고서가 없어 새로 등장한 항목의 식별은 불가합니다.')
    display=res['observations'][:12]
    if not display:lines.append('- 기준 시각에 사용할 수 있는 검증 가능한 관측값 없음')
    for x in display:
        delta=('; 이전값 대비 '+fmt(x['delta'],x['unit'])) if x['delta'] is not None else ''
        surprise=('; 예상 대비 '+fmt(x['surprise'],x['unit'])) if x['surprise'] is not None else ''
        lines.append(f"- [{x['severity']}/{x['quality']}/{x['status']}] **{x['entity']}** "
                     f"({CAT_KO[x['category']]}): {x['fact']}{delta}{surprise}. "
                     f"관측 {x['observed_at']}, 공개 {x['available_at']}, "
                     f"출처 {x['source_name']}: {x['source_url']}")
        lines.append(f"  - 가능 영향(가설): {x['potential_impact'] or '검증 전 / 특정 방향 주장 없음'}")
        lines.append(f"  - 반대 증거: {', '.join(x['counterevidence']) if x['counterevidence'] else '연결된 반대 증거 없음'} "
                     f"/ 정보 제약: {', '.join(x['issues']) if x['issues'] else '추가 없음'}")
    lines+=['','## 예정된 이벤트']
    if not res['calendar']:lines.append('- 기준 시각에 확인된 향후 30일 공식 일정 없음 (미수집 가능성 포함)')
    for e in res['calendar'][:12]:
        lines.append(f"- {e['event_at']} | {e['entity']} | {e['event']} "
                     f"({e['certainty']}) — {e['source_url']}")
    lines+=['','## 미확인 / 결함 / 데이터 범위']
    for item in res['invalid_records'][:12]:
        lines.append(f"- 데이터 오류 ID {item['id']}: {item['issue']}")
    for why,n in q['excluded'].items():lines.append(f'- 제외 {why}: {n}건')
    lines+=['- 출처 링크·등급은 원문 확인을 대신하지 않습니다. 콘텐츠 독립 검증 0건(수집 파일 자체만 평가).',
            '- 장중 VWAP·ORB는 정규장 시작 전 확인 불가. KRX/NXT 집계 범위를 합치지 않음.',
            '', '## 측정 KPI']
    if not kpis or kpis['status']=='NOT_MEASURABLE':
        lines.append('- 탐지율·정확도·지연: 측정 불가. 완전한 정답지(ground truth)와 경보시각 로그 필요.')
    else:
        lines.append(f"- 범위 {kpis['scope_size']}건, 중요 {kpis['important_count']}건, "
                     f"재현율 {kpis['recall']}, 정밀도 {kpis['precision']}, "
                     f"중위 탐지지연 {kpis['median_delay_minutes']}분. 투자수익률 효과 아님.")
    lines+=['','## 한계','- '+'\n- '.join(res['limitations'])]
    return '\n'.join(lines)+'\n'


def render_html(res, kpis=None, bankis_link=None):
    q=res['quality']; sample=res['sample']
    status_note='합성 데이터로 제작한 기능 시연입니다. 실제 시세, 공시 및 추천 정보가 아닙니다.' if sample else '사용자 제공 데이터 기반입니다. 링크는 자동 독립 인증을 의미하지 않습니다.'
    pill=lambda t,css='':f'<span class="pill {css}">{E(t)}</span>'
    obs=[]
    display=res['observations']
    for x in display:
        status=' '.join([x['status'],x['quality']])
        if x['status']=='CONFLICT':status+=' SOURCE CONFLICT'
        val=fmt(x['value'],x['unit']) if x['value'] is not None else '사실 서술'
        delta=fmt(x['delta'],x['unit']) if x['delta'] is not None else '비교 기준 없음'
        surprise=fmt(x['surprise'],x['unit']) if x['surprise'] is not None else '시장 예상치 미확보'
        contrary=x.get('counterevidence_details',[])
        opposing=('; '.join(f'<a href="{E(z["source_url"])}" target="_blank" rel="noopener noreferrer">{E(z["id"])}</a> '
                            f'({E(z["fact"])})' for z in contrary) if contrary else
                  '연결된 반대 관측 근거 없음 (반대 가능성이 없다는 뜻은 아님)')
        src=f'<a href="{E(x["source_url"])}" rel="noopener noreferrer" target="_blank">{E(x["source_name"])} ↗</a>'
        prior_src=(f'<a href="{E(x["previous_source_url"])}" target="_blank" rel="noopener noreferrer">이전값 근거 ↗</a>'
                   if x.get('previous_source_url') else '이전값 출처 미확인')
        expect_src=(f'<a href="{E(x["expected_source_url"])}" target="_blank" rel="noopener noreferrer">예상치 근거 ↗</a>'
                    if x.get('expected_source_url') else '사전 예상치 근거 미확인')
        details=f'''<div class="detail-grid"><div><div class="eyebrow">측정 및 비교</div><p>관측값: <b>{val}</b><br>직전 관측 대비: {delta}<br>예상 대비 차이: {surprise}<br>거래소·세션: {E(x['venue'] or '미확인')}<br>{prior_src} · {expect_src}</p>
<div class="eyebrow">잠재 영향 (해석 가설)</div><p>{E(x['potential_impact'] or '검증된 방향성 해석 없음')}</p></div>
<div><div class="eyebrow">반대 증거 · 검증 필요</div><p>{opposing}</p><div class="eyebrow">데이터 계보 · 제한</div><p>관측: {E(x['observed_at'])}<br>공개: {E(x['available_at'])}<br>수집: {E(x['ingested_at'])}<br>출처 유형: {E(x['source_class'])}<br>{src}</p><p class="dim">{E(', '.join(x['issues']) or '추가 경고 없음')}</p></div></div>'''
        obs.append(f'''<article class="observation" data-filter="{E(x['category'])}" data-severity="{E(x['severity'])}" data-search="{E(x['entity']+' '+x['fact']+' '+x['metric'])}">
<div class="obs-row"><div class="obs-main"><div class="badges">{pill(x['severity'],'sev-'+x['severity'].lower())}{pill(CAT_KO[x['category']])}{pill(status,'warning' if x['status']=='CONFLICT' else '')}</div>
<div class="obs-title">{E(x['entity'])} <span class="dim">{E(x['metric'])}</span></div><p>{E(x['fact'])}</p><div class="obs-meta">관측 {E(x['observed_at'][:16])} · 공개 {E(x['available_at'][:16])} · {src}</div></div>
<details><summary>근거 및 반론 확인</summary>{details}</details></div></article>''')
    if not obs:obs=['<div class="empty">사용 가능한 검증 시점의 관측이 없습니다. 종목이나 가격을 생성하지 않습니다.</div>']
    future=''.join(f'<tr><td>{E(x["event_at"][:16])}</td><td>{E(x["entity"])}</td><td>{E(x["event"])}</td><td>{pill(x["certainty"])}</td><td><a href="{E(x["source_url"])}" target="_blank" rel="noopener noreferrer">공식 출처 ↗</a></td></tr>' for x in res['calendar'])
    if not future:future='<tr><td colspan="5" class="empty">확인된 향후 이벤트 없음 (미수집 가능)</td></tr>'
    quality_list=''.join(f'<li><strong>{E(x["id"])}</strong> : {E(x["issue"])}</li>' for x in res['invalid_records'][:15])
    quality_list+= ''.join(f'<li>{E(k)} : {v}건 제외</li>' for k,v in q['excluded'].items())
    if not quality_list:quality_list='<li>입력 검증 오류 기록 없음. 원문 독립 확인을 의미하지 않음.</li>'
    if res.get('previous_provided'):
        ch=res['changes']; changehtml=(f'<strong>새 관측 {len(ch["new"])} · 변경 {len(ch["revised"])} · 이전에는 있었으나 현재 미관측 {len(ch["not_reobserved"])}</strong>'
                                    '<div class="tiny">현재 미관측은 철회 또는 종료와 다릅니다.</div>')
    else:changehtml='<strong>이전 보고서 없음</strong><div class="tiny">첫 실행 시 변화 판정 불가</div>'
    kpitxt=('측정 전: 정답지 및 경보 기록 필요' if not kpis or kpis['status']=='NOT_MEASURABLE' else
            f"정밀도 {kpis['precision']}, 탐지율 {kpis['recall']}, 중위 지연 {kpis['median_delay_minutes']}분")
    extra=f'<a class="secondary-link" href="{E(bankis_link)}">모멘텀 연구 화면 (Layer 2) ↗</a>' if bankis_link else '<span class="dim">모멘텀 모듈 분리됨 (Layer 2)</span>'
    banner='<div class="banner">DEMO · SYNTHETIC DATA · 실제 종목 및 주가 아님</div>' if sample else '<div class="banner">자료 출처 독립 검증 전 · 실제 주문 및 자동매매 기능 없음</div>'
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Market Intelligence | 전략 중립</title><style>
:root{{--bg:#0c1219;--card:#15212b;--panel:#111b24;--border:#2a3946;--text:#e9f0f5;--muted:#9cb0bf;--accent:#8bdccb;--red:#efaa91;--amber:#e8c88d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;line-height:1.55}}main{{max-width:1180px;margin:auto;padding:32px 22px 80px}}a{{color:#9acddf;text-decoration:none}}a:hover{{text-decoration:underline}}header{{display:flex;justify-content:space-between;align-items:center;gap:16px;border-bottom:1px solid var(--border);padding-bottom:24px}}.brand{{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:1.6px}}h1{{font-size:27px;letter-spacing:-.4px;line-height:1.2;margin:8px 0}}h2{{font-size:17px;margin:0}}h3{{font-size:14px}}.dim,.tiny{{color:var(--muted)}}.tiny{{font-size:12px}}.stamp{{color:var(--muted);font-size:13px}}.banner{{background:#2b2924;border:1px solid #514532;border-radius:9px;padding:11px 15px;color:#f4d69d;font-size:13px;margin:18px 0}}.headline{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}.kpi{{border:1px solid var(--border);background:var(--card);padding:19px;border-radius:12px}}.kpi span{{display:block;font-size:12px;color:var(--muted)}}.kpi b{{font-size:27px;display:block;margin-top:4px;font-variant-numeric:tabular-nums}}.block{{border:1px solid var(--border);border-radius:12px;background:var(--panel);margin-top:16px;overflow:hidden}}.head{{padding:18px 19px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}.body{{padding:18px 19px}}.notice{{padding:15px 19px;display:flex;gap:18px;justify-content:space-between;align-items:center;flex-wrap:wrap}}.pill{{font-size:10px;font-weight:700;padding:5px 8px;color:#b9d3de;background:#293b47;border-radius:5px;display:inline-flex;white-space:nowrap}}.pill.sev-high{{color:#ffd0a8;background:#4a342d}}.pill.sev-medium{{color:#e8dcaf;background:#3d392d}}.pill.warning{{background:#5d302e;color:#ffd1ca}}.controls{{display:flex;gap:8px;flex-wrap:wrap}}input,select{{background:#0b151d;border:1px solid #3a4a58;color:var(--text);padding:9px 11px;border-radius:8px;min-width:155px}}input{{min-width:210px}}.observation{{border-bottom:1px solid var(--border);padding:18px 19px}}.observation:last-child{{border-bottom:0}}.badges{{display:flex;gap:5px;flex-wrap:wrap}}.obs-title{{font-size:17px;font-weight:750;margin:8px 0 2px}}.obs-title .dim{{font-size:12px;font-weight:400}}.obs-row p{{margin:7px 0;font-size:14px}}.obs-meta{{font-size:11px;color:var(--muted);margin-top:9px}}summary{{cursor:pointer;font-size:12px;color:var(--accent);margin:12px 0}}details[open]{{border-top:1px dashed var(--border);margin-top:13px;padding-top:6px}}.detail-grid{{display:grid;grid-template-columns:1fr 1fr;gap:22px;font-size:13px}}.eyebrow{{font-size:10px;letter-spacing:1px;font-weight:750;color:var(--muted);margin-top:15px;text-transform:uppercase}}.detail-grid p{{line-height:1.85}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border-bottom:1px solid #293845;padding:12px 14px;text-align:left}}th{{font-size:11px;color:var(--muted)}}.table-wrap{{overflow:auto}}.empty{{padding:22px;color:var(--muted);font-size:13px}}.foot{{color:var(--muted);font-size:12px;margin-top:24px;line-height:1.9}}.taglink{{background:#1a3537;border:1px solid #356e68;color:var(--accent);padding:9px 11px;border-radius:7px;font-size:12px}}.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}ul{{margin:0;padding-left:19px}}li{{margin:7px 0}}@media(max-width:800px){{.headline{{grid-template-columns:repeat(2,1fr)}}.grid2,.detail-grid{{grid-template-columns:1fr}}header{{align-items:flex-start;flex-direction:column}}h1{{font-size:24px}}.notice{{display:block}}.controls>input{{width:100%}}}}
</style></head><body><main><header><div><div class="brand">MARKET INTELLIGENCE / EVIDENCE FIRST</div><h1>시장 변화 및 위험 브리핑</h1><div class="stamp">전략 중립 Layer 1 · 강세점수 없음 · 주문 실행 없음</div></div><div class="stamp">관측 기준 KST<br><b>{E(res['asof'])}</b><br>{extra}</div></header>
{banner}<div class="headline"><div class="kpi"><span>관측 / 공급 레코드</span><b>{q['visible_observations']} / {q['input_observations']}</b></div><div class="kpi"><span>현재·비충돌 관측</span><b>{q['current_nonconflicting']}</b></div><div class="kpi"><span>출처 충돌 / 데이터 오류</span><b>{q['conflicts']} / {q['invalid_rows']}</b></div><div class="kpi"><span>시간 경과 관측</span><b>{q['stale']}</b></div></div>
<section class="block"><div class="head"><h2>지난 보고 이후 무엇이 달라졌는가?</h2>{changehtml}</div><div class="notice"><div><b>정보 판단용 보고서</b><div class="tiny">{E(status_note)}</div></div><div class="taglink">이상이 곧 매수/매도 신호는 아닙니다</div></div></section>
<section class="block"><div class="head"><div><h2>주요 관측 및 반대 근거</h2><div class="tiny">고객 전략을 전제하지 않는 사건·유동성·위험 관측</div></div><div class="controls"><input id="search" placeholder="종목 · 사건 · 지표 검색" aria-label="관측 검색"><select id="category" aria-label="정보 종류"><option value="">모든 종류</option>{''.join(f'<option value="{E(k)}">{E(v)}</option>' for k,v in CAT_KO.items())}</select><select id="severity" aria-label="우선순위"><option value="">모든 중요도</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></div></div><div id="observations">{''.join(obs)}</div><div class="body tiny" id="visibleCount"></div></section>
<section class="block"><div class="head"><h2>예정된 사건 · 확정 여부</h2><div class="tiny">아직 발생하지 않은 사건은 예정 정보로만 분류</div></div><div class="table-wrap"><table><thead><tr><th>예정일</th><th>대상</th><th>사건</th><th>상태</th><th>근거</th></tr></thead><tbody>{future}</tbody></table></div></section>
<div class="grid2"><section class="block"><div class="head"><h2>데이터 경보 및 제외</h2></div><div class="body"><ul>{quality_list}</ul><p class="tiny">제외 기록의 본문은 미래정보 누설 방지를 위해 표시하지 않습니다.</p></div></section><section class="block"><div class="head"><h2>유효성 측정</h2></div><div class="body"><b>{E(kpitxt)}</b><p class="tiny">알림이 수익을 개선했는지는 상사의 전략·거래결과를 모르면 측정할 수 없습니다. 검증되지 않은 알파는 주장하지 않습니다.</p><p class="tiny">제공된 관측 레코드에 한한 커버리지입니다. 한국시장 전수 데이터로 해석하지 마십시오.</p></div></section></div>
<div class="foot">원칙: 관측과 해석 구분 · 선공개 금지 · 출처·관측·공개·수집시각 분리 · 출처 충돌 보존 · 미확인 시 미확인 표시. "전략 중립"은 모든 전략에 같은 경제적 효과를 준다는 뜻이 아닙니다. 보고서의 수치와 공개 출처는 원문과 교차검증할 필요가 있습니다.</div></main>
<script>const controls=['search','category','severity'].map(id=>document.getElementById(id));function apply(){{const [q,c,s]=controls.map(x=>x.value.toLowerCase().trim());let n=0;document.querySelectorAll('.observation').forEach(e=>{{const ok=(!q||e.dataset.search.toLowerCase().includes(q))&&(!c||e.dataset.filter.toLowerCase()===c)&&(!s||e.dataset.severity.toLowerCase()===s);e.hidden=!ok;if(ok)n++;}});document.getElementById('visibleCount').textContent=`현재 필터로 ${{n}}건 표시`;}}controls.forEach(x=>x.addEventListener('input',apply));apply();</script></body></html>'''


def write_intelligence(res, folder, *, kpis=None, bankis_link=None):
    target=Path(folder);target.mkdir(parents=True,exist_ok=True)
    fp={'json':target/'intelligence.json','markdown':target/'intelligence.md',
        'html':target/'intelligence.html','csv':target/'intelligence_observations.csv'}
    fp['json'].write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
    fp['markdown'].write_text(render_markdown(res,kpis),encoding='utf-8')
    fp['html'].write_text(render_html(res,kpis,bankis_link=bankis_link),encoding='utf-8')
    cols=['id','entity','category','severity','status','quality','metric','value','unit','previous_value',
          'expected_value','delta','surprise','observed_at','available_at','source_name','source_class','source_url','fact','potential_impact']
    with fp['csv'].open('w',newline='',encoding='utf-8-sig') as fh:
        writer=csv.DictWriter(fh,fieldnames=cols);writer.writeheader()
        for row in res['observations']:writer.writerow({k:row.get(k) for k in cols})
    if kpis is not None:
        k=target/'kpis.json';k.write_text(json.dumps(kpis,ensure_ascii=False,indent=2),encoding='utf-8')
        fp['kpis']=k
    return {key:str(path) for key,path in fp.items()}
