"""Point-in-time, fail-closed watchlist engine. Scores rank observations, never imply buys."""
from __future__ import annotations
from datetime import timedelta
import math
import pandas as pd
import numpy as np
from .data import prepare_daily, prepare_index, is_true
from .settings import Settings, last_allowed_daily_date, parse_asof

POSITIVE_EVENTS = {"earnings", "contract", "guidance", "policy", "product"}
RISK_TERMS = ("유상증자", "전환사채", "신주인수권", "거래정지", "관리종목", "감사의견", "감자", "계약해지", "계약취소")


def _clip(x: float, floor=0.0, cap=1.0) -> float:
    return float(min(cap, max(floor, x)))


def _f(x, digits=4):
    return round(float(x), digits) if np.isfinite(float(x)) else None


def _eligibility(elig: pd.DataFrame, code: str, asof, stale_days: int) -> list[str]:
    e = elig.loc[elig["code"].astype(str).str.zfill(6).eq(code)].copy()
    if e.empty: return ["ELIGIBILITY_UNVERIFIED"]
    e["checked_at_dt"] = pd.to_datetime(e["checked_at"], utc=True, errors="coerce")
    e = e[e["checked_at_dt"] <= pd.Timestamp(asof).tz_convert("UTC")].sort_values("checked_at_dt")
    if e.empty: return ["ELIGIBILITY_NOT_KNOWN_AT_ASOF"]
    last = e.iloc[-1]
    if pd.isna(last["checked_at_dt"]) or (pd.Timestamp(asof) - last["checked_at_dt"]).days > stale_days:
        return ["ELIGIBILITY_STALE"]
    if not str(last.get("source_url", "")).startswith("http"):
        return ["ELIGIBILITY_NO_SOURCE"]
    if not is_true(last["eligible"]): return ["NOT_CONTEST_ELIGIBLE"]
    if str(last["risk_level"]).strip().upper() != "NONE":
        return ["RISK_FLAG:"+str(last["risk_level"])]
    return []


def _evaluate_events(events: pd.DataFrame, code: str, asof) -> tuple[float, list[str], list[dict]]:
    if events.empty: return 0.0, [], []
    ev = events[events["code"].astype(str).str.zfill(6).eq(code)].copy()
    if ev.empty: return 0.0, [], []
    ev["published"] = pd.to_datetime(ev["published_at"], errors="coerce", utc=True)
    ev = ev[(ev["published"] <= pd.Timestamp(asof).tz_convert("UTC")) &
            (ev["published"] >= pd.Timestamp(asof).tz_convert("UTC") - timedelta(days=7))]
    if ev.empty: return 0.0, [], []
    score = 0.0
    risk = []
    evidence = []
    for _, e in ev.iterrows():
        url = str(e["source_url"])
        title = str(e["title"])
        verified = is_true(e["verified"]) and url.startswith(("https://", "http://"))
        typ = str(e["event_type"]).strip().lower()
        material = pd.to_numeric(e["materiality"], errors="coerce")
        # Human-assessed materiality MUST have verified source, never inferred from an unverified headline.
        if verified and typ in POSITIVE_EVENTS and np.isfinite(material) and 0 <= material <= 5:
            score = max(score, min(15.0, float(material)*3))
        if any(term in title for term in RISK_TERMS):
            risk.append("CORPORATE_DISCLOSURE_REVIEW")
        evidence.append({"title":title,"published_at":e["published"].isoformat(),"url":url,
                         "verified":verified,"type":typ,"materiality":float(material) if np.isfinite(material) else None})
    return score, sorted(set(risk)), evidence


