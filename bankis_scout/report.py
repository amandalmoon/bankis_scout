"""Portable, standalone HTML + Markdown + machine-readable audit outputs."""
from __future__ import annotations
import csv
import html
import json
from pathlib import Path

REASON_KO={
"INVALID_OHLC_OR_SOURCE":"시세 또는 출처값이 잘못됨", "CONFLICTING_DUPLICATE":"같은 날짜에 상충하는 시세", 
"INSUFFICIENT_HISTORY":"25개 이상 일봉이 필요", "NO_ASOF_PRICE":"관측 가능한 일봉 없음",
"LOW_TURNOVER":"마지막 거래일 거래대금 부족", "LOW_HISTORICAL_LIQUIDITY":"20일 중앙 거래대금 부족",
"CORPORATE_ACTION_OR_DATA_SPIKE":"액면분할·권리변동 또는 비정상 급변 검증 필요",
"ELIGIBILITY_UNVERIFIED":"대회 거래가능 여부 미검증", "ELIGIBILITY_NOT_KNOWN_AT_ASOF":"당시 확인된 대회 거래가능 정보 없음",
"ELIGIBILITY_STALE":"거래가능/경보 확인이 오래됨", "ELIGIBILITY_NO_SOURCE":"대회거래 및 위험 검증 출처 없음",
"NOT_CONTEST_ELIGIBLE":"대회 거래 불가", "CORPORATE_DISCLOSURE_REVIEW":"증자·CB·계약취소 등 공시 재검토 필요",
"MISSING_BENCHMARK":"시장 지수 데이터 부재", "BENCHMARK_PRICE_DATE_MISMATCH":"종목과 시장지수 기준일 불일치",
"INSUFFICIENT_BENCHMARK":"시장지수 비교기간 부족", "STALE_BENCHMARK":"시장지수 데이터 오래됨",
"BENCHMARK_DATE_ALIGNMENT_MISSING":"시장지수와 날짜 정렬 불가", "STALE_LAST_BAR":"오래된 일봉",
"UNKNOWN_MARKET":"코스피/코스닥 시장 구분 없음", "SCORE_BELOW_WATCH_THRESHOLD":"강세 점수 기준 미달",
"ZERO_BASE_VOLUME":"과거 거래량 기준 계산 불가", "INSUFFICIENT_PREVIOUS_20":"과거 20거래일 자료 부족",
"TWO_BARS_BELOW_VWAP":"2개 분봉 연속 VWAP 아래", "FALSE_BREAKOUT_CONFIRMED":"초기 고점 돌파 후 재이탈",
"SPREAD_TOO_WIDE":"매수·매도 호가 차이가 너무 큼", "NO_CONFIRMED_ENTRY_PATTERN":"검증된 진입 형태 없음",
"ORB_AND_VWAP_AND_VOLUME":"초기 고점·VWAP·거래량 동시 확인", "VWAP_PULLBACK_RECOVERY":"VWAP 부근 조정 후 재회복",
"VENUE_SCOPE_NOT_KRX":"KRX 기준일봉과 장중 거래소 범위 불일치", "OPENING_RANGE_INCOMPLETE":"초기 15분 봉 정보 불완전", "PREOPEN_WATCHLIST_MISSING_FUTURE_OR_TOO_OLD":"장전 후보 기준시각 누락·미래 또는 오래됨", "TRADED_VALUE_UNITS_OR_PRICE_MISMATCH":"거래대금 단위 또는 가격 불일치", "OPENING_LOW_AND_VWAP_BROKEN":"개장 저점·VWAP 함께 이탈",
}

def E(value):return html.escape(str(value),quote=True)

def pct(val):return f"{val:+.2f}%" if isinstance(val,(int,float)) else "미확인"

def get_rows(res):
    return res.get("records",[])


