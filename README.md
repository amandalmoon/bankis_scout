> GitHub 운영 연결(2026-10-10): 매일 00:17 KST에 KIS 모의 서버 전수 수집과 v2 보고서 생성을 예약했습니다. 키는 저장소 Secrets로 연결하며 계좌자료는 공급 파일에서 제외합니다. 첫 실행은 2,769종목·242,215행 수집에 성공했고, 기존 ChatGPT 08시 예약의 실제 보고서 읽기와 다운로드 ZIP의 해시 일치를 확인했습니다. 다음 자동 수집도 성공했으나 예약 지연이 관측되어 준비 시간을 앞당겼습니다. 최신 상태는 [delivery/latest.json](delivery/latest.json), 데이터와 보고서는 Actions artifact에서 확인합니다. 로컬·GitHub Linux 테스트 90개 통과. 실전·계좌 연동과 독립적인 수익성 입증은 미완료입니다. 자세한 안내는 [GITHUB_OPERATIONS.md](GITHUB_OPERATIONS.md)를 확인하세요.

# BankIS Market Intelligence v2.0 / Strategy-neutral intelligence and BankIS Scout

**Status (2026-10-09):** This is a working research prototype, NOT a validated alpha, automated trading app, market-wide live feed, or order-execution system. The included demo is entirely SYNTHETIC. No investment decisions should be based on synthetic prices or fabricated consensus.

## Scope: two independent layers

- **Layer 1: Market Intelligence** (`intelligence.html` / `intelligence.json`). An evidence ledger that records new facts, measurable changes, truly pre-event expectations, risk, liquidity, market structure, counterevidence, publication/observation/ingestion timestamps, provenance disagreements and real source-access gaps. It does not rank BUY candidates or prescribe a strategy.
- **Layer 2: BankIS Scout** (`preopen.html` / `intraday.html`). The previous momentum-scanning research module. It is conceptually separate and its scores remain unvalidated heuristics, never the output of Layer 1.

## Quick start, Windows PowerShell

Unzip and open a PowerShell terminal in this directory (`project`). Install Python 3.10+ first.

```powershell
py -m pip install -e ".[test]"
py -m pytest -q tests
py -m bankis_scout demo --output reports/demo
py -m bankis_scout intel-demo --output reports/demo
start reports/demo/intelligence.html
start reports/demo/preopen.html
```

`intelligence.html` shows fictional entities explicitly labelled as DEMO / SYNTHETIC. `preopen.html` is the original, separate simulated momentum module. The reports work offline after generation, including interactive search/filters and expandable provenance/counterevidence. No live market data is fetched by these demo commands.

## Operational evidence format: no key required

Use `examples/observations_TEMPLATE.csv` and `examples/calendar_TEMPLATE.csv` to create **real, independently checked** observations. Both templates contain a header only: values must come from verified sources. Set `asof` to the actual time you want the report to represent, including `+09:00`.

```powershell
mkdir data/evidence
copy examples/observations_TEMPLATE.csv data/evidence/observations.csv
copy examples/calendar_TEMPLATE.csv data/evidence/calendar.csv
py -m bankis_scout intel --data-dir data/evidence --asof "2026-10-12T08:00:00+09:00" --output reports/evidence
start reports/evidence/intelligence.html
```

The explicit missing-data state is expected when evidence files have only headers. A report with zero verified facts is preferable to a false trading recommendation.

**Observation schema:** `id` uniquely identifies the evidence event; `entity` and `fact` state an observation, NOT a directional prediction; `category` belongs to `SURPRISE, ABNORMAL, LIQUIDITY, RISK, FLOWS, MARKET, CORPORATE, DATA_QUALITY`; `metric,value,unit` hold comparable numerical measurements. `previous_value, previous_observed_at, previous_source_url` are optional historical baselines. `expected_value, expected_asof, expected_source_url` are optional **pre-event** forecasts or consensus measurements. No numerical difference/"surprise" is calculated unless its baseline/expectation timestamp is strictly before the current observation and has a valid source URL; prior values are never filled with zeros. `observed_at, available_at, ingested_at` must be timezone-aware ISO timestamps and must satisfy `observed <= available <= ingested <= asof`. `source_url, source_name, source_class` document provenance; classes are `PRIMARY, SECONDARY, PROXY, USER_SUPPLIED`. `venue` distinguishes KRX/NXT; `severity` is information urgency, not an investment score; `potential_impact` is always an interpretation hypothesis. `counter_ids` joins visible independent evidence rows using `|` separators. `followup_at` marks review time.

