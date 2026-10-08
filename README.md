# 📈 FINANCIAL LAB

> 기업의 재무 성과와 주가가 시장지수, 환율, 금리 및 신용 스프레드와 어떻게 움직였는지 일별 데이터로 검증합니다.

기업의 재무제표, 주가, 시장지수와 외부 요인을 한 화면에서 분석하고 여러 기업을 같은 기준으로 비교하는 Flask 기반 데이터 분석 프로젝트입니다.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-Analysis-150458?style=flat&logo=pandas&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-Visualization-11557C?style=flat)
![Flask](https://img.shields.io/badge/Flask-Web%20App-000000?style=flat&logo=flask&logoColor=white)
![Open DART](https://img.shields.io/badge/Open%20DART-FSS-0B6BCB?style=flat)

기업명을 입력하면 Open DART 재무제표와 일별 시장 데이터를 수집하고, 업종별 KPI, 주가 흐름, 투자자 거래량, 상관관계와 매크로 레이더를 생성합니다. 한 기업은 상세 분석 화면으로, 두 기업 이상은 지표와 차트를 바로 비교할 수 있는 화면으로 표시합니다.

## ✨ 주요 기능

- 기업을 한 번에 최대 10개까지 분석
- 최근 1년부터 10년까지 연간 재무제표 조회
- 1개월, 3개월, 6개월, 1년과 3년 주가 조회
- 일반기업, 금융업과 보험업을 구분한 재무 KPI 계산
- KOSPI와 KOSDAQ 시장 환경 및 기업별 비교 시장지수 연결
- 원/달러 환율, 국고채 3년 금리와 신용 스프레드 분석
- 기업 상관에서 시장 상관을 뺀 매크로 레이더 제공
- 주가, 거래량, 투자자별 매수와 매도 비중 차트 제공
- 결측 보간, 단위 오류 보정과 IQR 이상치 기록
- 결과 표의 첫 5행 미리보기와 CSV 다운로드 제공
- 실행별 진행률 표시와 결과 파일 분리 보관

## 🖥️ 화면 구성

### 검색 화면

- 기업명 입력 칸을 추가하거나 삭제할 수 있으며 최대 10개까지 입력할 수 있습니다.
- 재무제표 조회기간은 1년부터 10년까지 선택할 수 있습니다.
- 주가 조회기간은 1개월, 3개월, 6개월, 1년과 3년 중에서 선택합니다.
- 분석 중에는 재무, 주가, 매크로와 결과 정리 단계를 진행률로 표시합니다.

### 결과 화면

결과 화면 상단에는 다음 정보가 항상 표시됩니다.

- 시장 환경: KOSPI, KOSDAQ, 원/달러 환율과 금리의 최신 기준일, 최신값 및 선택기간 변화
- 기업 스냅샷: 기업명, 종목코드, 시장, 최신 종가, 시가총액, 기간수익률과 업종별 핵심 KPI
- 조회 실패, 결측 데이터와 보정 내역에 대한 경고

결과 본문은 네 개 탭으로 구성됩니다.

| 탭 | 내용 |
|---|---|
| 재무 | 전체 재무 KPI 표, 연도별 재무 차트 |
| 주가 | 주가 KPI, 정규화 주가 비교, 이동평균과 볼린저 밴드, 거래량, 투자자별 매수와 매도 비중 |
| 매크로 | 시장 및 외부 요인 표, 매크로 레이더, 외부 요인과 상관관계 차트 |
| 요약 | 상관관계 종합 인사이트, 원본 데이터 미리보기와 CSV 다운로드 |

한 기업을 조회하면 각 KPI가 한눈에 보이는 표와 기업별 상세 차트를 표시합니다. 두 기업 이상을 조회하면 지표를 행, 기업을 열로 구성한 비교표와 첫 공통 거래일을 100으로 맞춘 정규화 주가 차트를 표시합니다.

## 🗂️ 데이터 출처

| 영역 | 데이터 | 출처 |
|---|---|---|
| 재무 | 기업 정보와 연간 재무제표 | [Open DART](https://opendart.fss.or.kr/) |
| 주가 | 일별 시가, 고가, 저가, 종가, 거래량, 거래대금과 시가총액 | [공공데이터포털](https://www.data.go.kr/) 금융위원회 |
| 시장 | KOSPI와 KOSDAQ 일별 지수 종가 | [공공데이터포털](https://www.data.go.kr/) 금융위원회 |
| 투자자 | 최근 최대 10거래일의 기관, 개인, 외국인과 기타 매수 및 매도 거래량 | 네이버 모바일 증권 공개 응답 |
| 환율 | 원/달러 매매기준율 | [한국수출입은행](https://www.koreaexim.go.kr/) |
| 금리 | 국고채 3년과 회사채 3년 AA- | [한국은행 ECOS](https://ecos.bok.or.kr/api/) |
| 신용 스프레드 | 회사채 3년 AA- 금리에서 국고채 3년 금리를 뺀 값 | 한국은행 ECOS 자료로 계산 |

기업의 시장구분이 KOSPI이면 KOSPI, KOSDAQ이면 KOSDAQ을 비교 시장지수로 사용합니다. 화면 상단 시장 환경에는 두 지수를 모두 표시하지만 기업별 상관계산에는 해당 기업의 소속 시장지수만 사용합니다.

## 🔬 분석 방법

### 재무제표와 업종 구분

- 연결재무제표를 우선 사용하고 없으면 별도재무제표를 사용합니다.
- 표준 계정 ID를 우선하고 기업별 계정명을 보조적으로 사용합니다.
- 공시 계정 구성을 기준으로 일반기업, 금융업과 보험업을 판별합니다.
- 공시 연속성과 평균자본 및 평균자산 계산을 위해 화면 조회기간보다 직전 연도를 내부적으로 추가 조회합니다.
- 원천 계정, 비교연도 또는 유효한 분모가 없으면 값을 추정하지 않고 상태와 사유를 남깁니다.

| 구분 | 핵심 성과지표 | 추가 분석 지표 |
|---|---|---|
| 일반기업 | 매출 성장률, 영업이익률, ROE, 부채비율 | 순이익률, ROA, 이자보상배율, 매출채권 회전일수와 각종 성장률 |
| 금융업 | 순이자손익, 순수수료손익, ROE, ROA | 영업이익, 당기순이익, 자산과 이익 성장률 |
| 보험업 | 보험서비스수익 성장률, 보험서비스마진, ROE, 투자손익 | 보험서비스수익과 손익, ROA, 자산과 이익 성장률 |

```text
ROE                  = 당기순이익 ÷ 전년과 당년 평균자본 × 100
ROA                  = 당기순이익 ÷ 전년과 당년 평균자산 × 100
영업이익률           = 영업이익 ÷ 매출 × 100
부채비율             = 부채총계 ÷ 자본총계 × 100
이자보상배율         = 영업이익 ÷ 현금흐름표상 이자지급액
보험서비스마진       = 보험서비스손익 ÷ 보험서비스수익 × 100
매출채권 회전일수    = 기말 매출채권 ÷ 매출 × 365
```

### 주가 분석

- 기간수익률, 최고가, 최저가, 평균 거래량, 평균 거래대금과 시가총액을 계산합니다.
- 5일, 20일과 60일 단순이동평균을 계산합니다.
- 20일 이동평균과 표준편차 2배를 사용한 볼린저 밴드를 계산합니다.
- 두 기업 이상에서는 첫 공통 거래일 종가를 100으로 맞춰 주가 성과를 비교합니다.
- 최근 거래량 변화율은 최근 20거래일 평균과 직전 20거래일 평균을 비교합니다.
- 1개월 조회에서는 최근 거래량 변화율 계산에 필요한 시세만 이전 70일 범위에서 추가 수집하며, 화면과 CSV의 조회기간은 그대로 유지합니다.

거래량 차트의 `매수 우세`와 `매도 우세`는 실제 투자자 주문 방향이 아닙니다. 종가가 시가보다 높은 날과 낮은 날을 구분한 가격 방향 표시입니다. 실제 투자자별 매수와 매도 거래량 비중은 별도의 파이차트와 `investor_summary.csv`에서 확인합니다.

### 일별 변화량

수준값의 공통 추세로 인한 허위상관을 줄이기 위해 상관분석에는 일별 변화량을 사용합니다.

| 변수 | 분석값 | 계산식 |
|---|---|---|
| 기업 주가 | 일간 수익률 | `(오늘 종가 ÷ 전일 종가 - 1) × 100` |
| 시장지수 | 일간 수익률 | `(오늘 지수 ÷ 전일 지수 - 1) × 100` |
| 원/달러 환율 | 일간 변화율 | `(오늘 환율 ÷ 전일 환율 - 1) × 100` |
| 국고채 3년 금리 | 변화폭 | `(오늘 금리 - 전일 금리) × 100`, 단위 bp |
| 신용 스프레드 | 변화폭 | `오늘 스프레드 - 전일 스프레드`, 단위 bp |

기업별 주식 거래일을 기준으로 시장지수와 외부 요인을 왼쪽 결합합니다. 최대 10일 범위에서 직전 값을 사용해 제한적으로 보간하지만, 보간 당일과 영향을 받는 변화 구간은 상관계수와 이상치 계산에서 제외합니다.

### 상관관계 히트맵

히트맵은 기업 주가 수익률, 소속 시장지수 수익률, 환율 변화율, 금리 변화폭과 신용 스프레드 변화폭의 Pearson 상관관계를 보여 줍니다. 유효 관측값이 10개 이상일 때 계산하며 자기 자신과의 상관계수 1.00은 가립니다.

| 상관계수 절댓값 | 해석 |
|---:|---|
| `0.3 미만` | 약함 |
| `0.3 이상, 0.7 미만` | 중간 |
| `0.7 이상` | 강함 |

### 매크로 레이더

매크로 레이더는 환율, 금리와 신용 스프레드마다 시장과 구별되는 기업 고유의 과거 동행성과 그 안정성을 진단합니다.

```text
기업 상관       = corr(기업 일간수익률, 외부 요인 일간변화)
시장 상관       = corr(소속 시장지수 일간수익률, 외부 요인 일간변화)
시장 대비 차이  = 기업 상관 - 시장 상관
```

| 노출 판정 | 시장 대비 차이 절댓값 |
|---|---:|
| 약 | `0.15 미만` |
| 중 | `0.15 이상, 0.30 미만` |
| 강 | `0.30 이상` |

| 주가 조회기간 | 이동상관 창 |
|---|---:|
| 1개월 | 10거래일 |
| 3개월 | 20거래일 |
| 6개월, 1년과 3년 | 60거래일 |

- `-0.1`부터 `+0.1`까지의 이동상관은 중립으로 분류합니다.
- 부호 유지율은 전체기간 기업 상관과 같은 부호인 이동상관의 비율입니다.
- 부호 전환 횟수와 전환율은 중립 이동상관을 제외한 방향성 관측치로 계산합니다.
- 부호 유지율이 80% 이상이고 부호 전환율이 5% 이하이면 안정으로 판정합니다.
- 전체기간 기업 상관이 중립이면 부호 유지율과 안정성은 `방향성 없음`으로 표시하지만 부호 전환 횟수와 전환율은 계산합니다.
- 이동상관 관측치가 10개 미만이거나 방향성 관측치가 부족하면 안정성은 `비교기간 없음`으로 표시합니다.
- 1개월과 3개월 결과는 `단기 참고`이며, 6개월 이상에서 강하고 안정적인 경우에만 구조적 노출 후보로 해석합니다.

매크로 레이더는 실제 영업 노출액이나 인과관계를 측정하지 않습니다. 기업의 수출입 비중, 결제통화, 외화부채, 환헤지, 차입구조와 공시를 함께 확인해야 합니다.

### 데이터 품질

- 앞뒤 값과 비교해 10배, 100배 또는 1000배 차이가 난 뒤 원래 수준으로 돌아오는 값은 단위 오류 후보로 보정합니다.
- 하루 변화량이 `Q1 - 1.5 × IQR`보다 작거나 `Q3 + 1.5 × IQR`보다 크면 이상치로 표시합니다.
- 이상치는 삭제하지 않고 원인 확인 대상으로 유지합니다.
- 처리 대상, 기업명, 기준일, 원래값, 처리값과 사유는 `data_quality_log.csv`에 기록합니다.

## 🎬 시연

https://github.com/user-attachments/assets/fd538833-aba5-4605-85de-0af79b1dd0b6

## 🚀 빠른 시작

### 1. 저장소와 환경변수 준비

```powershell
git clone https://github.com/David9733/financial_analysis.git
cd financial_analysis
Copy-Item .env.example .env
```

```text
DART_KEY=your_open_dart_api_key
PUBLIC_STOCK_API_KEY=your_public_data_portal_api_key
KOREAEXIM_API_KEY=your_koreaexim_exchange_api_key
ECOS_API_KEY=your_bok_ecos_api_key
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

| 환경변수 | 필수 여부 | 용도 |
|---|---|---|
| `DART_KEY` | 필수 | 기업 검색과 연간 재무제표 |
| `PUBLIC_STOCK_API_KEY` | 주가 분석 시 필수 | 주식시세, KOSPI와 KOSDAQ 지수 |
| `KOREAEXIM_API_KEY` | 매크로 분석 시 필수 | 원/달러 환율 |
| `ECOS_API_KEY` | 매크로 분석 시 필수 | 국고채와 회사채 금리 |
| `OPENAI_API_KEY` | 현재 불필요 | GPT 자동 인사이트를 다시 활성화할 때 사용 |
| `OPENAI_MODEL` | 선택 | GPT 모델명, 기본값 `gpt-4o-mini` |

현재 `src/main.py`의 `ENABLE_GPT_INSIGHTS`가 `False`이므로 GPT 자동 인사이트는 생성하지 않습니다. 재무, 주가, 매크로 KPI와 규칙 기반 상관관계 인사이트는 정상적으로 생성됩니다.

### 2. 의존성 설치

Python 3.10 이상을 사용합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
```

### 3. 웹 실행

```powershell
.\.venv\Scripts\python.exe src/app.py
```

브라우저에서 `http://127.0.0.1:5000`을 엽니다. `uv`를 사용하면 다음 명령으로 바로 실행할 수 있습니다.

```powershell
uv run --python 3.10 --isolated --with-requirements requirements.lock src/app.py
```

### 4. 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

현재 전체 테스트는 123개입니다. 외부 API는 테스트에서 가짜 응답으로 대체하므로 네트워크와 API 키 없이 실행할 수 있습니다.

## 💻 CLI와 Python 사용

CLI 실행 전 `src/main.py` 상단의 기업명과 조회기간을 수정합니다.

```python
COMPANIES = ["삼성전자", "SK하이닉스"]
START_YEAR = None
END_YEAR = None
NUMBER_OF_YEARS = 5
```

```powershell
.\.venv\Scripts\python.exe src/main.py
```

Python 코드에서는 통합 분석 함수를 직접 호출할 수 있습니다.

```python
from src.main import run_integrated_analysis

result = run_integrated_analysis(
    ["삼성전자", "SK하이닉스"],
    number_of_years=5,
    stock_period="1y",
    show_charts=False,
)

print(result.financial)
print(result.stock_summary)
print(result.market_macro)
print(result.quality_log)
```

`stock_period`는 `1m`, `3m`, `6m`, `1y`와 `3y`를 지원합니다.

## 📤 생성 결과

웹 결과는 `output/web_runs/<실행 ID>/`, CLI 결과는 `output/cli/`에 저장됩니다.

```text
output/
├── cli/
└── web_runs/
    └── <실행 ID>/
        ├── financial_analysis.csv
        ├── stock_prices.csv
        ├── stock_summary.csv
        ├── investor_summary.csv
        ├── market_macro.csv
        ├── data_quality_log.csv
        ├── kpi_analysis.json
        ├── gpt_insights.json
        ├── charts/
        └── stock_charts/
```

| 결과물 | 내용 |
|---|---|
| `financial_analysis.csv` | 업종별 연간 재무지표 |
| `stock_prices.csv` | 선택기간의 일별 주가 원본과 정규화 주가 |
| `stock_summary.csv` | 최근 종가, 기간수익률, 거래량과 시가총액 요약 |
| `investor_summary.csv` | 투자자별 매수, 매도, 순매수 거래량과 비중 |
| `market_macro.csv` | 주가, 시장지수, 환율, 금리, 신용 스프레드와 일별 변화량 |
| `data_quality_log.csv` | 보간, 단위 오류 보정과 이상치 처리 내역 |
| `kpi_analysis.json` | 화면과 분석에 사용하는 KPI 스키마 1.4 |
| `gpt_insights.json` | GPT 기능을 활성화하고 결과가 있을 때 생성되는 보조 설명 |
| `charts/` | 재무 차트 |
| `stock_charts/` | 주가, 거래량, 투자자, 외부 요인, 이상치, 히트맵과 이동상관 차트 |

데이터가 없으면 `investor_summary.csv`, `data_quality_log.csv`와 `gpt_insights.json`은 생성되지 않을 수 있습니다. 웹 실행별 완료 결과는 1시간 동안 보관하며 이후 새 분석이 완료될 때 만료된 결과를 정리합니다. 진행 중이거나 완료 표식이 없는 폴더는 삭제하지 않습니다.

## 🧱 프로젝트 구조

```text
src/
├── app.py                    # Flask 요청, 진행률, 결과 화면과 다운로드
├── main.py                   # 재무, 주가와 매크로 통합 파이프라인
├── dart_api.py               # Open DART 기업 검색과 재무제표 수집
├── financial_analysis.py     # 계정 매칭, 업종 판별과 재무 KPI
├── stock_api.py              # 주가와 시장지수 API
├── stock_analysis.py         # 주가 정제, 이동평균, 볼린저 밴드와 요약
├── investor_analysis.py      # 투자자별 매수와 매도 거래량 집계
├── macro_api.py              # 환율과 금리 API
├── macro_analysis.py         # 거래일 병합, 변화량, 보간과 이상치
├── correlation_settings.py   # 조회기간별 이동상관 공통 설정
├── correlation_insight.py    # 규칙 기반 상관관계 종합 인사이트
├── kpi_analysis.py           # KPI 스키마와 매크로 레이더
├── visualization.py          # 재무 차트
├── stock_visualization.py    # 주가, 투자자와 매크로 차트
├── gpt_analysis.py           # GPT 응답 생성과 숫자 검증
└── analysis_prompt.py        # GPT 분석 지침

templates/
├── index.html                # 기업 검색 화면
└── result_dashboard.html     # 단일 및 다중 기업 결과 화면

tests/                        # unittest 기반 단위 및 통합 테스트
docs/                         # 분석 방법론과 기술 가이드
```

## ⚠️ 해석 시 주의사항

- 상관관계는 인과관계가 아닙니다.
- 매크로 레이더의 노출은 과거 수익률 동행성을 뜻하며 실제 매출, 비용, 자산 또는 부채 노출액이 아닙니다.
- 신용 스프레드는 시장 전반의 기업 신용위험 지표이며 개별 기업의 실제 조달금리가 아닙니다.
- 업종지수를 사용하지 않으므로 시장 효과와 업종 효과를 완전히 분리하지 못합니다.
- 1개월과 3개월 결과는 관측 수가 적어 일부 날짜에 민감합니다.
- 이상치는 오류로 단정하지 않으며 공시와 뉴스로 원인을 추가 확인해야 합니다.
- 공공데이터는 갱신 시차가 있으므로 최신값은 실시간 체결가가 아닐 수 있습니다.
- 결과는 공개 데이터 탐색용이며 투자, 매수, 매도 또는 인수 권고가 아닙니다.

## 📚 상세 문서

- [분석 방법론](docs/analysis-methodology.md): 계산식, 시계열 정렬, 결측과 이상치 및 상관분석 규칙
- [기술 및 운영 가이드](docs/technical-guide.md): API, CLI, 파일 구조, 보안과 운영 로그

## 🧰 기술 스택

`Python`, `Pandas`, `Matplotlib`, `koreanize-matplotlib`, `Flask`, `Pydantic`과 `OpenAI API`
