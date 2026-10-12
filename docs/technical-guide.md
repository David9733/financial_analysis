# 기술 및 운영 가이드

프로젝트 실행, API 동작, 출력 파일과 운영 관련 세부사항을 설명합니다. 분석 설계는
[분석 방법론](analysis-methodology.md)을 참고하세요.

## 1. API 키

프로젝트 루트의 `.env.example`을 `.env`로 복사하고 사용할 키를 입력합니다.

| 키 | 함께 인식하는 이름 | 서비스 | 용도 |
|---|---|---|---|
| `DART_KEY` | `DART_API_KEY` | [Open DART](https://opendart.fss.or.kr/) | 기업 검색과 재무제표 (필수) |
| `PUBLIC_STOCK_API_KEY` | `STOCK_API_KEY` | [공공데이터포털](https://www.data.go.kr/) | 주식시세, KOSPI/KOSDAQ 지수 |
| `KOREAEXIM_API_KEY` | `EXIM_API_KEY` | [한국수출입은행](https://www.koreaexim.go.kr/) | 원/달러 환율 |
| `ECOS_API_KEY` | - | [한국은행 ECOS](https://ecos.bok.or.kr/api/) | 국고채와 회사채 금리 |
| `OPENAI_API_KEY` | `GPT_KEY` | [OpenAI](https://platform.openai.com/api-keys) | KPI 기반 보조 인사이트 |

공공데이터포털에서는 금융위원회의 `주식시세정보`와 `지수시세정보` 두 서비스를 각각
활용 신청해야 합니다. 이미 설정된 시스템 환경 변수는 `.env` 값보다 우선합니다.

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

| 입력 | 허용 범위 |
|---|---|
| 기업 수 | 1개에서 10개 (쉼표, 세미콜론, 줄바꿈으로 구분하며 중복은 제거) |
| 재무제표 조회기간 | 최근 1년에서 10년 |
| 주가 조회기간 | `1m`, `3m`, `6m`, `1y`, `3y` |

| 경로 | 메서드 | 역할 |
|---|---|---|
| `/` | GET | 입력 화면 |
| `/analyze` | POST | 분석 실행 후 결과 화면 반환 |
| `/analysis-progress/<run_id>` | GET | 진행 단계와 진행률(JSON), 입력 화면이 주기적으로 조회 |
| `/results/<run_id>/<파일 경로>` | GET | 해당 실행의 CSV와 차트 파일 |

### CLI

`src/main.py` 상단의 기업명과 재무 조회기간을 수정합니다.

```python
COMPANIES = ["CJ프레시웨이", "롯데웰푸드"]
START_YEAR = None
END_YEAR = None
NUMBER_OF_YEARS = 5
```

```powershell
uv run --python 3.10 --isolated --with-requirements requirements.lock src/main.py
```

CLI의 주가 조회기간은 `1y`로 고정되어 있습니다. 다른 기간은 아래처럼 함수를 직접
호출할 때 `stock_period`로 지정합니다. `START_YEAR`와 `END_YEAR`를 지정하면
`NUMBER_OF_YEARS` 대신 해당 연도 범위를 조회합니다.

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

- 일별 주식의 시가, 고가, 저가, 종가, 거래량, 거래대금과 시가총액을 사용합니다.
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

최근 최대 10거래일의 기관, 개인, 외국인과 기타 매수 거래량 비중을 계산합니다. 거래량
차트의 빨강과 파랑은 실제 매수와 매도 분리가 아니라 시가 대비 종가 방향 표시입니다.

## 5. GPT 보조 분석

Python/Pandas가 계산한 KPI JSON만 전달하며 GPT가 원천 숫자를 다시 계산하지 않습니다.
응답의 근거 키와 수치를 검증하고, 검증에 실패하면 실패 사유를 덧붙여 다시 요청합니다.
첫 요청을 포함해 최대 3번까지 요청하며, 마지막 응답에서도 남은 사용할 수 없는 근거,
입력에 없는 숫자와 투자 권유 표현은 안전한 문장으로 교체합니다. 인증, 한도 초과나
네트워크 같은 API 오류는 다시 요청하지 않고 바로 KPI 기반 대체 인사이트로 전환합니다.

응답 저장은 비활성화합니다. GPT가 실패하거나 사용 한도를 초과해도 재무 및 시장 KPI,
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
├── dart_api.py               # DART 기업 검색, 기업코드 캐시, 재무제표 API
├── financial_analysis.py     # 계정 매칭, 업종 판별, 재무지표
├── visualization.py          # 재무 차트
├── stock_api.py              # 주식과 시장지수 API
├── stock_analysis.py         # 주가 정제와 요약
├── investor_analysis.py      # 투자자별 거래량 집계
├── macro_api.py              # 환율과 금리 API
├── macro_analysis.py         # 거래일 병합과 변화량
├── data_quality.py           # 단위 보정과 이상치
├── kpi_analysis.py           # KPI 계약, 매크로 레이더, 시나리오
├── correlation_settings.py   # 조회기간별 이동상관 창 설정
├── stock_visualization.py    # 시장 시각화
├── correlation_insight.py    # 히트맵 종합 인사이트
├── analysis_prompt.py        # GPT 분석 지침
└── gpt_analysis.py           # GPT 생성과 검증
```

## 8. 문제 해결

필수 데이터 오류는 입력 화면에 오류로 표시되고, 선택 데이터 오류는 결과 화면 상단의
경고로 표시되며 나머지 분석은 계속됩니다.

| 메시지 | 원인 | 조치 |
|---|---|---|
| `.env에 DART_KEY 또는 DART_API_KEY를 설정해 주세요` | DART 키 없음 | 프로젝트 루트에 `.env`를 만들고 `DART_KEY` 입력 |
| `입력한 기업명 '…'을(를) 찾을 수 없습니다. 비슷한 기업: …` | 오타 또는 비상장 법인명 | 제안된 기업명 중 하나로 다시 입력 |
| `기업명 '…' 검색 결과가 여러 개입니다: …` | 같은 이름의 법인이 여러 개 | 목록에 표시된 정확한 법인명 입력 |
| `분석 가능한 재무 데이터를 가져오지 못했습니다` | 해당 기간 사업보고서 없음 | 조회기간을 늘리거나 다른 기업 확인 |
| `DART API 오류: status=020` 등 | DART 키 오류 또는 호출 한도 | [DART 오류 코드](https://opendart.fss.or.kr/)와 키 상태 확인 |
| `…: 상장 종목코드가 없어 재무분석만 제공합니다` | 비상장 기업 | 정상 동작, 주가와 매크로 분석 없음 |
| `.env에 PUBLIC_STOCK_API_KEY를 설정해 주세요` | 주가 키 없음 | 키 입력 또는 재무분석만 사용 |
| `주식시세 API 오류: code=…` | 서비스 미승인 또는 키 오류 | 공공데이터포털에서 두 서비스 활용 승인 여부 확인 |
| `환율 API 일일 호출 한도(1,000건)를 초과했습니다` | 처음 3년 조회 등으로 호출이 많음 | 다음 날 다시 실행, 이미 받은 날짜는 캐시되어 재호출하지 않음 |
| `환율 API 인증키가 유효하지 않습니다` | 수출입은행 키 오류 | 키 확인 |
| `환율: N개 날짜 조회에 실패해 직전 값으로 채웠습니다` | 일부 날짜 일시 오류 | 다시 실행하면 실패한 날짜만 재호출 |
| `…: 투자자별 수급 조회 실패` | 비공식 응답 형식 변경 또는 네트워크 | 투자자 차트만 제외, 나머지는 정상 |
| `GPT 자동 분석을 불러오지 못했습니다` | OpenAI 키 없음, 한도 초과 또는 검증 실패 | KPI 기반 대체 인사이트가 표시되며 키와 사용량 확인 |

캐시가 손상되었거나 최신 기업 목록이 필요하면 `.cache/` 폴더를 삭제하고 다시
실행합니다. 기업코드는 다시 내려받고, 환율은 조회 기간만큼 다시 호출합니다.

## 9. 보안과 운영 로그

- `.env`, API 키, 캐시와 생성 결과는 Git 추적 대상에서 제외합니다.
- 서버는 기본적으로 `127.0.0.1`, `debug=False`로 실행합니다.
- 사용자 입력을 셸 명령으로 실행하지 않습니다.
- 실행 로그에는 API 키나 전체 KPI 대신 `run_id`, 단계, 기업 수, 경고 수와 처리시간을 기록합니다.
- 외부 서비스에는 해당 요청에 필요한 기업, 종목, 날짜와 인증키만 전송합니다.
- OpenAI 분석 시 기업명과 KPI JSON이 전송되지만 API 키는 요청 본문이나 로그에 남기지 않습니다.

인터넷 공개 배포 시에는 사용자 인증, 요청 제한, HTTPS, 운영용 WSGI 서버와 별도 결과
정리 정책이 추가로 필요합니다.
