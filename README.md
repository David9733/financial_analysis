# 📈 FINANCIAL LAB

> 기업의 재무 성과와 주가가 시장지수, 환율, 금리 및 신용 스프레드와 어떻게 움직였는지 일별 데이터로 분석합니다.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-Analysis-150458?style=flat&logo=pandas&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-Visualization-11557C?style=flat)
![Flask](https://img.shields.io/badge/Flask-Web%20App-000000?style=flat&logo=flask&logoColor=white)
![Open DART](https://img.shields.io/badge/Open%20DART-FSS-0B6BCB?style=flat)

기업명을 입력하면 재무제표와 일별 시장 데이터를 수집하고, 업종별 KPI, 주가 흐름, 투자자 거래량, 상관관계와 매크로 레이더를 한 화면에 보여 줍니다. 한 기업은 상세 분석으로, 두 기업 이상은 비교 분석으로 표시합니다.

## ✨ 주요 기능

- 기업을 한 번에 최대 10개까지 분석
- 최근 1년부터 10년까지 연간 재무제표 조회
- 1개월, 3개월, 6개월, 1년과 3년 주가 조회
- 일반기업, 금융업과 보험업을 구분한 재무 KPI
- KOSPI, KOSDAQ, 환율, 금리와 신용 스프레드 분석
- 기업 상관에서 시장 상관을 뺀 매크로 레이더
- 주가, 거래량, 투자자별 매수와 매도 비중 차트
- 결측 보간, 단위 오류 보정과 IQR 이상치 기록
- 원본 데이터 미리보기와 CSV 다운로드

## 🎬 시연

https://github.com/user-attachments/assets/fd538833-aba5-4605-85de-0af79b1dd0b6

## 🖥️ 화면 구성

결과 화면 상단에는 KOSPI, KOSDAQ, 원/달러 환율과 금리의 최신값 및 기업 스냅샷을 표시합니다.

| 탭 | 내용 |
|---|---|
| 재무 | 전체 재무 KPI와 연도별 재무 차트 |
| 주가 | 주가 KPI, 정규화 주가 비교, 이동평균, 볼린저 밴드, 거래량과 투자자 비중 |
| 매크로 | 시장 및 외부 요인, 매크로 레이더와 상관관계 차트 |
| 요약 | 상관관계 종합 인사이트, 데이터 미리보기와 CSV 다운로드 |

단일 기업에서는 KPI와 차트를 상세히 보여 주고, 다중 기업에서는 지표를 행, 기업을 열로 구성한 비교표와 첫 공통 거래일을 100으로 맞춘 주가 비교 차트를 제공합니다.

## 🗂️ 데이터 출처

| 영역 | 데이터 | 출처 |
|---|---|---|
| 재무 | 기업 정보와 연간 재무제표 | [Open DART](https://opendart.fss.or.kr/) |
| 주가 | 일별 OHLC, 거래량, 거래대금과 시가총액 | [공공데이터포털](https://www.data.go.kr/) 금융위원회 |
| 시장 | KOSPI와 KOSDAQ 일별 지수 종가 | 공공데이터포털 금융위원회 |
| 투자자 | 응답에 포함된 최근 거래일의 기관, 개인, 외국인과 기타 매수 및 매도 거래량 | 네이버 모바일 증권 비공식 공개 응답 |
| 환율 | 원/달러 매매기준율 | [한국수출입은행](https://www.koreaexim.go.kr/) |
| 금리 | 국고채 3년과 회사채 3년 AA- | [한국은행 ECOS](https://ecos.bok.or.kr/api/) |
| 신용 스프레드 | 회사채 3년 AA- 금리에서 국고채 3년 금리를 뺀 값 | 한국은행 ECOS 자료로 계산 |

투자자 데이터는 공식 네이버 API가 아닌 공개 응답 형식에 의존하므로 형식 변경 시 조회가 실패할 수 있습니다. 기업별 상관분석에는 해당 기업의 소속 시장지수만 사용합니다.

## 🔬 분석 기준

### 업종별 핵심 성과지표

| 구분 | 기업 스냅샷 KPI |
|---|---|
| 일반기업 | 매출 성장률, 영업이익률, ROE, 부채비율 |
| 금융업 | 순이자손익, 순수수료손익, ROE, ROA |
| 보험업 | 보험서비스수익 성장률, 보험서비스마진, ROE, 투자손익 |

연결재무제표를 우선 사용하고 없으면 별도재무제표를 사용합니다. 원천 계정이나 비교연도가 없으면 값을 추정하지 않고 사유를 표시합니다.

### 일별 변화량과 상관관계

상관분석에는 수준값이 아닌 일별 변화량을 사용합니다.

```text
주가와 시장지수  = 일간 수익률
원/달러 환율     = 일간 변화율
금리             = 일간 변화폭(bp)
신용 스프레드    = 일간 변화폭(bp)
```

히트맵은 위 변수의 Pearson 상관관계를 보여 줍니다. 유효 관측값이 10개 이상일 때 계산하며, 상관계수 절댓값 0.3 미만은 약함, 0.3 이상 0.7 미만은 중간, 0.7 이상은 강함으로 해석합니다.

### 매크로 레이더

```text
기업 상관       = corr(기업 일간수익률, 외부 요인 일간변화)
시장 상관       = corr(소속 시장지수 일간수익률, 외부 요인 일간변화)
시장 대비 차이  = 기업 상관 - 시장 상관
```

| 판정 | 기준 |
|---|---|
| 노출 약 | 시장 대비 차이 절댓값 0.15 미만 |
| 노출 중 | 0.15 이상, 0.30 미만 |
| 노출 강 | 0.30 이상 |
| 안정 | 부호 유지율 80% 이상 및 부호 전환율 5% 이하 |

이동상관 창은 1개월 10일, 3개월 20일, 6개월과 1년 및 3년은 60거래일입니다. 전체기간 기업 상관이 `-0.1`부터 `+0.1` 사이이면 `방향성 없음`으로 표시합니다. 1개월과 3개월 결과는 단기 참고값입니다.

상세 계산식, 결측 처리와 이상치 기준은 [분석 방법론](docs/analysis-methodology.md)에서 확인할 수 있습니다.

## 🚀 빠른 시작

### 1. 저장소와 API 키 준비

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

`DART_KEY`는 재무분석에 필요합니다. 주가와 매크로 분석에는 각 데이터 제공처의 키가 필요합니다. 현재 GPT 자동 인사이트는 비활성화되어 있어 `OPENAI_API_KEY` 없이 실행할 수 있습니다.

### 2. 설치와 실행

Python 3.10 이상을 사용합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe src/app.py
```

브라우저에서 `http://127.0.0.1:5000`을 엽니다.

`uv`를 사용하는 경우 다음 명령으로 바로 실행할 수 있습니다.

```powershell
uv run --python 3.10 --isolated --with-requirements requirements.lock src/app.py
```

### 3. 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

전체 123개 테스트는 외부 API를 가짜 응답으로 대체하므로 네트워크와 API 키 없이 실행할 수 있습니다.

## 📤 생성 결과

웹 결과는 `output/web_runs/<실행 ID>/`, CLI 결과는 `output/cli/`에 저장됩니다.

| 결과물 | 내용 |
|---|---|
| `financial_analysis.csv` | 업종별 연간 재무지표 |
| `stock_prices.csv`, `stock_summary.csv` | 일별 주가와 기간 요약 |
| `investor_summary.csv` | 투자자별 매수, 매도, 순매수 거래량과 비중 |
| `market_macro.csv` | 주가, 시장지수와 외부 요인의 수준값 및 변화량 |
| `data_quality_log.csv` | 보간, 단위 보정과 이상치 처리 내역 |
| `kpi_analysis.json` | 화면과 분석에 사용하는 KPI 스키마 1.4 |
| `charts/`, `stock_charts/` | 재무, 주가, 투자자와 매크로 차트 |

데이터가 없는 선택 결과물은 생성되지 않을 수 있습니다. 완료된 웹 결과는 1시간 동안 보관한 뒤 새 분석이 완료될 때 정리합니다.

## 🧱 주요 소스

| 파일 | 역할 |
|---|---|
| `src/app.py` | Flask 요청, 진행률, 결과 화면과 다운로드 |
| `src/main.py` | 재무, 주가와 매크로 통합 파이프라인 |
| `src/financial_analysis.py` | 계정 매칭, 업종 판별과 재무 KPI |
| `src/stock_analysis.py` | 주가 정제, 이동평균과 볼린저 밴드 |
| `src/macro_analysis.py` | 거래일 병합, 변화량, 보간과 이상치 |
| `src/kpi_analysis.py` | KPI 스키마와 매크로 레이더 |
| `src/stock_visualization.py` | 주가, 투자자와 매크로 차트 |

## ⚠️ 해석 시 주의사항

- 상관관계는 인과관계가 아닙니다.
- 매크로 레이더는 실제 영업 노출액이나 미래 주가를 의미하지 않습니다.
- 신용 스프레드는 시장 전체 지표이며 개별 기업의 실제 조달금리가 아닙니다.
- 업종지수를 사용하지 않아 시장 효과와 업종 효과를 완전히 분리하지 못합니다.
- 짧은 조회기간은 관측 수가 적어 일부 날짜에 민감합니다.
- 결과는 공개 데이터 탐색용이며 투자, 매수 또는 매도 권고가 아닙니다.

## 📚 문서와 기술 스택

- [분석 방법론](docs/analysis-methodology.md)
- [기술 및 운영 가이드](docs/technical-guide.md)

`Python`, `Pandas`, `Matplotlib`, `koreanize-matplotlib`, `Flask`, `Pydantic`과 `OpenAI API`
