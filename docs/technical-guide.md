# 기술 및 운영 가이드

프로젝트 실행, API 동작, 출력 파일과 운영 관련 세부사항을 설명합니다. 분석 설계는
[분석 방법론](analysis-methodology.md)을 참고하세요.

## 1. API 키

프로젝트 루트의 `.env.example`을 `.env`로 복사하고 사용할 키를 입력합니다.

| 키 | 함께 인식하는 이름 | 서비스 | 용도 |
|---|---|---|---|
| `DART_KEY` | `DART_API_KEY` | [Open DART](https://opendart.fss.or.kr/) | 기업 검색과 재무제표 (필수) |
| `PUBLIC_STOCK_API_KEY` | `STOCK_API_KEY` | [공공데이터포털](https://www.data.go.kr/) | 주식시세, KOSPI/KOSDAQ 지수 |
| `ECOS_API_KEY` | - | [한국은행 ECOS](https://ecos.bok.or.kr/api/) | 원/달러 환율, 국고채와 회사채 금리 |
| `OPENAI_API_KEY` | `GPT_KEY` | [OpenAI](https://platform.openai.com/api-keys) | KPI 기반 보조 인사이트 |

공공데이터포털에서는 금융위원회의 `주식시세정보`와 `지수시세정보` 두 서비스를 각각
활용 신청해야 합니다. 이미 설정된 시스템 환경 변수는 `.env` 값보다 우선합니다.

```text
DART_KEY=발급받은_Open_DART_API_키
PUBLIC_STOCK_API_KEY=공공데이터포털_서비스키
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
| `/gpt-analysis/<run_id>` | GET, POST | GET은 백그라운드 GPT 분석 상태와 완성된 요약 화면 조각 반환, POST는 Vercel에서 브라우저가 보낸 KPI로 GPT 분석 실행 |
| `/results/<run_id>/<파일 경로>` | GET | 해당 실행의 CSV와 차트 파일 |

입력한 기업명은 재무 수집을 시작하기 전에 모두 검증합니다. 정확한 이름과 하나로 확정되는
부분 이름만 자동 선택하며, 오타 유사도만으로 다른 법인을 자동 선택하지 않습니다. 잘못된
이름이 여러 개이면 `기업명을 확인해 주세요` 안내 아래에 입력별 후보를 한 번에 표시합니다.
분석을 다시 제출하면 이전 오류를 숨기고 진행률 화면을 즉시 표시하며, 제출 중에는 기업 추가,
삭제와 조회기간 변경을 잠급니다.

### Vercel 배포

배포 사이트는 `vercel.json`으로 `src/app.py`를 서버리스 함수로 실행하며 요청당 최대 실행 시간은
300초입니다. 환경 변수 `VERCEL`이 있으면 다음처럼 동작합니다.

| 항목 | 로컬 실행 | Vercel |
|---|---|---|
| 결과 저장 위치 | 프로젝트 루트의 `output/` | `/tmp/financial_analysis/output/` |
| 차트 전달 | `/results/<run_id>/…` 파일 경로 | HTML에 이미지 직접 삽입. 차트 합계가 2.2MB를 넘으면 너비 1,200px, 품질 78의 WebP로 압축 |
| GPT 분석 | 서버 백그라운드 스레드에서 실행하고 브라우저가 상태를 조회 | 브라우저가 압축된 KPI JSON을 `/gpt-analysis/<run_id>`에 POST해 한 요청 안에서 실행 |

서버리스 인스턴스는 메모리와 임시 파일을 요청 사이에 공유하지 않으므로 GPT 분석에 필요한 KPI를
zlib과 base64로 압축해 화면에 담아 둡니다. 압축 데이터는 1MB, 압축 해제 후 데이터는 4MB를 넘으면
거부합니다. 결과 저장 위치는 `FINANCIAL_ANALYSIS_RUNTIME_DIR` 환경 변수로 직접 지정할 수도 있습니다.

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
- 기업코드 캐시는 `.cache/corp_codes.json`에 저장하고 7일 후 갱신합니다. 캐시가 없으면 저장소에
  포함된 `data/corp_codes.zip`을 먼저 사용하고, 그것도 읽을 수 없을 때만 DART에서 내려받습니다.
- 화면 조회기간과 별도로 최근 3개 연속 사업연도 추세 계산에 필요한 사업보고서를 최대 4개
  확보합니다.
- 금융업과 보험업의 과거 연도 단독 응답이 없으면 최신 사업보고서의 `frmtrm_amount`와
  `bfefrmtrm_amount` 비교금액으로 누락 연도와 계정만 복원하며 직접 조회값을 우선합니다.

### 공공데이터포털 금융위원회

- 일별 주식의 시가, 고가, 저가, 종가, 거래량, 거래대금과 시가총액을 사용합니다.
- KOSPI와 KOSDAQ 일별 지수 종가를 수집합니다.
- 데이터는 일 1회 적재되므로 최근 종가는 실시간 체결가가 아닙니다.

### 한국은행 ECOS

- 통계표 `731Y001`의 원/미국달러 매매기준율 `0000001`을 사용합니다.
- 통계표 `817Y002`의 국고채 3년 `010200000`을 사용합니다.
- 회사채 3년 AA- `010300000`을 함께 조회해 신용 스프레드를 계산합니다.
- 환율과 금리는 조회 시작일과 종료일을 한 번에 전달하며, 1,000행을 넘으면 페이지를 나눠 수집합니다.

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

웹에서는 재무, 주가와 매크로 분석을 먼저 완료해 재무 탭을 표시하고 GPT 분석은 별도
스레드에서 실행합니다. 브라우저는 `/gpt-analysis/<run_id>`를 주기적으로 조회해 완성된
내용만 요약 탭에 넣습니다. GPT 요청은 최대 10초 동안 기다리며 시간 초과, 인증 오류,
검증 실패나 API 오류가 발생하면 계산된 KPI 기반 분석을 표시합니다. 웹에서는 10초 제한 때문에
GPT에 한 번만 요청하고, 검증에 실패한 문장은 다시 요청하지 않고 KPI 기반 문장으로 교체합니다.
최대 3번 요청은 CLI에 적용되며, CLI는 기존처럼 `include_gpt` 설정에 따라 통합 실행할 수 있습니다.

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
├── star_score.py             # 업종별 5축 스타 점수
├── correlation_settings.py   # 조회기간별 이동상관 창 설정
├── stock_visualization.py    # 시장 시각화
├── correlation_insight.py    # 히트맵 종합 인사이트
├── analysis_prompt.py        # GPT 분석 지침
├── gpt_analysis.py           # GPT 생성과 검증
└── exchange_rate_interest_correlation.py  # 환율과 금리 상관 단독 예제 (파이프라인에서 사용하지 않음)

templates/
├── index.html                # 입력 화면과 진행률
├── result_dashboard.html     # 결과 화면 (재무, 주가, 매크로, 요약 탭)
├── _gpt_analysis.html        # GPT 분석 화면 조각
├── _chat_widget.html         # Chatling 안내 챗봇
└── _favicon.html             # 파비콘
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
| `.env에 ECOS_API_KEY를 설정해 주세요` | 환율과 금리 키 없음 | 한국은행 ECOS 키 입력 또는 해당 지표 없이 분석 |
| `원/달러 환율 API 결과가 비어 있습니다` | 기간에 환율 통계가 없거나 ECOS 응답이 비어 있음 | 조회기간과 ECOS 서비스 상태 확인 |
| `…: 투자자별 수급 조회 실패` | 비공식 응답 형식 변경 또는 네트워크 | 투자자 차트만 제외, 나머지는 정상 |
| `GPT 자동 분석을 불러오지 못했습니다` | OpenAI 키 없음, 한도 초과 또는 검증 실패 | KPI 기반 대체 인사이트가 표시되며 키와 사용량 확인 |

개발 중 HTML을 바꾼 뒤 이전 화면이 남는 문제를 줄이기 위해 Flask 템플릿 자동 재로딩을
활성화했습니다. 이미 브라우저에 열린 문서는 `Ctrl+F5`로 새로고침해야 최신 스크립트와
스타일이 적용됩니다.

캐시가 손상되었거나 최신 기업 목록이 필요하면 `.cache/` 폴더를 삭제하고 다시
실행합니다. 기업코드는 다시 내려받으며, 환율과 금리는 ECOS 기간 조회로 다시 수집합니다.

## 9. 보안과 운영 로그

- `.env`, API 키, 캐시와 생성 결과는 Git 추적 대상에서 제외합니다.
- 서버는 기본적으로 `127.0.0.1`, `debug=False`로 실행합니다.
- 사용자 입력을 셸 명령으로 실행하지 않습니다.
- 실행 로그에는 API 키나 전체 KPI 대신 `run_id`, 단계, 기업 수, 경고 수와 처리시간을 기록합니다.
- 외부 서비스에는 해당 요청에 필요한 기업, 종목, 날짜와 인증키만 전송합니다.
- OpenAI 분석 시 기업명과 KPI JSON이 전송되지만 API 키는 요청 본문이나 로그에 남기지 않습니다.
- 입력 화면과 결과 화면은 Chatling 챗봇 스크립트(`templates/_chat_widget.html`)를 불러옵니다.
  사용자가 챗봇에 입력한 내용은 Chatling 서버로 전송되며, 분석 결과와 API 키는 챗봇에 전달하지
  않습니다. 챗봇은 대화 ID를 브라우저 쿠키에 최대 30일 보관합니다.

현재 Vercel 배포 사이트에는 사용자 인증과 요청 제한이 없습니다. 이용자가 늘어나면 외부 API 호출
한도를 지키기 위해 요청 제한과 사용자 인증을 추가해야 합니다.
