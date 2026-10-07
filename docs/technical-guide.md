# 기술 및 운영 가이드

프로젝트 실행, API 동작, 출력 파일과 운영 관련 세부사항을 설명합니다. 분석 설계는
[분석 방법론](analysis-methodology.md)을 참고하세요.

## 1. API 키

프로젝트 루트의 `.env.example`을 `.env`로 복사하고 사용할 키를 입력합니다.

| 키 | 서비스 | 용도 |
|---|---|---|
| `DART_KEY` | Open DART | 기업 검색과 재무제표 |
| `PUBLIC_STOCK_API_KEY` | 공공데이터포털 | 주식시세, KOSPI/KOSDAQ 지수 |
| `KOREAEXIM_API_KEY` | 한국수출입은행 | 원/달러 환율 |
| `ECOS_API_KEY` | 한국은행 ECOS | 국고채·회사채 금리 |
| `OPENAI_API_KEY` | OpenAI | KPI 기반 보조 인사이트 |

```text
DART_KEY=발급받은_Open_DART_API_키
PUBLIC_STOCK_API_KEY=공공데이터포털_서비스키
KOREAEXIM_API_KEY=수출입은행_인증키
ECOS_API_KEY=ECOS_인증키
OPENAI_API_KEY=OpenAI_API_키
OPENAI_MODEL=gpt-4o-mini
```

선택 API가 없거나 호출에 실패하면 해당 지표만 `출처 데이터 없음`으로 두고 가능한
분석은 계속합니다. OpenAI 호출이 실패해도 Python으로 계산한 KPI와 차트는 유지합니다.

## 2. 실행

### 웹 애플리케이션

```powershell
uv run --python 3.10 --isolated --with-requirements requirements.lock src/app.py
```

기본 주소는 `http://127.0.0.1:5000`이며 종료는 `Ctrl+C`입니다.

### CLI

`src/main.py` 상단의 기업명과 재무 조회기간을 수정합니다.

```python
COMPANIES = ["삼성전자", "SK하이닉스"]
START_YEAR = None
END_YEAR = None
NUMBER_OF_YEARS = 5
```

```powershell
uv run --python 3.10 --isolated --with-requirements requirements.lock src/main.py
```

Python 코드에서는 통합 함수를 직접 호출할 수 있습니다.

```python
from src.main import run_integrated_analysis

result = run_integrated_analysis(
    ["삼성전자", "SK하이닉스"],
    number_of_years=5,
    stock_period="1y",
    show_charts=False,
)

result.market_macro
result.quality_log
```

`stock_period`는 `1m`, `3m`, `6m`, `1y`, `3y`를 지원합니다.

## 3. 테스트와 의존성

```powershell
uv run --python 3.10 --isolated --with-requirements requirements.lock --with pytest -m pytest -q
```

외부 API는 가짜 응답으로 대체하므로 네트워크와 API 키 없이 테스트할 수 있습니다.

`requirements.txt`는 호환 가능한 버전 범위를, `requirements.lock`은 검증된 정확한
버전을 관리합니다. 의존성을 변경한 뒤 전체 테스트를 통과시키고 잠금 파일을 갱신합니다.

```powershell
uv pip compile --python-version 3.10 requirements.txt -o requirements.lock
```

## 4. 데이터 제공처별 처리

### Open DART

- 기업 기본정보, 상장 종목코드와 연간 재무제표를 사용합니다.
- 기업코드 캐시는 `.cache/corp_codes.json`에 저장하고 7일 후 갱신합니다.

### 공공데이터포털 금융위원회

- 일별 주식의 시가·고가·저가·종가·거래량·거래대금·시가총액을 사용합니다.
- KOSPI와 KOSDAQ 일별 지수 종가를 수집합니다.
- 데이터는 일 1회 적재되므로 최근 종가는 실시간 체결가가 아닙니다.

### 한국수출입은행