**Calendar schema:** `id, entity, event, event_at, announced_at, ingested_at, source_url, source_name, certainty, exposure, expected_value, unit`. An upcoming event's occurrence in the calendar is NOT a release of its actual result; event announcements after `asof` are suppressed.

**Previous snapshot delta**: compare snapshots with `--previous reports/previous/intelligence.json`. Missing an item in a newer dataset means `not_reobserved`, never "withdrawn" or "resolved". Changes/newness are only computed relative to an actually provided previous snapshot.

**Source conflict**: same entity + metric + unit + observation timestamp + venue with different numeric values is retained in parallel as `CONFLICT`, never silently averaged or ranked. Duplicate IDs with different content are also flagged. A purported URL in a CSV is **not proof** that the page contains the asserted information: verified source content and precise release time remain a human/connector duty.

## Import existing Korean EOD CSV; optional OpenDART facts

This can reuse the daily stock/index CSV created by `fetch-kis` without the BankIS trading eligibility CSV required by Layer 2. `--source-url` MUST name a relevant real source of the loaded data, and timestamps MUST describe source availability and ingestion. Do not label an API documentation page as independent verification of the CSV rows.

```powershell
py -m bankis_scout intel-from-daily --data-dir data/real --source-url "https://SOURCE-OF-THE-ACTUAL-DATA" --available-at "2026-10-12T17:00:00+09:00" --ingested-at "2026-10-12T17:05:00+09:00" --asof "2026-10-13T08:00:00+09:00" --output reports/intelligence
```

For a complete merged EOD report (optional, when disclosures/events exist):

```powershell
py -m bankis_scout intel-pipeline --data-dir data/real --source-url "https://SOURCE-OF-THE-ACTUAL-DATA" --available-at "2026-10-12T17:00:00+09:00" --ingested-at "2026-10-12T17:05:00+09:00" --asof "2026-10-13T08:00:00+09:00" --dart-events data/real/events.csv --manual-evidence data/evidence/observations.csv --calendar data/evidence/calendar.csv --previous reports/previous/intelligence.json --output reports/intelligence
```

**These command examples are not usable as-is:** replace placeholder URLs and timestamps with the actual provenance and observed timing and omit non-existent optional paths. A KIS access key and separate allowed symbol universe are needed for market fetching (see Layer 2 guide below). Existing `events.csv` imports DART titles conservatively, without asserting bullishness. Date-only disclosure records are gated to the end of the day and cannot be used as if their release time were known during a prior morning. This importer does not independently fetch or authenticate the contents of every URL, nor does it establish full exchange coverage.

## Automated local collection and the ChatGPT 08:00 scheduled message

The local sample `scripts/preopen_intelligence_job.ps1` demonstrates a Windows Task Scheduler job: it invokes the read-only KIS fetcher, preserves the previous report, builds the new intelligence artifact, and stops if data collection failed. You must configure your own KIS permissions and review the actual provider timing. Run this script in your local environment; it was not scheduled on your PC by this package.

**The ChatGPT 08:00 KST daily task is a separate task.** Its text instructions were updated on 2026-10-09 to report Layer 1 first and BankIS Layer 2 as a separate appendix. That task does NOT read reports on this computer automatically. To make it consume local results, a supported, permitted persistent connector/file service must be set up and independently tested. ChatGPT app push/email notification settings may need enabling.

At 08:00 KST, KRX regular hours have not opened; do not call current-day ORB, regular-session VWAP, or 09:20 RVOL a measured fact. The next intraday verification must be performed separately, against current trade data and correct KRX/NXT market/venue coverage.

## Independent information-value evaluation

Without a complete, scoped, retrospectively adjudicated ledger of objectively important events **and** a timestamped detection/alert log, do not publish a precision, recall, or latency claim. The KPI command requires `ground_truth.csv` with columns `id,label,known_at` (labels `IMPORTANT` or `NOT_IMPORTANT`) and `alerts.csv` with columns `id,emitted_at`:

```powershell
py -m bankis_scout intel-kpis --report reports/intelligence/intelligence.json --ground-truth data/review/ground_truth.csv --alerts data/review/alerts.csv --output reports/intelligence/kpis.json
```

