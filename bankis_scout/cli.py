"""CLI entry point. All commands are data-only; no order requests are implemented."""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from .settings import KST, parse_asof, Settings
from .data import load_bundle,DataContractError
from .engine import screen_bundle
from .monitor import recheck
from .report import write_artifacts
from .demo import create_demo


def _now():return datetime.now(KST).isoformat()

def main(argv=None):
    from dotenv import load_dotenv
    from .runtime import project_root
    load_dotenv(project_root() / ".env", override=False)
    a=argparse.ArgumentParser(prog="bankis-scout",description="KRX/KOSDAQ read-only stock candidate selection & rejection engine")
    sub=a.add_subparsers(dest="cmd",required=True)
    d=sub.add_parser("demo",help="create SYNTHETIC example data and reports")
    d.add_argument("--output",default="reports/demo")
    s=sub.add_parser("screen",help="08:00 pre-open EOD candidate screen")
    s.add_argument("--data-dir",required=True);s.add_argument("--asof",default=_now());s.add_argument("--output",default="reports/preopen")
    m=sub.add_parser("recheck",help="post-09:20 completed-bar pattern recheck; no orders")
    m.add_argument("--data-dir",required=True);m.add_argument("--watch",required=True)
    m.add_argument("--asof",default=_now());m.add_argument("--output",default="reports/intraday")
    b=sub.add_parser("backtest",help="conservative next-open horizon-close event study")
    b.add_argument("--data-dir",required=True);b.add_argument("--hold-days",type=int,default=1)
    b.add_argument("--top",type=int,default=3);b.add_argument("--cost-bps",type=float,default=33.0)
    b.add_argument("--output",default="reports/event_study.json")
    k=sub.add_parser("fetch-kis",help="authenticated read-only market daily data; KIS API keys required")
    k.add_argument("--universe",required=True);k.add_argument("--out-data",required=True)
    k.add_argument("--asof",default=_now());k.add_argument("--max-symbols",type=int,default=45)
    kin=sub.add_parser("fetch-kis-intraday",help="KIS read-only 1-minute snapshots to strict 5-minute bars")
    kin.add_argument("--watch",required=True);kin.add_argument("--out-csv",required=True)
    kin.add_argument("--asof",default=_now())
    dk=sub.add_parser("fetch-dart",help="collect official disclosures, no automatic impact scoring")
    dk.add_argument("--universe",required=True);dk.add_argument("--out-events",required=True)
    dk.add_argument("--asof",default=_now())
    di=sub.add_parser("discover-kis",help="find a current trading value shortlist; VERIFY market and time manually")
    di.add_argument("--output",default="reports/discovery.csv")
    # Layer 1 is strategy neutral. Layer 2 remains the existing BankIS momentum system.
    ild=sub.add_parser("intel-demo", help="produce a wholly SYNTHETIC strategy-neutral information report")
    ild.add_argument("--output",default="reports/intel-demo")
    il=sub.add_parser("intel",help="create independent Market Intelligence from evidence CSVs")
    il.add_argument("--data-dir",required=True)
    il.add_argument("--asof",default=_now());il.add_argument("--output",default="reports/intelligence")
    il.add_argument("--previous",default=None,help="previous intelligence.json snapshot for genuine changes")
    il.add_argument("--ground-truth",default=None,help="complete, labelled retrospective event set CSV")
    il.add_argument("--alerts",default=None,help="timestamped alert ledger CSV")
    ildaily=sub.add_parser("intel-from-daily",help="derive neutral price/volume observations from existing daily CSV")
    ildaily.add_argument("--data-dir",required=True)
    ildaily.add_argument("--asof",default=_now());ildaily.add_argument("--output",default="reports/intelligence")
    ildaily.add_argument("--source-url",required=True)
    ildaily.add_argument("--available-at",required=True)
    ildaily.add_argument("--ingested-at",required=True)
    ildaily.add_argument("--max-items",type=int,default=12)
    ilpipe=sub.add_parser("intel-pipeline",help="merge EOD market observations with DART/manual evidence; keep strategy-neutral")
    ilpipe.add_argument("--data-dir",required=True)
    ilpipe.add_argument("--asof",default=_now())
    ilpipe.add_argument("--source-url",required=True)
    ilpipe.add_argument("--available-at",required=True)
    ilpipe.add_argument("--ingested-at",required=True)
    ilpipe.add_argument("--dart-events",default=None)
    ilpipe.add_argument("--manual-evidence",default=None,help="additional observation CSV facts, not trading scores")
    ilpipe.add_argument("--calendar",default=None)
    ilpipe.add_argument("--previous",default=None)
    ilpipe.add_argument("--output",default="reports/intelligence")
    ilpipe.add_argument("--max-items",type=int,default=12)
    ilmetric=sub.add_parser("intel-kpis",help="evaluate evidence-alert performance against a complete labelled scope")
    ilmetric.add_argument("--report",required=True)
    ilmetric.add_argument("--ground-truth",required=True)
    ilmetric.add_argument("--alerts",required=True)
    ilmetric.add_argument("--output",default="reports/intelligence/kpis.json")
    try:
        args=a.parse_args(argv)
        if args.cmd=="demo":
            out=Path(args.output)
            create_demo(out/"synthetic_input")
            bundle=load_bundle(out/"synthetic_input")
            result=screen_bundle(bundle,"2026-10-09T08:00:00+09:00")
            paths=write_artifacts(result,out,sample=True,stem="preopen")
            mini=recheck(result,bundle["intraday"],"2026-10-12T09:37:00+09:00")
            paths.update({"intraday_"+k:v for k,v in write_artifacts(mini,out,sample=True,stem="intraday") .items()})
            print(json.dumps({"synthetic_only":True,"coverage":result["coverage"],"paths":paths},ensure_ascii=False,indent=2))
        elif args.cmd=="screen":
            bundle=load_bundle(args.data_dir)
            result=screen_bundle(bundle,args.asof)
            paths=write_artifacts(result,args.output,stem="preopen")
            print(json.dumps({"coverage":result["coverage"],"paths":paths},ensure_ascii=False,indent=2))
        elif args.cmd=="recheck":
            bundle=load_bundle(args.data_dir)
            base=json.loads(Path(args.watch).read_text(encoding="utf-8"))
            output=recheck(base,bundle["intraday"],args.asof)
            paths=write_artifacts(output,args.output,stem="intraday")
            print(json.dumps({"coverage":output["coverage"],"paths":paths},ensure_ascii=False,indent=2))
        elif args.cmd=="backtest":
            from .backtest import event_study
            bundle=load_bundle(args.data_dir)
            result=event_study(bundle,hold_days=args.hold_days,top_n=args.top,cost_bps=args.cost_bps)
            out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps({"status":result["status"],"summary":result["summary"],"file":str(out),"limitations":result.get("limitations",[])},ensure_ascii=False,indent=2))
        elif args.cmd=="fetch-kis":
            from .kis import KISClient,fetch_bundle
            response=fetch_bundle(KISClient(),args.universe,args.out_data,args.asof,max_symbols=args.max_symbols)
            print(json.dumps(response,ensure_ascii=False,indent=2))
        elif args.cmd=="fetch-kis-intraday":
            from .kis import KISClient,fetch_intraday_from_kis
            response=fetch_intraday_from_kis(KISClient(),args.watch,args.out_csv,args.asof)
            print(json.dumps(response,ensure_ascii=False,indent=2))
        elif args.cmd=="fetch-dart":
            from .dart import collect_disclosures
            response=collect_disclosures(args.universe,args.out_events,args.asof)
            print(json.dumps(response,ensure_ascii=False,indent=2))
        elif args.cmd=="intel-demo":
            from .intel_demo import synthetic_intel
            from .intelligence import read_intel_folder, evaluate_intelligence, evaluate_detection_kpis
            from .intel_report import write_intelligence
            out=Path(args.output)
            inp=synthetic_intel(out/"synthetic_input")
            observations, calendar=read_intel_folder(inp)
            report=evaluate_intelligence(observations,calendar,"2026-10-09T08:00:00+09:00",sample=True)
            link="preopen.html" if (out/"preopen.html").exists() else None
            files=write_intelligence(report,out,kpis=evaluate_detection_kpis(report),bankis_link=link)
            print(json.dumps({"synthetic_only":True,"quality":report["quality"],"files":files},ensure_ascii=False,indent=2))
        elif args.cmd=="intel":
            from .intelligence import read_intel_folder, evaluate_intelligence, evaluate_detection_kpis, read_csv, detect_synthetic
            from .intel_report import write_intelligence
            observations,calendar=read_intel_folder(args.data_dir)
            previous=json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
            report=evaluate_intelligence(observations,calendar,args.asof,previous=previous,
                sample=detect_synthetic(observations,calendar))
            truths=read_csv(args.ground_truth,["id","label","known_at"]) if args.ground_truth else None
            alerts=read_csv(args.alerts,["id","emitted_at"]) if args.alerts else None
            kpis=evaluate_detection_kpis(report,truths,alerts)
            files=write_intelligence(report,args.output,kpis=kpis)
            print(json.dumps({"quality":report["quality"],"kpis":kpis,"files":files},ensure_ascii=False,indent=2))
        elif args.cmd=="intel-from-daily":
            from .intel_adapter import describe_daily_bundle
            from .intelligence import evaluate_intelligence,evaluate_detection_kpis
            from .intel_report import write_intelligence
            obs,excluded=describe_daily_bundle(args.data_dir,args.asof,source_url=args.source_url,
                    available_at=args.available_at,ingested_at=args.ingested_at,max_items=args.max_items)
            from .data import csv_read, DAILY_FIELDS
            synth=csv_read(Path(args.data_dir)/'daily.csv',DAILY_FIELDS)['source'].astype(str).str.contains('SYNTHETIC',case=False).any()
            report=evaluate_intelligence(obs,[],args.asof,sample=synth)
            report['adapter_exclusions']=excluded
            files=write_intelligence(report,args.output,kpis=evaluate_detection_kpis(report))
            print(json.dumps({"quality":report["quality"],"adapter_exclusions":excluded,"files":files},ensure_ascii=False,indent=2))
        elif args.cmd=="intel-pipeline":
            from .intel_adapter import describe_daily_bundle
            from .intel_disclosures import disclosure_to_observations,save_observations_csv
            from .intelligence import evaluate_intelligence,evaluate_detection_kpis,read_csv,OBS_COLUMNS,CAL_COLUMNS,detect_synthetic
            from .intel_report import write_intelligence
            observations,excluded=describe_daily_bundle(args.data_dir,args.asof,
                source_url=args.source_url,available_at=args.available_at,
                ingested_at=args.ingested_at,max_items=args.max_items)
            if args.dart_events:
                observations.extend(disclosure_to_observations(args.dart_events,ingested_at=args.ingested_at))
            if args.manual_evidence:
                observations.extend(read_csv(args.manual_evidence,OBS_COLUMNS))
            events=read_csv(args.calendar,CAL_COLUMNS) if args.calendar else []
            prev=json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
            from .data import csv_read,DAILY_FIELDS
            demo=bool(csv_read(Path(args.data_dir)/'daily.csv',DAILY_FIELDS)['source'].astype(str).str.contains('SYNTHETIC',case=False).any())
            report=evaluate_intelligence(observations,events,args.asof,previous=prev,
                sample=(demo or detect_synthetic(observations,events)))
            report['adapter_exclusions']=excluded
            out=Path(args.output)
            out.mkdir(parents=True,exist_ok=True)
            save_observations_csv(out/'collected_observations.csv',observations)
            files=write_intelligence(report,out,kpis=evaluate_detection_kpis(report))
            files['collected_observations']=str(out/'collected_observations.csv')
            print(json.dumps({'quality':report['quality'],'files':files,'adapter_exclusions':excluded},ensure_ascii=False,indent=2))
        elif args.cmd=="intel-kpis":
            from .intelligence import evaluate_detection_kpis,read_csv
            report=json.loads(Path(args.report).read_text(encoding="utf-8"))
            gt=read_csv(args.ground_truth,["id","label","known_at"])
            al=read_csv(args.alerts,["id","emitted_at"])
            results=evaluate_detection_kpis(report,gt,al)
            outfile=Path(args.output);outfile.parent.mkdir(parents=True,exist_ok=True)
            outfile.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps(results,ensure_ascii=False,indent=2))
        elif args.cmd=="discover-kis":
            import pandas as pd
            from .kis import KISClient
            response=KISClient().volume_rank()
            p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
            pd.DataFrame(response).to_csv(p,index=False,encoding="utf-8-sig")
            print("KIS current-volume-rank discovery only (NO timestamp, market or contest eligibility verified):",p)
        return 0
    except (DataContractError, ValueError, RuntimeError, OSError) as exc:
        print("DATA/ACCESS BLOCKED:",str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    sys.exit(main())