def markdown_brief(res:dict, sample=False) -> str:
    rows=get_rows(res)
    ts=res.get("asof", "unknown")
    pre = res.get("mode","PREOPEN_WATCHLIST_ONLY")
    verified = [x for x in rows if x.get("status")=="WATCH"]
    lines=[f"# BankIS Scout | {ts}",
           f"> {'교육용 합성 데이터. 실제 종목/매매 추천 아님.' if sample else '수집된 데이터로 만든 연구용 후보 목록. 매수 지시 아님.'}",
           f"> 모드: `{pre}` | 점수: 검증 전 휴리스틱 (승률/확률이 아님)",
           f"> 입력 종목: {len(rows)} | 관찰 후보: {len(verified)} | 탈락/정보차단: {len(rows)-len(verified)}", "",
           "## 장전 관찰 후보", "| 종목 | 구분 | 점수 | 당일 참고 수준(전일) | 5일 시장 초과수익률 | 거래량 배율 |",
           "|---|---|---:|---|---:|---:|"]
    for r in verified[:8]:
        f=r["features"]
        safe=lambda a:str(a).replace("|","/")
        lines.append(f"| {safe(r['name'])} ({r['code']}) | {safe(r['market'])} | {r['score']:.1f} | 고 {f.get('last_high','?')} / 저 {f.get('last_low','?')} | {f.get('rs5_pctp','?')}%p | {f.get('rvol_eod','?')}x |")
    if not verified:lines.append("| 검증된 후보 없음 | - | - | - | - | - |")
    lines += ["", "## 후보별 확인할 점"]
    for r in verified[:8]:
        f=r["features"]
        lines += [f"### {r['name']} ({r['code']})", f"- 전일 종가 {f.get('last_close','미확인')}원, 20일선 {f.get('ma20','미확인')}원, 직전 20일 최고가 {f.get('prev_high20','미확인')}원",
                  f"- 최근 확인된 촉매: {', '.join(e['title'] for e in r.get('events',[]) if e['verified']) or '검증된 긍정 촉매 없음'}",
                  "- 09:20 이후 5분봉 완료 → ORB·VWAP·거래량 신호 확인 전에는 매수조건 미확정",
                  "- 반증: VWAP 재이탈, 초기 범위 돌파 실패, 스프레드 확대, 공시 위험 발견",
                  f"- 경고: {', '.join(r['warnings']) if r['warnings'] else '없음'}",""]
    lines.extend(["## 거절 / 데이터 부족 사유"])
    for r in rows:
        if r["status"]!="WATCH":
            lines.append(f"- **{r['name']} ({r['code']})** `{r['status']}`: "+", ".join(REASON_KO.get(x,x) for x in r["reasons"]))
    lines += ["", "## 소스·누락·의사결정 범위",
              "- 각 종목의 source와 마지막 거래일은 JSON/HTML 상세 화면에서 확인합니다.",
              "- 서류/공시 촉매 점수는 확인된 URL과 명시적 중요도 평가가 있는 경우에만 부여합니다.",
              "- 업종별 상대강도·실시간 체결·대회 계좌/순위는 본 버전에 자동 연동되지 않았습니다.",
              "- 8시 지표는 전일 확정 일봉 기준이며 당일 VWAP, ORB, 호가·체결은 포함하지 않습니다.",
              "- 역사적 백테스트 통계와 실제 매수 판단은 구분해야 합니다."]
    return "\n".join(lines)+"\n"


