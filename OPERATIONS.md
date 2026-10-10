# 실제 데이터 운영 연결

## GitHub 실행과 기존 ChatGPT 예약

서버를 별도로 구매하지 않는 운영 경로를 설정했습니다.
`amandalmoon/bankis_scout`의 GitHub Actions에 매일 00:17 KST 모의 KIS 전수 수집을 예약했습니다.
실행 결과는 로그인 권한이 필요한 Actions 첨부파일에 3일간 보관하고,
`delivery/latest.json`에는 실행 상태·보고서 시각·첨부파일 식별자만 기록합니다.
저장소 소스는 공개되어 있으며 계좌번호·키·로컬 원장은 소스에 포함하지 않습니다.
KIS 앱 키와 시크릿은 저장소 Secrets를 사용합니다.

기존 ChatGPT `08시 시장정보·뱅키스 브리핑`의 반복 일정은 유지하고,
당일 READY 보고서를 GitHub 연결 도구로 읽도록 지침을 저장했습니다.
2026-10-10 08:02 KST 실제 예약에서 첫 클라우드 보고서를 읽은 결과를 확인했습니다.
예약 결과에서 내려받은 ZIP과 GitHub 원본 ZIP 및 내부 6개 파일의 해시가 일치했습니다.
설정 저장과 예약 실행의 성공은 구분합니다. 실제 실행·첨부파일 검증 결과는
`reports/github_artifact_check.json`, `reports/chatgpt_scheduled_check.json`, `reports/operations_status.json`을 확인하세요.
실패·지연·오래된 보고서는 해당 상태를 표시하며 최신 보고서로 대체해 해석하지 않습니다.
GitHub 예약은 지연될 수 있으므로 08:00 공급 완료를 보장하지 않습니다.
캐시는 장기 성과 원장의 영구 보관소가 아니므로 독립 성과 검증에는 별도 보존이 필요합니다.
자세한 설정은 `GITHUB_OPERATIONS.md`에 있습니다.

## 현재 설정

`.env`는 모의투자(vps) 키를 사용합니다. 실전 키는 아직 없습니다.
현재 KIS 마스터의 코스피·코스닥 주식(ST/RT/PF/IF/MF/DR/FS)을 수집합니다.
영문자가 들어 있는 6자리 코드도 지원합니다. ETF·ETN·채권·권리는 제외합니다.
마스터와 수신 자료의 스냅샷을 보존하며, 이는 과거 시점의 전수 상장목록을 인증하지 않습니다.

프로젝트 폴더에서:

```powershell
.\.venv\Scripts\python.exe -m bankis_scout.collect_all
.\.venv\Scripts\python.exe -m bankis_scout.pipeline
```

수집은 모의 서버에서 동시 응답 대기 중에도 요청 시작 간격을 0.65초로 제한합니다.
중단 후 같은 날짜 범위로 재실행하면 검증된 종목 캐시를 재사용하고 실패 종목을 재시도합니다.
`data/kis_all/collection_status.json`이 최종 수집 영수증입니다. PARTIAL은 전수 완료가 아닙니다.
분석에 필요한 이력 부족·거래정지 등은 별도 표시되며 거래자격을 자동으로 승인하지 않습니다.
보고서 생성 시 수신 지수의 최근 25거래일과 종목 이력을 대조해 누락을 점검합니다.
이 점검은 수신 시계열끼리의 대조이며, 독립적인 KRX 과거 거래일·상장목록 인증은 아닙니다.
동일 수집 폴더에서 수집 명령을 동시에 실행하지 마세요.
동시 실행은 `collection.lock`과 `pipeline.lock`으로 차단합니다. 강제 종료로 잠금이 남았다면
실제로 해당 프로세스가 종료됐는지 확인한 뒤 남은 잠금을 제거하고 재개합니다.

## 계좌 조회

`.env`의 `KIS_CANO`에는 모의계좌번호 앞 8자리, `KIS_ACNT_PRDT_CD`에는 실제 뒤 2자리를 입력합니다.
뒤 2자리가 없으면 조회를 차단합니다. 값이 01이라고 추측해서 채우지 마세요.

```powershell
.\.venv\Scripts\python.exe -m bankis_scout.account --start 2026-10-01 --end 2026-10-09
```

잔고와 체결 조회 GET만 허용합니다. 원장은 `.secrets/account`에 보관되고 보고서 서버에는 노출하지 않습니다.
Windows에서는 디렉터리의 실제 접근권한을 확인해야 하며 POSIX chmod만으로 Windows ACL 제한을 보장하지 않습니다.
계좌상품코드 미입력 상태에서 실행하면 `NOT_CONNECTED`입니다.

## 실전 서버