Detection metrics: precision = relevant alerts / all alerts; recall = relevant alerts / all truly important events in *complete reviewed scope*; alert delay = alert time minus first publicly known time (nonnegative). Even correctly computed detection metrics are **not** evidence of improved PnL. PnL uplift needs a controlled test with comparable market conditions, net costs, strategy actions and execution records. Do not invent a numeric benefit.

## Hard limits and what is still missing

| Item | Reality | Next operational verification |
|---|---|---|
| Complete KOSPI/KOSDAQ instrument and minute coverage | NOT connected | Validated universe, point-in-time listing coverage, licensed API permissions / limits |
| KIS API | Read-only adapter code, not live-authenticated here | User-owned credentials; record actual API replies; check schemas and rate limits |
| OpenDART | Optional title collector, no complete raw corporate filings | Verify corp codes, key access, disclosure contents and publication timestamps |
| Real KRX+NXT combined market | Not automatically consolidated | Explicit venue contracts, coverage tests and consistent timestamps |
| Real orderbook depth and costs | Not present in generic EOD CSV | Authorized feed and observable bid/ask before strategy claims |
| Prior-report comparison | Implemented only when prior snapshot supplied | Persist dated successive reports |
| Strategy alpha and PnL uplift | Not established | Forward validation, transaction costs, matched baselines |
| Daily ChatGPT alert + local report | Updated text task, separate local program | Approved storage connector, authenticated and tested read access |
| Morning delivery notification | Schedule active; push/email might be off | Review ChatGPT Tasks/notification settings |

Security: keep API keys outside the project; NEVER paste KIS_APP_SECRET/DART_API_KEY in chat, commit them, or include them in a report. No trade placement code is included. Do not submit example URLs as real evidence.

---

## Previous BankIS Scout v1 documentation (Layer 2, preserved)

# BankIS Scout v1.0 — 강세주 선별·오판 차단 시스템

> **개인 모의투자대회 연구용, 읽기 전용**. 이 소프트웨어는 주식 **주문 기능을 제공하지 않습니다**. 강세 점수는 예상 수익률이나 승률이 아니라 **검증 전 후보 선별 규칙**입니다.

2026-10-09 제작. 한국투자증권 공식 API의 **시세 조회 전용 엔드포인트**에 연결하도록 구현했습니다. API 인증키 및 대회별 허용 종목 정보가 없으므로 **실제 장세 기반 추천종목은 생성하거나 검증하지 않았습니다.** 기본 제공 SYN001~SYN006은 모두 **인공 합성** 시계열입니다.

## 0. 무엇이 완성됐고, 무엇이 아직 안 됐나

| 기능 | 상태 | 정확한 범위 |
|---|---|---|
| 일봉 OHLCV 검증 | **구현·테스트 완료** | 음수/비정상 OHLC, 중복 충돌, 데이터가 없는 종목, 미래 데이터 방지 |
| 국내주식 강세 스크리닝 | **구현·테스트 완료** | 유동성, 거래량 확대, 시장 대비 상대강도, 가격구조, 공시 점수 |
| 독립 위험 게이트 | **구현·테스트 완료** | 대회 대상·시장경보 확인, 공시 위험, 신뢰할 수 없는 시세, 얇은 거래대금 |
| 9:20 이후 장중 재확인 | **CSV로 구현·테스트 완료** | 완료된 5분봉 기준 ORB/VWAP 및 스프레드·돌파실패 차단 |
| HTML 대시보드 / MD / JSON / CSV | **구현·테스트 완료** | 종목별 판단/사유/원천 확인, 브라우저 검색·필터·상세 열기 |
| 날짜순 사후 검증 | **구현·테스트 완료** | 다음날 시가~h일 뒤 종가 이벤트 스터디, 미래정보 사용 방지 |
| KIS 일봉·지수 조회 HTTP 어댑터 | **구현·모의 응답 테스트 완료** | KIS 실서버 호출은 **미검증**. 본인 발급 키·접근권한 필요 |
| KIS 분봉/호가 조회 HTTP 어댑터 | **구현·서버 미검증** | 거래 중 권한/응답 형식 검증 필요; 불완전하면 차단 |
| OpenDART 신규 공시 수집기 | **구현·서버 미검증** | corp_code, API 키 필요; 공시의 경제적 영향은 자동 확정하지 않음 |
| 전체 KOSPI/KOSDAQ 전종목 완전 스캔 | **미완성** | 종목 유니버스·시세 수집 한도와 데이터 접근 권한 확인 필요 |
| KRX/NXT 동시 전체 호가장·정확한 체결 시뮬레이터 | **미구현** | 지연·시장별 계약·입수범위에 제약 |
| 대회 계좌 및 순위 연동 | **미연결** | 개인 인증 및 대회 계좌 API 지원 여부 미확인 |
| 기존 ChatGPT 8시 예약과 자동 파일 연결 | **미연결** | 예약 작업은 이 PC의 로컬 보고서 파일에 자동 접근하지 못함 |
| 실제 한국시장 성과·초과수익 증명 | **미검증** | 현시점 실제 데이터 기반 OOS 증거 없음 |