def render_html(res:dict,sample=False) -> str:
    rows=get_rows(res)
    title = "장중 재검증" if res.get("mode","").startswith("INTRADAY") else "장전 강세주 스캐너"
    counts={"WATCH":0,"REJECTED":0,"DATA_BLOCKED":0,"CONFIRMED_PATTERN":0}
    for r in rows:
        k=r.get("intraday_status") if res.get("mode","").startswith("INTRADAY") else r.get("status")
        if k in counts:counts[k]+=1
    trs=[]
    for i,r in enumerate(rows):
        status=r.get("intraday_status",r.get("status","?"))
        feat=r.get("features",{})
        det=r.get("intraday",{})
        src=r.get("source_type","-")
        reason=r.get("intraday_reasons",r.get("reasons",[]))
        rs=feat.get("rs5_pctp")
        rv=feat.get("rvol_eod")
        tag="WATCH" if status=="WATCH" else ("CONFIRMED" if status=="CONFIRMED_PATTERN" else status)
        score_val=r.get("score")
        score_text=(f"{score_val:.2f}" if isinstance(score_val,(int,float)) else "미산정")
        score_width=(min(100,max(0,float(score_val))) if isinstance(score_val,(int,float)) else 0)
        text_reasons=" / ".join(REASON_KO.get(x,x) for x in reason) or "점수 기준 통과 / 실시간 확인 전"
        evid="".join(f'<div class="evidence"><a href="{E(x["url"])}" rel="noopener noreferrer" target="_blank">{E(x["title"])}</a><small>{E(x["published_at"])} / 신뢰 검증 {"예" if x["verified"] else "아니오"}</small></div>'
                     for x in r.get("events",[]) if str(x.get("url","")).startswith("https://")) or "<span class='muted'>확인된 공시 촉매 없음</span>"
        comps="".join(f'<div class="barmetric"><span>{E(k)}</span><b>{v:g}</b></div>' for k,v in r.get("components",{}).items())
        fs=" ".join(f"{E(k)}: <strong>{E(v)}</strong>" for k,v in feat.items())
        xs=" ".join(f"{E(k)}: <strong>{E(v)}</strong>" for k,v in det.items())
        trs.append(f'''<tr data-status="{E(status)}" data-market="{E(r.get('market',''))}" data-hay="{E(r.get('name',''))} {E(r.get('code',''))} {E(r.get('sector',''))}">
        <td><span class="num">{i+1:02d}</span></td><td><b>{E(r.get('name',''))}</b><div class="muted mono">{E(r.get('code',''))} · {E(r.get('sector',''))}</div></td>
        <td>{E(r.get('market',''))}</td><td class="score"><div><strong>{E(score_text)}</strong><div class="bar"><span style="width:{score_width}%"></span></div></div></td>
        <td><span class="chip {E(status.lower())}">{E(tag)}</span></td>
        <td>{E(feat.get('last_date','미확인'))}</td><td>{pct(rs).replace('%','%p') if rs is not None else '미확인'}</td>
        <td>{f'{rv:.2f}×' if isinstance(rv,(int,float)) else '미확인'}</td>
        <td><button class="toggle" data-detail="d{i}" aria-expanded="false">상세 보기 ↓</button></td></tr>
        <tr id="d{i}" class="detailrow" hidden><td colspan="9"><div class="details">
        <div><h4>판단 · 차단 근거</h4><p>{E(text_reasons)}</p><h4>지표별 기여</h4>{comps}</div>
        <div><h4>관측값과 출처</h4><p class="metadata">{fs}</p><p class="metadata">{xs}</p><p class="muted">원천: {E(src)}</p><h4>공시 · 원문</h4>{evid}</div>
        </div></td></tr>''')
    tab="".join(trs) or "<tr><td colspan='9'>검증된 입력이 없습니다.</td></tr>"
    head=f"{counts['WATCH']} 관찰" if not res.get('mode','').startswith('INTRADAY') else f"{counts['CONFIRMED_PATTERN']} 패턴 확인"
    warning=("교육용 합성 입력입니다. 실제 주가나 투자 추천이 아닙니다." if sample else
             "실제 입력 데이터 기반 연구 결과입니다. 점수는 수익 확률이 아닙니다. 8시에는 매수 신호를 확정할 수 없습니다.")
    # All source strings are escaped in generated HTML and injected only as text.
    return f'''<!doctype html><html lang="ko"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>BankIS Scout | {E(title)}</title><style>
:root{{--bg:#08101b;--panel:#111e2e;--border:#293950;--text:#eaf1ff;--sub:#9aaec5;--mint:#5bdab3;--amber:#f3be76;--red:#fb8e93}}
*{{box-sizing:border-box}} body{{background:var(--bg);font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;color:var(--text);margin:0;line-height:1.55}}
main{{max-width:1380px;margin:auto;padding:32px 24px 70px}}header{{display:flex;align-items:center;justify-content:space-between;gap:20px;border-bottom:1px solid var(--border);padding-bottom:24px}}
.brand{{font-weight:800;letter-spacing:1.6px;color:var(--mint);font-size:13px}}h1{{font-size:28px;margin:8px 0}} .muted,small{{color:var(--sub);font-size:12px}} .mono{{font-family:ui-monospace,monospace}} .stamp{{color:var(--sub);font-size:13px;text-align:right}}
.notice{{padding:14px 17px;margin:23px 0;color:var(--amber);background:#342a20;border:1px solid #695033;border-radius:9px;font-size:14px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:19px 0 26px}}
.kpi{{border:1px solid var(--border);border-radius:12px;background:var(--panel);padding:19px}}.kpi label{{display:block;font-size:12px;color:var(--sub);letter-spacing:.5px}}.kpi strong{{font-size:31px}}.kpi .mint{{color:var(--mint)}}.kpi .red{{color:var(--red)}}
.panel{{background:var(--panel);border:1px solid var(--border);border-radius:14px;overflow:hidden}} .panelhead{{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:20px 22px;border-bottom:1px solid var(--border);flex-wrap:wrap}}h2{{font-size:16px;margin:0}}
.controls{{display:flex;gap:8px;flex-wrap:wrap}} input,select{{background:#0b1625;border:1px solid #3a4b63;color:var(--text);padding:10px 12px;border-radius:8px;min-width:145px}} input{{min-width:220px}}
.tablewrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th{{background:#142338;color:#a4b9ce;text-align:left;font-size:11px;letter-spacing:.45px;text-transform:uppercase;white-space:nowrap}}th,td{{padding:15px 12px;border-bottom:1px solid #24364a;vertical-align:middle}}td{{white-space:nowrap}}tr:hover td{{background:#182941}} .score strong{{font-size:17px}}.num{{color:var(--sub)}}.bar{{width:85px;height:4px;background:#25374b;border-radius:5px}}.bar span{{height:4px;display:block;background:var(--mint);border-radius:5px}}
.chip{{display:inline-block;font-weight:700;font-size:10px;letter-spacing:.3px;padding:6px 9px;border-radius:6px;background:#283444;color:#b8c8d8}}.chip.watch,.chip.confirmed_pattern{{color:#67ebbc;background:#153c36}}.chip.rejected,.chip.warning{{color:#ffc795;background:#493326}}.chip.data_blocked{{color:#ffaaaa;background:#48303a}}
.toggle{{cursor:pointer;border:1px solid #35536b;color:#b7dce9;border-radius:6px;padding:7px 10px;background:#142b3a;white-space:nowrap}}
.details{{display:grid;grid-template-columns:1fr 1fr;gap:32px;padding:10px 12px 23px;white-space:normal}}.details h4{{color:var(--sub);text-transform:uppercase;font-size:11px;letter-spacing:1px;margin:17px 0 10px}}.details p{{margin:8px 0}}.metadata{{line-height:2.3;font-size:12px}} .barmetric{{display:flex;justify-content:space-between;border-bottom:1px solid #294052;padding:5px 0;font-size:12px}}.barmetric b{{color:var(--mint)}}a{{color:#a3d7ff;text-decoration:none}}a:hover{{text-decoration:underline}}.evidence{{padding:6px 0}}.evidence small{{display:block}}
.footer{{color:var(--sub);font-size:12px;margin-top:20px}}@media(max-width:800px){{.kpis{{grid-template-columns:repeat(2,1fr)}}header{{align-items:flex-start}}h1{{font-size:24px}}.details{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><div class="brand">BANKIS SCOUT / RESEARCH TERMINAL</div><h1>{E(title)}</h1><div class="muted">강세 후보 선정 · 탈락 원인 기록 · 주문 실행 없음</div></div><div class="stamp">KST 관측 기준<br/><strong>{E(res.get('asof','?'))}</strong><br/>기준 일봉 ≤ {E(res.get('last_allowed_daily_date','미표시'))}</div></header>
<div class="notice">{E(warning)}</div>
<div class="kpis"><div class="kpi"><label>분석 종목</label><strong>{len(rows)}</strong></div><div class="kpi"><label>후보 / 확인</label><strong class="mint">{head}</strong></div><div class="kpi"><label>사전 탈락</label><strong>{counts['REJECTED']}</strong></div><div class="kpi"><label>정보 부족 차단</label><strong class="red">{counts['DATA_BLOCKED']}</strong></div></div>
<section class="panel"><div class="panelhead"><div><h2>판단 대기열</h2><div class="muted">행을 펼치면 지표 기여와 탈락 근거를 확인할 수 있습니다.</div></div>
<div class="controls"><input id="search" placeholder="종목명 · 코드 · 업종 검색" aria-label="종목 검색"/><select id="status" aria-label="판단 상태"><option value="">전체 상태</option><option value="WATCH">WATCH</option><option value="CONFIRMED_PATTERN">CONFIRMED</option><option value="WARNING">WARNING</option><option value="REJECTED">REJECTED</option><option value="DATA_BLOCKED">DATA_BLOCKED</option></select><select id="market" aria-label="시장"><option value="">전체 시장</option><option>KOSPI</option><option>KOSDAQ</option></select></div></div>
<div class="tablewrap"><table><thead><tr><th>No.</th><th>종목</th><th>시장</th><th>강세점수</th><th>판정</th><th>전일 데이터</th><th>5D 초과강도</th><th>RVOL</th><th>근거</th></tr></thead><tbody>{tab}</tbody></table></div></section>
<div class="footer">자료 추출 단위는 종목/일자/거래소이며 과거 정보의 발표시각을 초과해 사용하지 않도록 별도 검증합니다. 업종 초과강도·호가 히스토리·대회 개인순위는 추가 권한 없이는 제공하지 않습니다. 투자 조언이나 자동 매매 기능이 아닙니다.</div>
</main><script>
const search=document.getElementById('search'), status=document.getElementById('status'), market=document.getElementById('market');
function update(){{let q=search.value.toLowerCase().trim();document.querySelectorAll('tr[data-status]').forEach(tr=>{{let ok=(!q||tr.dataset.hay.toLowerCase().includes(q))&&(!status.value||tr.dataset.status===status.value)&&(!market.value||tr.dataset.market===market.value);tr.hidden=!ok;let d=tr.nextElementSibling;if(!ok&&d&&d.classList.contains('detailrow'))d.hidden=true;}})}}
[search,status,market].forEach(el=>el.addEventListener('input',update));document.querySelectorAll('.toggle').forEach(btn=>btn.addEventListener('click',()=>{{let d=document.getElementById(btn.dataset.detail);d.hidden=!d.hidden;btn.setAttribute('aria-expanded',String(!d.hidden));btn.textContent=d.hidden?'상세 보기 ↓':'접기 ↑';}}));
</script></body></html>'''