실전 키 발급 후 `.env.production.example`을 `.env.production`으로 복사해 실제 키·계좌를 로컬에서 입력합니다.
모의 키를 실전 서버로 보내지 않습니다. 실전 검증은 별도 데이터 폴더를 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m bankis_scout.collect_all --env-file .env.production --output data/kis_prod
.\.venv\Scripts\python.exe -m bankis_scout.account --env-file .env.production
```

기존 프로세스 환경변수가 `.env`보다 우선합니다. 실전·모의 설정이 섞이지 않도록 별도 실행 환경을 사용합니다.

## 수익성 검증

`data/forward_validation/plan.json`에 전략 코드 해시, 비교군, 기간, 비용 시나리오, 최소 표본을 사전 등록합니다.
평일 09:00 전에 완료된 전수 수집·동일 위험/자격 심사 결과만 사전 기록합니다.
같은 날짜 기록을 덮어쓰지 않습니다. 휴장일 기록은 나중에 거래 세션 자료와 대조해 제외합니다.
기록 시점 이후 실제 시가·종가가 확보된 세션만 선정군과 거래대금 상위 비교군을 비교합니다.
60개 짝지어진 세션 이후 일간 종속성을 고려한 5일 블록 부트스트랩 구간을 계산합니다.
비용(10/33/60bp)은 가정이고 실제 체결·세금·수수료 확인 전 결과는 탐색적 모의성과입니다.
대회 자격이 확인되지 않으면 후보와 성과를 억지로 만들지 않습니다.
기존 역사적 이벤트 연구만으로는 과거 종목·거래자격·수집시각의 독립 검증을 충족하지 않습니다.
실제 계좌성과 검증에는 의사결정 연결 체결·비용·입출금 자료가 추가로 필요합니다.

## 별도 Linux 서버를 사용할 경우

아래는 GitHub 실행과 별개로 서버·도메인을 직접 운영할 때의 대안입니다.
Linux 서버의 `/opt/bankis`에 프로그램을 배치하고 `bankis` 사용자 소유로 설정합니다.
로컬 `.venv`를 복사하지 말고 서버에서 `python3 -m venv .venv` 후 `.venv/bin/pip install .`로 설치합니다.
재현 가능한 의존성 설치는 `.venv/bin/pip install -r requirements.lock` 후 `.venv/bin/pip install --no-deps .`입니다.
`BANKIS_HOME=/opt/bankis`가 설정되어 wheel 설치 후에도 설정·데이터를 올바른 운영 폴더에 저장합니다.
서버에 `.env`를 별도로 전달하고 `chmod 600 .env`, 계좌 원장 디렉터리는 소유자 전용으로 설정합니다.

```bash
.venv/bin/python -m bankis_scout.briefing_server --init-token
.venv/bin/python -m bankis_scout.pipeline --collect
sudo cp deploy/bankis-collect.service deploy/bankis-collect.timer deploy/bankis-report.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bankis-collect.timer bankis-report.service
```

수집 예약은 매일 07:00 KST입니다. 수집 시간이 길면 더 일찍 조정해야 합니다.
`systemctl list-timers bankis-collect.timer`와 service 실행 결과를 확인합니다.
TLS reverse proxy는 `deploy/nginx-report.example.conf`를 실제 도메인·인증서로 설정합니다.
보고서 URL은 `https://도메인/BRIEFING_READ_TOKEN값/briefing.md`이며 읽기 비밀을 포함하므로 공유 범위를 제한합니다.
서버는 허용된 7개 파일(보고서 4개, 일별 종목·지수 CSV 2개, manifest.json)만 제공합니다.
CSV는 일별 OHLCV이며 실시간 호가·체결 시세가 아닙니다. 고정된 열 목록으로 계좌 및 추가 열을 제외합니다.
보고서 생성 시 데이터와 SHA-256 목록을 함께 완성한 뒤 CURRENT를 전환합니다.
`https://도메인/토큰/manifest.json`을 먼저 읽고, 목록의 snapshot_id를 사용해
`https://도메인/토큰/snapshot_id/briefing.md` 등 동일 회차 파일을 읽습니다.
파일 변경·손상은 HTTP 503으로 차단합니다. 이전 4개 파일만 있던 회차는 재생성해야 합니다.
디렉터리·키·계좌 원장은 제공하지 않습니다. 해시는 전송 파일 일치 검사이며 독립적인 출처 인증이 아닙니다.
당일 보고서가 없으면 HTTP 503으로 차단합니다. 실제 URL에는 HTTPS가 필요합니다.

연결 검증은 다음 명령으로 모든 파일을 실제 읽어 크기·해시를 대조합니다.
로컬 검사는 외부 공급 또는 ChatGPT 예약 연결 완료를 뜻하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m bankis_scout.verify_feed --local
```

배포 후 서버/로컬 `.env`에 `BRIEFING_BASE_URL=https://실제도메인`을 저장하고
`python -m bankis_scout.verify_feed`를 실행합니다. 주소에 토큰을 붙이지 않습니다.
리다이렉트는 거부해 다른 서버로 읽기 토큰이 전달되지 않게 합니다.
검증 영수증은 reports/feed_local_check.json 또는 feed_remote_check.json입니다.
REMOTE_HTTP_VERIFIED는 해당 검사 프로그램의 원격 읽기 성공이며 ChatGPT 예약 읽기는 별도입니다.

그 후 기존 ChatGPT 예약의 지시문에 실제 주소를 넣습니다. 연결용 초안은 `deploy/chatgpt-0800-prompt.txt`입니다.
ChatGPT 예약에서 해당 주소 읽기가 성공하는지와 08:00 실행 결과를 별도로 확인해야 합니다.
이 파일을 만들었다는 사실은 ChatGPT 예약 변경 완료를 뜻하지 않습니다.
브라우저/예약의 URL 접근 권한에 따라 읽기 비밀이 포함된 주소가 차단될 수 있으며 실제로 시험해야 합니다.
실행 환경의 Docker 데몬은 현재 미실행 상태이므로 Docker 이미지는 아직 빌드 검증하지 않았습니다.

공식 자료: [KIS 종목 마스터](https://github.com/koreainvestment/open-trading-api/tree/main/stocks_info),
[잔고 조회](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_balance/inquire_balance.py),
[체결 조회](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_ccld/inquire_daily_ccld.py),
[OpenAI 예약 작업](https://learn.chatgpt.com/docs/automations?surface=app).
