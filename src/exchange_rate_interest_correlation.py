"""pandas의 corr()를 사용하여 환율과 금리의 상관관계를 분석하는 예제입니다."""

# 표 형태의 데이터를 처리하기 위해 pandas를 불러옵니다.
import pandas as pd


# 분석에 사용할 날짜 열의 이름을 상수로 정의합니다.
DATE_COLUMN = "날짜"
# 분석에 사용할 원/달러 환율 열의 이름을 상수로 정의합니다.
EXCHANGE_RATE_COLUMN = "원달러환율"
# 분석에 사용할 금리 열의 이름을 상수로 정의합니다.
INTEREST_RATE_COLUMN = "금리"


def analyze_correlation(
    data: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """환율·금리의 수준값 및 변화량 상관계수 행렬을 반환합니다.

    입력 데이터에는 ``날짜``, ``원달러환율``, ``금리`` 열이 있어야 합니다.
    금리는 3.25처럼 퍼센트(%) 단위의 숫자로 입력한다고 가정합니다.
    """

    # 반드시 필요한 열의 이름을 집합으로 만들어 입력 데이터의 구조를 검사합니다.
    required_columns = {DATE_COLUMN, EXCHANGE_RATE_COLUMN, INTEREST_RATE_COLUMN}
    # 필수 열 가운데 입력 데이터에 없는 열을 찾습니다.
    missing_columns = required_columns.difference(data.columns)
    # 누락된 필수 열이 있으면 어떤 열이 필요한지 알기 쉬운 오류로 안내합니다.
    if missing_columns:
        raise ValueError(f"필수 열이 없습니다: {', '.join(sorted(missing_columns))}")

    # 원본 DataFrame을 변경하지 않도록 분석에 필요한 세 열만 복사합니다.
    analysis_data = data[[DATE_COLUMN, EXCHANGE_RATE_COLUMN, INTEREST_RATE_COLUMN]].copy()

    # 날짜 문자열을 pandas의 날짜 자료형으로 바꾸며, 잘못된 값은 NaT로 처리합니다.
    analysis_data[DATE_COLUMN] = pd.to_datetime(
        analysis_data[DATE_COLUMN],
        errors="coerce",
    )

    # 쉼표가 포함된 환율 문자열도 숫자로 바꿀 수 있도록 쉼표를 제거합니다.
    analysis_data[EXCHANGE_RATE_COLUMN] = (
        analysis_data[EXCHANGE_RATE_COLUMN].astype(str).str.replace(",", "", regex=False)
    )
    # 환율 열을 숫자 자료형으로 바꾸며, 변환할 수 없는 값은 NaN으로 처리합니다.
    analysis_data[EXCHANGE_RATE_COLUMN] = pd.to_numeric(
        analysis_data[EXCHANGE_RATE_COLUMN],
        errors="coerce",
    )
    # 금리 열을 숫자 자료형으로 바꾸며, 변환할 수 없는 값은 NaN으로 처리합니다.
    analysis_data[INTEREST_RATE_COLUMN] = pd.to_numeric(
        analysis_data[INTEREST_RATE_COLUMN],
        errors="coerce",
    )

    # 날짜·환율·금리 중 하나라도 비어 있는 행은 정확한 비교를 위해 제외합니다.
    analysis_data = analysis_data.dropna(
        subset=[DATE_COLUMN, EXCHANGE_RATE_COLUMN, INTEREST_RATE_COLUMN]
    )
    # 날짜가 중복되면 가장 마지막에 입력된 행을 남깁니다.
    analysis_data = analysis_data.drop_duplicates(subset=DATE_COLUMN, keep="last")
    # 시계열 변화량을 올바르게 계산할 수 있도록 날짜 오름차순으로 정렬합니다.
    analysis_data = analysis_data.sort_values(DATE_COLUMN).reset_index(drop=True)

    # 상관계수를 계산하려면 유효한 관측값이 최소 2개 필요합니다.
    if len(analysis_data) < 2:
        raise ValueError("상관관계 분석에는 유효한 환율·금리 관측값이 2개 이상 필요합니다.")

    # 환율과 금리의 수준값만 선택한 뒤 Pearson 상관계수 행렬을 계산합니다.
    # method="pearson"은 선형 관계를 -1부터 1 사이의 값으로 나타냅니다.
    level_correlation = analysis_data[
        [EXCHANGE_RATE_COLUMN, INTEREST_RATE_COLUMN]
    ].corr(method="pearson")

    # 전일 대비 환율 변동률을 백분율(%) 단위로 계산합니다.
    analysis_data["환율변동률(%)"] = analysis_data[EXCHANGE_RATE_COLUMN].pct_change() * 100
    # 전일 대비 금리의 단순 차이를 퍼센트포인트(%p) 단위로 계산합니다.
    analysis_data["금리변화폭(%p)"] = analysis_data[INTEREST_RATE_COLUMN].diff()

    # 첫 행에는 이전 날짜가 없어 변화량이 NaN이므로 변화량이 있는 행만 선택합니다.
    change_data = analysis_data[["환율변동률(%)", "금리변화폭(%p)"]].dropna()
    # 변화량 표본이 2개 이상인지 확인하여 의미 없는 계산을 방지합니다.
    if len(change_data) < 2:
        raise ValueError("변화량 상관관계 분석에는 유효한 관측값이 3개 이상 필요합니다.")

    # 환율 변동률과 금리 변화폭의 Pearson 상관계수 행렬을 계산합니다.
    change_correlation = change_data.corr(method="pearson")

    # 정제된 원자료와 두 상관계수를 확인할 수 있도록 결과 열을 함께 유지합니다.
    return analysis_data, level_correlation, change_correlation


def explain_correlation(coefficient: float) -> str:
    """상관계수의 방향과 선형 관계의 강도를 간단한 한국어 문장으로 설명합니다."""

    # 한 변수가 일정하여 상관계수가 NaN이면 계산 불가 사유를 안내합니다.
    if pd.isna(coefficient):
        return "한 변수의 값이 일정하거나 표본이 부족하여 상관계수를 계산할 수 없습니다."

    # 상관계수를 절댓값으로 바꾸어 관계의 강도를 판단합니다.
    strength_value = abs(coefficient)
    # 절댓값이 0.7 이상이면 강한 선형 관계로 분류합니다.
    if strength_value >= 0.7:
        strength = "강한"
    # 절댓값이 0.4 이상 0.7 미만이면 중간 정도의 선형 관계로 분류합니다.
    elif strength_value >= 0.4:
        strength = "중간 정도의"
    # 절댓값이 0.4 미만이면 약한 선형 관계로 분류합니다.
    else:
        strength = "약한"

    # 양수는 두 변수가 같은 방향으로 움직이는 경향을 뜻합니다.
    if coefficient > 0:
        direction = "양(+)의"
    # 음수는 두 변수가 반대 방향으로 움직이는 경향을 뜻합니다.
    elif coefficient < 0:
        direction = "음(-)의"
    # 정확히 0이면 선형 관계가 없다고 표현합니다.
    else:
        return "선형 상관관계가 없습니다."

    # 판단한 강도와 방향을 하나의 설명 문장으로 합쳐 반환합니다.
    return f"{strength} {direction} 선형 상관관계가 있습니다."


if __name__ == "__main__":
    # 별도 파일 없이도 코드를 실행해 볼 수 있도록 예제 데이터를 만듭니다.
    sample_data = pd.DataFrame(
        {
            # 각 관측값의 날짜를 입력합니다.
            DATE_COLUMN: [
                "2026-01-02",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-09",
            ],
            # 같은 날짜의 원/달러 환율을 입력합니다.
            EXCHANGE_RATE_COLUMN: [1468.4, 1471.2, 1465.8, 1478.1, 1474.3, 1482.5],
            # 같은 날짜의 금리(예: 국고채 3년물)를 % 단위로 입력합니다.
            INTEREST_RATE_COLUMN: [2.82, 2.84, 2.83, 2.87, 2.86, 2.90],
        }
    )

    # 위에서 만든 함수에 예제 데이터를 전달하여 분석 결과를 받습니다.
    cleaned_data, level_corr, change_corr = analyze_correlation(sample_data)

    # 정제된 데이터와 계산된 변화량을 출력합니다.
    print("[분석 데이터]")
    print(cleaned_data.to_string(index=False))

    # 환율·금리 수준값의 전체 상관계수 행렬을 출력합니다.
    print("\n[환율·금리 수준값 상관계수 행렬]")
    print(level_corr.round(4))

    # 두 열이 만나는 위치에서 수준값 상관계수 하나를 가져옵니다.
    level_coefficient = level_corr.loc[EXCHANGE_RATE_COLUMN, INTEREST_RATE_COLUMN]
    # 수준값 상관계수와 해석 문장을 출력합니다.
    print(f"상관계수: {level_coefficient:.4f}")
    print(f"해석: {explain_correlation(level_coefficient)}")

    # 환율 변동률·금리 변화폭의 전체 상관계수 행렬을 출력합니다.
    print("\n[환율 변동률·금리 변화폭 상관계수 행렬]")
    print(change_corr.round(4))

    # 두 변화량 열이 만나는 위치에서 변화량 상관계수 하나를 가져옵니다.
    change_coefficient = change_corr.loc["환율변동률(%)", "금리변화폭(%p)"]
    # 변화량 상관계수와 해석 문장을 출력합니다.
    print(f"상관계수: {change_coefficient:.4f}")
    print(f"해석: {explain_correlation(change_coefficient)}")

    # 실제 CSV 파일을 사용할 때는 아래 두 줄의 주석을 해제하면 됩니다.
    # csv_data = pd.read_csv("exchange_rate_interest_rate.csv", encoding="utf-8-sig")
    # cleaned_data, level_corr, change_corr = analyze_correlation(csv_data)