## 1. 3분 설치 (Windows)

1. [Python](https://www.python.org/downloads/) 3.10 이상 설치, 설치 시 PATH 체크.
2. 이 압축파일을 원하는 폴더에 풀기 (예: `C:\\bankis-scout`).
3. 압축 해제된 폴더에서 PowerShell을 열고 아래를 실행합니다.

```powershell
py -m pip install -e .
py -m pytest -q tests
py -m bankis_scout demo --output reports/demo
start reports/demo/preopen.html
```

테스트에는 `pytest`가 필요하며 없으면 `py -m pip install pytest`를 먼저 실행하십시오. `scripts/run_demo.bat` 더블클릭으로도 샘플 보고서를 생성할 수 있습니다.

**주의:** `reports/demo`와 `synthetic_input`의 값은 실제 주가가 아닙니다. `SYNxxx`라는 종목코드는 실제 거래에 쓰이지 않습니다.

## 2. 실제 데이터 연결 (KIS 시세)

1. KIS Developers에서 본인 사용 조건에 맞는 API 접근 권한을 발급합니다.
2. 터미널 세션 환경변수에 `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ENV=prod`를 설정합니다. `prod`는 **시세 조회 API 호스트**를 뜻하며 실전 주문 기능은 본 프로젝트에 없습니다. `vps`는 일부 조회 API 지원 범위가 다를 수 있습니다.
3. 본인의 관심종목 목록을 `examples/universe.csv`에서 편집합니다. 이것은 **전체 상장주식 목록이 아니라 명시적 관찰 유니버스**입니다. 순위 API의 장전 데이터는 날짜가 확인되지 않는 한 확정 전일 순위로 취급하지 않습니다.
4. 일봉과 코스피/코스닥 지수를 내려받습니다.

```powershell
$env:KIS_APP_KEY="본인 KIS API 앱키"
$env:KIS_APP_SECRET="본인 KIS API 시크릿"
$env:KIS_ENV="prod"
py -m bankis_scout fetch-kis --universe examples/universe.csv --out-data data/real
```

**키는 이 채팅에 보내거나 Git에 커밋하지 마십시오.** 이 앱은 `/quotations/` 하위 조회 API만 허용하며 `order-cash`, `inquire-balance` 등 계좌/주문 기능은 없습니다.

5. 대회 허용 종목·시장경보 확인 정보를 검증한 후 `data/real/eligibility.csv`를 아래 스키마로 **직접 작성**합니다. 거래소/대회 출처 없이 `eligible=true`로 임의 설정하지 마십시오.

```csv
code,eligible,risk_level,checked_at,source_url
005930,true,NONE,2026-10-12T07:45:00+09:00,https://[실제-공식-확인-URL]
```

이 URL은 형식 예시입니다. 실제 검증 없이 템플릿을 그대로 사용해서는 안 됩니다. 정보가 없으면 엔진은 **DATA_BLOCKED** 처리하며 매수 후보를 만들어내지 않습니다. 대회 사용 가능 범위는 반드시 해당 회차 공식 규정에 따릅니다.

6. 아래 명령으로 오전 8시 **장전 참고 종목**을 만듭니다.

```powershell
py -m bankis_scout screen --data-dir data/real --output reports/live
start reports/live/preopen.html
```

8시에 알 수 없는 당일 VWAP/ORB/호가를 전일 수치처럼 표시하지 않습니다.

## 3. DART 공시 (선택)

`examples/universe.csv`의 `dart_corp_code` 필드에 **종목코드와 별개인 DART 고유번호**를 입력합니다. OpenDART 키가 있으면:

```powershell
$env:DART_API_KEY="본인 OpenDART 키"
py -m bankis_scout fetch-dart --universe examples/universe.csv --out-events data/real/events.csv
```

기본 수집 값의 `materiality=0`이며, 공시 제목만 보고 긍정적인 점수를 자동 배정하지 않습니다. 원문 내용, 기업의 규모 대비 효과, 일정 등을 검토 후 `materiality`를 0~5로 **사람이 수정**할 수 있습니다. 위험한 기업행위 키워드가 있으면 확인 전까지 별도 심사 대상으로 차단합니다. OpenDART `list.json`은 공시 일자만 알 수 있는 경우가 있어 보수적으로 해당일 23:59에 공개된 것으로 처리합니다.

## 4. 장중 09:20 이후 재검증

장전 `reports/live/preopen.json`을 만들고, 당일 분봉 입력 `data/real/intraday.csv`를 채웁니다. 다음과 같이 KIS 어댑터도 제공하지만 **실서버 KIS 분봉 응답의 누적거래대금/호가정합성 검증을 마쳐야 운영에 투입**할 수 있습니다.

```powershell
py -m bankis_scout fetch-kis-intraday --watch reports/live/preopen.json --out-csv data/real/intraday.csv
py -m bankis_scout recheck --watch reports/live/preopen.json --data-dir data/real --output reports/intraday
start reports/intraday/intraday.html
```

`intraday.csv`는 `bar_end,code,venue,open,high,low,close,volume,turnover_krw,bid,ask,source`를 요구합니다. `bar_end`는 각 봉이 **완전히 종료된 시각** (예: `2026-10-12T09:05:00+09:00`)이어야 합니다. `turnover_krw`는 봉 안에서 **실제로 체결된 거래대금(원)**이며, 종가×거래량 대체치로 위장할 수 없습니다. 최신 스프레드에는 해당 시각 근처의 유효한 최우선 bid/ask가 필요합니다.

장중 가격이 상승했다고 바로 매수 명령을 내리지 않습니다. 다음 상태가 나타납니다.

| 상태 | 의미 |
|---|---|
| `WATCH` | 사전 조건은 통과했으나 진입 형태 미확인 |
| `CONFIRMED_PATTERN` | ORB/VWAP/거래량 등 **형태** 확인. 실제 승률은 미검증 |
| `WARNING` | VWAP 이탈 등 진입 근거 약화 |
| `REJECTED` | 가짜 돌파, 과도한 스프레드, 고위험 조건 |
| `DATA_BLOCKED` | 공시·거래허용·분봉·호가·일봉 등이 없어 판단 금지 |

**REST 분봉 단점:** 요청 시점의 최근 데이터만 반환되거나 거래소 범위가 달라 초기 15분봉을 복원하지 못할 수 있습니다. 이 경우 차단 상태로 유지됩니다. 실전 운영에는 09:00부터 연속 분봉 저장 작업이나 이용 약관에 맞는 실시간 구독이 필요합니다.

## 5. 사후 검증 (수익성 *증명* 아님)

```powershell
py -m bankis_scout backtest --data-dir data/real --hold-days 1 --top 3 --cost-bps 33 --output reports/event_study.json
```

하루 뒤 시가에 진입하고 1거래일 뒤 종가에 나왔다는 단순한 사건 연구입니다. 3일 보유를 검토하려면 `--hold-days 3`을 쓰십시오. `cost-bps 33`은 거래 비용 **가정값**이고 실제 대회의 세금/체결료는 회차별 규정을 확인해야 합니다.

**중요한 한계:** 이 결과에는 지정가 미체결, 실시간 호가 충격, 개별 손절·수량 제약, 매수 금지, 상·하한가, 동시 보유 포지션 관리가 반영되지 않습니다. 평균 사건 수익률을 실제 계좌 누적 수익률로 오해해서는 안 됩니다. 특히 과거 대회 거래 가능 여부의 시점별 자료가 없으면 `DATA_BLOCKED`가 많아져 평가가 불가능할 수 있습니다. `selected_all`, `baseline_all`과 마지막 20% 신호일의 보류 구간이 같이 출력됩니다. 결과가 비어 있으면 **우수한 전략이라고 주장해서는 안 됩니다**.

## 6. 위험 게이트와 순위 점수

가중치(최대 100)는 1차 연구 설정입니다.

- 유동성 20점: 현재 거래대금 규모 (로그 정규화)
- 거래량 확대 15점: 최근 20일 중앙 거래량 대비 마지막 거래일의 RVOL
- 시장 상대강도 20점: 동일 거래일 지수와 1일/5일 초과수익률 비교
- 가격 구조 20점: 20일선·직전 고점과 단기 가격 변화
- 공시 촉매 15점: 출처가 확인되고 사람이 0~5로 평가한 공시
- 종가 위치 10점: 하루 가격범위 안에서 종가의 상대적 위치

점수 60 이상이면 **WATCH**일 뿐 BUY 신호가 아닙니다. 아래 중 하나에 해당하면 점수가 높아도 탈락·차단합니다: 대회 거래자격 미검증/거래금지, 위험 공시, 거래대금 부족, 일봉 데이터 결손·미래정보, 지수 비교 기준일 불일치, 급격한 주식수 변동 가능성, 최근 호가가 넓거나 잘못됨.

## 7. 일일 일정과 기존 오전 8시 예약과의 관계

- 07:40 개인 PC 또는 서버에서 `fetch-kis` 수행 (API 허용 범위 내).
- 07:50 `screen` 실행 후 `reports/live/preopen.md`/`.html` 생성.
- 08:00 기존 ChatGPT의 '뱅키스 8시 강세주 브리핑' 예약은 **별도 시스템**으로 작동합니다. **자동으로 로컬 리포트를 읽는 것은 아닙니다**. 연동하려면 Google Drive 등 승인된 공용 파일 소스에 보고서를 올리는 별도 작업과 커넥터 접근권한이 필요합니다.
- 09:20 이후 `fetch-kis-intraday` (초기 데이터가 모두 있는지 확인) → `recheck` 수행.
- 장 종료 후 주문내역·매수조건·탈락사유와 이후 수익률 기록.

Windows 작업 스케줄러로 07:50 `screen`을 로컬 실행할 수 있지만, PC가 켜져 있어야 하고 사용자 환경변수 및 인증 토큰이 있어야 합니다. 자동으로 ChatGPT 알림에 동봉되지 않습니다.

## 8. 데이터 주의사항

- **원시 데이터 보존:** 출처, 가격단위(원), 시장코드, 수정주가 적용 여부를 확인하세요. KIS 연동은 장중 실제 체결가격과의 비교를 위해 **원주가**를 조회하므로 액면분할·권리락 발생 시 데이터 재구성이 필요합니다.
- **한정된 종목 유니버스:** `universe.csv`에 있는 종목만 평가합니다. 상장폐지·거래정지 종목을 빼놓고 과거 데이터를 연구하면 생존자 편향이 생깁니다.
- **정보 시점:** 뉴스를 보았던 시각과 실제 공시가 공개된 시각이 달라질 수 있습니다. OpenDART의 일자만 있는 자료를 장중에 이미 알았다고 사용하지 않습니다.
- **KIS 시세 서비스 제한:** 사용계정마다 API 사용권한/호출량/시장 범위가 다를 수 있습니다. 조회 불가 시 0을 넣지 않고 `DATA_BLOCKED`로 표시합니다.
- **거래소 범위:** KRX 기준 데이터와 KRX+NXT 통합 데이터를 섞지 않습니다. 이번 데모·조회 기본 설정은 KRX입니다.
- **가격 정확도:** 개인 리그 모의거래 체결조건은 공식 규정과 실제 계좌에서 검증해야 합니다. 이 시스템에는 가상 주문 엔진이 없습니다.

## 9. 사용한 공식 문서

- KIS API 공식 개발 예시: https://github.com/koreainvestment/open-trading-api
- KIS 기간별시세: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py
- KIS 지수 일봉: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_indexchartprice/inquire_daily_indexchartprice.py
- KIS 거래량 순위: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/volume_rank/volume_rank.py
- KIS 분봉: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_time_itemchartprice/inquire_time_itemchartprice.py
- OpenDART: https://opendart.fss.or.kr/
- KRX DATA: https://data.krx.co.kr/
- KIND: https://kind.krx.co.kr/
