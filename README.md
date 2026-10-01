# 📈 DART 기업 재무분석
> **기업명만 입력하면 Open DART 재무제표를 수집하고, 핵심 지표·비교표·차트를 자동 생성하는 웹 애플리케이션**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Web%20App-000000?style=flat&logo=flask&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-Analysis-150458?style=flat&logo=pandas&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-Visualization-11557C?style=flat)
![Open DART](https://img.shields.io/badge/Open%20DART-FSS-0B6BCB?style=flat)
![OS](https://img.shields.io/badge/OS-Windows-0078D6?style=flat&logo=windows&logoColor=white)

기업의 재무제표를 직접 내려받아 계정명을 찾고 계산식을 적용하는 반복 작업을 줄이기 위해 만든 프로젝트입니다. <br>기업명을 한 개 또는 여러 개 입력하면 **일반기업, 금융업, 보험업을 자동 구분**하고, 업종에 맞는 재무지표와 차트를 보여줍니다.

---

## 🎯 프로젝트 기획 의도

*"기업마다 계정명이 다르고 업종별로 봐야 하는 지표도 다른데, 필요한 숫자를 매번 직접 찾고 계산하는 과정이 번거로웠습니다."*

이 프로젝트는 다음 흐름을 자동화하는 것을 목표로 합니다.

> **기업 검색 → DART 공시 수집 → 계정 매칭 → 업종 판별 → 재무지표 계산 → 표, 차트 생성**

- 기업명을 정확히 기억하지 못해도 유사한 상장사를 검색합니다.
- 연결재무제표를 우선 사용하고, 없으면 별도재무제표를 조회합니다.
- 업종에 적용되지 않는 지표는 억지로 계산하지 않습니다.
- 값이 없는 이유를 빈칸 대신 명확한 문구로 표시합니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|---|---|
| 🔎 유사 기업명 검색 | 공백·법인표기·부분 이름·일부 오타·영문 브랜드의 한글 발음을 보정합니다. |
| ➕ 복수 기업 입력 | `+`와 `−` 버튼으로 최대 10개 기업을 추가하거나 삭제할 수 있습니다. |
| 🏢 업종 자동 판별 | 계정 구성을 기준으로 일반기업·금융업·보험업을 구분합니다. |
| 📊 자동 지표 계산 | 매출, 이익, 자산, ROE, 성장률 등 업종별 핵심 지표를 계산합니다. |
| 📈 차트 생성 | 한 기업은 연도별 추세, 여러 기업은 최근 공통 연도 비교 차트를 만듭니다. |
| 🧹 맞춤형 상세표 | 조회 기업 모두에 적용되지 않는 지표 열은 웹 상세표에서 자동으로 숨깁니다. |
| 📥 CSV 다운로드 | 계산 결과 전체를 Excel에서 열 수 있는 UTF-8 BOM CSV로 제공합니다. |

### 기업명 검색 예시

```text
SK하이닉스       → SK하이닉스
에스케이하이닉스 → SK하이닉스
에스케이하닉스   → SK하이닉스
현대그린         → 현대그린푸드
삼성전짜         → 삼성전자
엘지화확         → LG화학
```

유사도가 충분히 높으면 자동 선택합니다. 비슷한 후보가 여러 개라면 임의로 결정하지 않고 후보 목록을 안내합니다.

---

## 🛠️ 분석 과정 (Workflow)

```mermaid
graph LR
    A["1. 기업명 입력"] --> B["2. DART 기업 검색"]
    B --> C["3. 연간 재무제표 수집"]
    C --> D["4. 계정 매칭·업종 판별"]
    D --> E["5. 재무지표 계산"]
    E --> F["6. 표·CSV·차트 생성"]
```

1. 입력된 이름을 정규화하고 Open DART 기업 고유번호 목록에서 회사를 찾습니다.
2. 최근 사업보고서의 연결재무제표(CFS)를 우선 조회합니다.
3. 표준 계정 ID를 우선 사용하고 기업별 계정명은 보조 규칙으로 매칭합니다.
4. 기업 전체 연도의 계정 구성을 바탕으로 분석 업종을 결정합니다.
5. Pandas로 비율·성장률을 계산하고 Matplotlib으로 PNG 차트를 생성합니다.

---

## 🧮 계산 지표

### 공통 지표

- 영업이익, 당기순이익, 총자산, 부채총계, 자본총계
- ROE, 총자산 성장률, 영업이익 성장률, 당기순이익 성장률

### 일반기업

- 매출, 영업이익률, 부채비율, 이자보상배율
- 매출 성장률, 매출채권 회전일수

### 금융업

- 순이자손익, 순수수료손익
- 분리 공시 기업은 이자·수수료 수익에서 비용을 차감해 순액 계산

### 보험업

- 보험서비스수익, 보험서비스손익, 투자손익
- 보험서비스마진, 보험서비스수익 성장률

### 주요 계산식

```text
ROE                = 당기순이익 ÷ 평균자본 × 100
영업이익률          = 영업이익 ÷ 매출 × 100
보험서비스마진      = 보험서비스손익 ÷ 보험서비스수익 × 100
매출채권 회전일수   = 기말 매출채권 ÷ 매출 × 365
```

원천 데이터가 없거나 분모가 0이면 임의의 숫자를 만들지 않습니다. CSV에는 `해당 없음(업종)`, `비교연도 없음`, `원천 데이터 없음`처럼 이유를 표시합니다.

---

## 🚀 빠른 시작 (Quick Start)

### 1. 저장소 내려받기

```powershell
git clone https://github.com/David9733/financial_analysis.git
cd financial_analysis
```

### 2. Open DART API 키 설정

[Open DART](https://opendart.fss.or.kr/)에서 API 키를 발급받은 뒤 프로젝트 루트에 `.env` 파일을 생성합니다.

```text
DART_KEY=발급받은_API_키
```

### 3. 웹 애플리케이션 실행

이 프로젝트는 uv 관리 Python에서도 시스템 패키지를 변경하지 않고 실행할 수 있습니다.

```powershell
uv run --isolated --with-requirements requirements.txt app.py
```

기본 설정으로 실행하면 브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:5000
```

호스트나 포트 설정을 변경했다면 터미널에 표시된 실제 접속 주소를 사용합니다.

> uv 관리 Python에서는 `python -m pip install`이 PEP 668 정책으로 차단될 수 있습니다. `--break-system-packages`로 우회하지 않고 위의 `uv run` 방식을 권장합니다.

---

## 🖥️ CLI로 실행하기

`main.py` 상단의 기업명과 기간을 수정합니다.

```python
COMPANIES = ["삼성전자"]
# 또는
COMPANIES = ["삼성전자", "SK하이닉스", "LG전자"]

START_YEAR = None
END_YEAR = None
NUMBER_OF_YEARS = 5
```

실행 명령:

```powershell
uv run --isolated --with-requirements requirements.txt main.py
```

다른 Python 코드에서도 호출할 수 있습니다.

```python
from main import run_analysis

result = run_analysis(
    ["삼성전자", "SK하이닉스"],
    number_of_years=5,
    show_charts=False,
)
```

---

## 📂 파일 구조

```text
financial_analysis/
├── app.py                  # Flask 웹 애플리케이션과 요청 처리
├── main.py                 # 전체 분석 파이프라인 실행
├── dart_api.py             # Open DART 통신과 유사 기업명 검색
├── financial_analysis.py   # 계정 선택·업종 판별·재무지표 계산
├── visualization.py        # 단일 기업 추세·복수 기업 비교 차트
├── templates/
│   ├── index.html          # 기업 입력 화면
│   └── result.html         # 결과 차트·상세표 화면
├── static/
│   └── style.css           # 반응형 웹 스타일
├── requirements.txt        # Python 의존성
├── .gitignore              # 키·캐시·생성 결과 제외
└── README.md               # 프로젝트 설명
```

---

## 📤 생성 결과

```text
output/
├── financial_analysis.csv  # CLI 분석 결과
├── charts/                 # CLI PNG 차트
└── web_runs/               # 웹 요청별 CSV·차트
```

- 한 기업 조회: 연도별 추세 차트
- 두 기업 이상 조회: 가장 최근 공통 연도의 기업 비교 차트
- 웹 결과: 차트 갤러리, 업종 맞춤 상세표, CSV 다운로드

---

## 🔒 보안 및 데이터 처리

- `.env`와 DART API 키는 Git 추적 대상에서 제외됩니다.
- 웹 서버는 기본적으로 `127.0.0.1`에만 열리며 `debug=False`로 실행됩니다.
- 사용자 입력을 셸 명령으로 실행하지 않습니다.
- 생성된 CSV와 차트는 로컬 `output/` 폴더에 저장되며 GitHub에 업로드되지 않습니다.
- 기업 검색과 재무제표 수집을 위해 입력한 기업명과 API 키가 **Open DART 서버로 전송**됩니다.

> 현재 구성은 개인 PC의 로컬 사용을 기준으로 합니다. 인터넷에 공개 배포하려면 사용자 인증, 요청 제한, HTTPS, 운영용 WSGI 서버와 결과 파일 정리 정책을 추가해야 합니다.

---

## ⚠️ 참고 사항

- Open DART에서 제공하지 않는 연도나 계정은 분석 결과에도 표시할 수 없습니다.
- 기업별 사용자 정의 계정명 때문에 일부 지표가 `원천 데이터 없음`으로 표시될 수 있습니다.
- 유사 검색은 잘못된 기업 선택을 막기 위해 확신도가 낮을 때 자동 선택하지 않습니다.
- 재무지표는 투자 권유가 아닌 공시 데이터 탐색과 비교를 위한 참고 자료입니다.