def write_artifacts(res:dict, out: str | Path, sample=False, stem="preopen") -> dict:
    sample = bool(sample or any("SYNTHETIC" in str(x.get("source_type","")) for x in res.get("records",[])))
    p=Path(out); p.mkdir(parents=True,exist_ok=True)
    jsonp=p/f"{stem}.json"; mdp=p/f"{stem}.md"; htmlp=p/f"{stem}.html"; csvp=p/f"{stem}_candidates.csv"
    jsonp.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding="utf-8")
    mdp.write_text(markdown_brief(res,sample),encoding="utf-8")
    htmlp.write_text(render_html(res,sample),encoding="utf-8")
    rows=[]
    for x in res.get("records",[]):
        f=x.get("features",{})
        rows.append({"code":x["code"],"name":x["name"],"market":x["market"],"status":x.get("intraday_status",x["status"]),
                     "score":x["score"],"reason":";".join(x.get("intraday_reasons",x.get("reasons",[]))),
                     "source":x.get("source_type",""),"last_date":f.get("last_date",""),"rs5_pctp":f.get("rs5_pctp",""),"rvol_eod":f.get("rvol_eod","")})
    cols=["code","name","market","status","score","reason","source","last_date","rs5_pctp","rvol_eod"]
    with csvp.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(rows)
    return {"json":str(jsonp),"markdown":str(mdp),"html":str(htmlp),"csv":str(csvp)}