- 날짜별 `exchangeJSON` 응답에서 `cur_unit=USD`의 매매기준율을 사용합니다.
- 주말은 호출하지 않고 공휴일의 빈 응답은 값 없음으로 처리합니다.
- 평일 당일 값은 11시 이후 갱신되므로 캐시하지 않습니다.
- 과거 환율은 `.cache/exim_usd_krw.json`에 저장해 반복 호출을 줄입니다.
- 일일 호출 한도는 1,000건이므로 처음 3년 조회 시 약 780건 호출에 유의합니다.

### 한국은행 ECOS

- 통계표 `817Y002`의 국고채 3년 `010200000`을 사용합니다.
- 회사채 3년 AA- `010300000`을 함께 조회해 신용 스프레드를 계산합니다.
- 1,000행을 넘으면 페이지를 나눠 수집합니다.

### 투자자별 거래 동향

최근 최대 10거래일의 기관·개인·외국인·기타 매수 거래량 비중을 계산합니다. 거래량
차트의 빨강·파랑은 실제 매수·매도 분리가 아니라 시가 대비 종가 방향 표시입니다.

## 5. GPT 보조 분석

Python/Pandas가 계산한 KPI JSON만 전달하며 GPT가 원천 숫자를 다시 계산하지 않습니다.
응답의 근거 키와 수치를 검증하고 실패하면 최대 3회 재시도합니다. 사용할 수 없는 근거,
입력에 없는 숫자와 투자 권유 표현은 안전한 문장으로 교체합니다.

응답 저장은 비활성화합니다. GPT가 실패하거나 사용 한도를 초과해도 재무·시장 KPI,
CSV와 차트는 정상적으로 제공합니다.

## 6. 출력 구조

```text
output/
├── cli/
│   ├── financial_analysis.csv
│   ├── stock_prices.csv
│   ├── stock_summary.csv
│   ├── investor_summary.csv
│   ├── market_macro.csv
│   ├── data_quality_log.csv
│   ├── charts/
│   ├── stock_charts/
│   ├── kpi_analysis.json
│   └── gpt_insights.json
└── web_runs/
```

웹 분석은 실행별 UUID 폴더를 사용합니다. 완료 결과는 1시간 동안 보관하며 이후 새
분석이 완료될 때 정리합니다. 실행 중이거나 완료 표식이 없는 폴더는 삭제하지 않습니다.

## 7. 주요 소스 구조

```text
src/
├── app.py                    # Flask 요청과 결과 화면
├── main.py                   # 통합 분석 파이프라인
├── financial_analysis.py     # 계정 매칭, 업종 판별, 재무지표
├── stock_api.py              # 주식·시장지수 API
├── stock_analysis.py         # 주가 정제와 요약
├── macro_api.py              # 환율·금리 API
├── macro_analysis.py         # 거래일 병합과 변화량
├── data_quality.py           # 단위 보정과 이상치
├── kpi_analysis.py           # KPI 계약
├── stock_visualization.py    # 시장 시각화
├── correlation_insight.py    # 히트맵 종합 인사이트
└── gpt_analysis.py           # GPT 생성과 검증
```

## 8. 보안과 운영 로그

- `.env`, API 키, 캐시와 생성 결과는 Git 추적 대상에서 제외합니다.
- 서버는 기본적으로 `127.0.0.1`, `debug=False`로 실행합니다.
- 사용자 입력을 셸 명령으로 실행하지 않습니다.
- 실행 로그에는 API 키나 전체 KPI 대신 `run_id`, 단계, 기업 수, 경고 수와 처리시간을 기록합니다.
- 외부 서비스에는 해당 요청에 필요한 기업·종목·날짜와 인증키만 전송합니다.
- OpenAI 분석 시 기업명과 KPI JSON이 전송되지만 API 키는 요청 본문이나 로그에 남기지 않습니다.

인터넷 공개 배포 시에는 사용자 인증, 요청 제한, HTTPS, 운영용 WSGI 서버와 별도 결과
정리 정책이 추가로 필요합니다.
