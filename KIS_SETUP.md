# KIS 모의투자 연결

`project/.env`에 로컬 키가 설정되어 있습니다. 키와 토큰은 공유하지 마세요.
CLI는 프로젝트의 `.env`를 자동으로 읽으며, 이미 설정된 환경변수가 우선합니다.
모의투자 서버 설정은 `KIS_ENV=vps`입니다.

프로젝트 폴더에서 실행:

```powershell
.\.venv\Scripts\python.exe -m bankis_scout.verify_kis
.\.venv\Scripts\python.exe -m pytest -q
```

검증은 인증, 삼성전자(005930)·JYP Ent.(035900) 일봉, 코스피·코스닥 지수를 조회합니다.
결과는 `reports/kis_verification/status.json`과 CSV에 저장됩니다.
키와 접근 토큰은 결과 파일에 저장하지 않습니다.
표본의 비어 있지 않은 응답과 기본 데이터 계약을 검사하며, 전체 종목 수집,
원거래소 데이터와의 독립 대조, 계좌 연동, 실전 서버, 수익성을 검증한 것은 아닙니다.
이 결과 파일은 시장정보 보고서나 예약 브리핑에 자동 연결되지 않습니다.

새 환경 설치:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
```