def screen_bundle(bundle: dict[str, pd.DataFrame], asof, settings: Settings | None = None) -> dict:
    cfg = settings or Settings()
    now = parse_asof(asof)
    cutoff = last_allowed_daily_date(now)
    daily, problems = prepare_daily(bundle["daily"], cutoff)
    index, idx_problems = prepare_index(bundle["index"], cutoff)
    elig = bundle["eligibility"]
    events = bundle.get("events", pd.DataFrame())
    records = []
    grouped = {str(code): group.sort_values("date") for code, group in daily.groupby("code", sort=False)}
    benchmarks = {str(market): group.sort_values("date") for market, group in index.groupby("market", sort=False)}
    all_codes = sorted(grouped)
    for code in all_codes:
        g = grouped[code]
        # Metadata also comes from the permitted historical slice, never a future row.
        name = str(g.iloc[-1]["name"]) if len(g) else code
        market = str(g.iloc[-1]["market"]) if len(g) else "UNVERIFIED"
        sector = str(g.iloc[-1]["sector"]) if len(g) else "UNVERIFIED"
        reasons = list(problems.get(code, []))
        warnings = []
        scores = {x:0.0 for x in ("유동성", "거래량 확대", "시장 상대강도", "가격 구조", "공시 촉매", "종가 위치")}
        features: dict = {}
        evidence = []
        if len(g) < cfg.history_min: reasons.append("INSUFFICIENT_HISTORY")
        if len(g):
            last = g.iloc[-1]
            features["last_date"] = str(last["date"])
            features["last_close"] = _f(last["close"], 2)
            features["last_turnover_krw"] = _f(last["turnover_krw"], 0)
            features["last_high"] = _f(last["high"], 2)
            features["last_low"] = _f(last["low"], 2)
            features["source"] = str(last["source"])
            if (cutoff - last["date"]).days > cfg.stale_days: reasons.append("STALE_LAST_BAR")
            if last["turnover_krw"] < cfg.min_turnover_krw: reasons.append("LOW_TURNOVER")
            if len(g) > 1:
                ret1 = last["close"]/g.iloc[-2]["close"]-1
                features["ret1_pct"] = _f(ret1*100, 2)
                if abs(ret1) > cfg.risk_move_limit: reasons.append("CORPORATE_ACTION_OR_DATA_SPIKE")
        else:
            reasons.append("NO_ASOF_PRICE")
        reasons.extend(_eligibility(elig, code, now, 14))
        cat_score, disclosure_risk, evidence = _evaluate_events(events, code, now)
        reasons.extend(disclosure_risk)
        scores["공시 촉매"] = cat_score
        if not evidence: warnings.append("NO_RECENT_VERIFIED_CATALYST: not a hard rejection")
        if market not in {"KOSPI", "KOSDAQ"}: reasons.append("UNKNOWN_MARKET")
        benchmark = benchmarks.get(market, index.iloc[0:0])
        if market in idx_problems: reasons.append(idx_problems[market])
        if benchmark.empty: reasons.append("MISSING_BENCHMARK")
        elif len(g):
            if last["date"] != benchmark.iloc[-1]["date"]:
                reasons.append("BENCHMARK_PRICE_DATE_MISMATCH")
            if len(benchmark) < cfg.history_min: reasons.append("INSUFFICIENT_BENCHMARK")
            if (cutoff - benchmark.iloc[-1]["date"]).days > cfg.stale_days:
                reasons.append("STALE_BENCHMARK")
        if len(g) >= cfg.history_min and len(benchmark) >= cfg.history_min:
            prev20 = g.iloc[-21:-1]
            if len(prev20) < 20: reasons.append("INSUFFICIENT_PREVIOUS_20")
            else:
                avg_t = float(prev20["turnover_krw"].median())
                vmed = float(prev20["volume"].median())
                if avg_t < cfg.min_median_turnover_krw: reasons.append("LOW_HISTORICAL_LIQUIDITY")
                if vmed <= 0: reasons.append("ZERO_BASE_VOLUME")
                else:
                    rvol = float(g.iloc[-1]["volume"]/vmed)
                    features["rvol_eod"] = _f(rvol, 2)
                    scores["거래량 확대"] = _f(15 * _clip((rvol-0.8)/3.2), 2)
                features["median_turnover20_krw"] = _f(avg_t, 0)
                scores["유동성"] = _f(20*_clip((np.log10(max(1,float(g.iloc[-1]["turnover_krw"]))) - np.log10(cfg.min_turnover_krw))/0.95), 2)
                ma20 = float(g.iloc[-20:]["close"].mean())
                prev_high20 = float(g.iloc[-21:-1]["high"].max())
                ret5 = g.iloc[-1]["close"]/g.iloc[-6]["close"]-1
                features.update({"ma20":_f(ma20,2), "prev_high20":_f(prev_high20,2), "ret5_pct":_f(ret5*100,2)})
                structure = (8 if g.iloc[-1]["close"]>ma20 else 0) + (7 if g.iloc[-1]["close"]>=prev_high20*.97 else 0) + (5 if g.iloc[-1]["close"]>g.iloc[-4]["close"] else 0)
                scores["가격 구조"] = structure
                day_range = float(g.iloc[-1]["high"] - g.iloc[-1]["low"])
                loc = ((float(g.iloc[-1]["close"])-float(g.iloc[-1]["low"]))/day_range) if day_range>0 else .5
                features["close_location"] = _f(loc,3)
                scores["종가 위치"] = _f(10*_clip(loc), 2)
                # Use identical exchange session dates for stock and index; fail if no index at comparison dates.
                idx_series = benchmark.set_index("date")["close"]
                dates = [g.iloc[-1]["date"],g.iloc[-2]["date"],g.iloc[-6]["date"]]
                if all(d in idx_series.index for d in dates):
                    m1 = float(idx_series.loc[dates[0]]/idx_series.loc[dates[1]]-1)
                    m5 = float(idx_series.loc[dates[0]]/idx_series.loc[dates[2]]-1)
                    s1 = float(g.iloc[-1]["close"]/g.iloc[-2]["close"]-1)
                    s5 = float(g.iloc[-1]["close"]/g.iloc[-6]["close"]-1)
                    rs1,rs5=s1-m1,s5-m5
                    features["rs1_pctp"] = _f(rs1*100,2)
                    features["rs5_pctp"] = _f(rs5*100,2)
                    scores["시장 상대강도"] = _f(8*_clip(rs1/.04)+12*_clip(rs5/.08),2)
                else: reasons.append("BENCHMARK_DATE_ALIGNMENT_MISSING")
        # An extreme rise is a warning, not a guaranteed decline; avoid false precision.
        if features.get("ret1_pct", 0)>22: warnings.append("EXTENDED_DAILY_MOVE")
        reasons = sorted(set(reasons))
        score = _f(sum(scores.values()),2)
        if any(r.startswith(("INVALID_", "CONFLICTING_", "MISSING_", "INSUFFICIENT_", "STALE_", "NO_ASOF_", "ELIGIBILITY_", "UNKNOWN_", "BENCHMARK_")) for r in reasons):
            status = "DATA_BLOCKED"
        elif reasons:
            status = "REJECTED"
        elif score < cfg.min_watch_score:
            status = "REJECTED"
            reasons = ["SCORE_BELOW_WATCH_THRESHOLD"]
        else:
            status = "WATCH"
        # Never show numerical strength from inputs that failed a required data contract.
        if status == "DATA_BLOCKED":
            score = None
            scores = {}
            if any(x in reasons for x in ("INVALID_OHLC_OR_SOURCE", "CONFLICTING_DUPLICATE")):
                features = {k:v for k,v in features.items() if k in ("source", "last_date")}
        records.append({"code":code,"name":name,"market":market,"sector":sector,"score":score,
                        "status":status,"reasons":reasons,"warnings":warnings,"components":scores,
                        "features":features,"events":evidence,"source_type":str(features.get("source","unknown"))})
    records.sort(key=lambda r:(0 if r["status"]=="WATCH" else 1, -(r["score"] if r["score"] is not None else -1),r["code"]))
    return {"app":"BankIS Scout v1","mode":"PREOPEN_WATCHLIST_ONLY","asof":now.isoformat(),"last_allowed_daily_date":str(cutoff),
            "method":"heuristic / uncalibrated / not a buy signal","assumptions":{"min_turnover_krw":cfg.min_turnover_krw,
            "min_median_turnover_krw":cfg.min_median_turnover_krw,"min_watch_score":cfg.min_watch_score},
            "coverage":{"input_symbols":len(all_codes),"watch":sum(r["status"]=="WATCH" for r in records),
            "rejected":sum(r["status"]=="REJECTED" for r in records),"data_blocked":sum(r["status"]=="DATA_BLOCKED" for r in records),
            "universe_exhaustive":False},"records":records}
