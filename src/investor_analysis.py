"""공개 투자자 동향을 화면용 네 개 그룹으로 집계한다."""

from __future__ import annotations

from datetime import date
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


INVESTOR_COLUMNS = [
    "기업명",
    "종목코드",
    "투자자구분",
    "매도거래량",
    "매수거래량",
    "순매수거래량",
    "매수비중",
    "매도비중",
]

INSTITUTION_LABELS = {
    "금융투자",
    "보험",
    "투신",
    "사모",
    "은행",
    "기타금융",
    "연기금",
    "연기금 등",
}

TREND_URL = "https://m.stock.naver.com/front-api/stock/domestic/trend"


class InvestorDataError(RuntimeError):
    """투자자별 거래실적을 가져오거나 해석할 수 없을 때 발생한다."""


def empty_investor_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=INVESTOR_COLUMNS)


def summarize_investor_trading(
    raw: pd.DataFrame, company_name: str, stock_code: str
) -> pd.DataFrame:
    """KRX 투자자 분류를 기관·개인·외국인·기타 네 그룹으로 합친다."""
    if raw.empty:
        return empty_investor_summary()

    data = raw.copy()
    data.index = data.index.map(lambda value: str(value).strip())
    column_aliases = {
        "매도": "매도거래량",
        "매도거래량": "매도거래량",
        "매수": "매수거래량",
        "매수거래량": "매수거래량",
        "순매수": "순매수거래량",
        "순매수거래량": "순매수거래량",
    }
    data = data.rename(columns=column_aliases)
    required = ["매도거래량", "매수거래량", "순매수거래량"]
    if any(column not in data.columns for column in required):
        raise InvestorDataError("KRX 투자자별 거래실적의 응답 형식이 예상과 다릅니다.")
    for column in required:
        data[column] = pd.to_numeric(
            data[column].astype(str).str.replace(",", "", regex=False), errors="coerce"
        ).fillna(0)

    def totals(labels: set[str]) -> pd.Series:
        matching = data.loc[data.index.intersection(labels), required]
        return matching.sum() if not matching.empty else pd.Series(0, index=required)

    institution = (
        data.loc["기관합계", required]
        if "기관합계" in data.index
        else totals(INSTITUTION_LABELS)
    )
    grouped = {
        "기관": institution,
        "개인": totals({"개인"}),
        "외국인": totals({"외국인"}),
        "기타": totals({"기타법인", "기타외국인"}),
    }
    total_buys = sum(max(float(values["매수거래량"]), 0) for values in grouped.values())
    total_sells = sum(max(float(values["매도거래량"]), 0) for values in grouped.values())
    rows = []
    for label, values in grouped.items():
        buy_volume = float(values["매수거래량"])
        sell_volume = float(values["매도거래량"])
        rows.append(
            {
                "기업명": company_name,
                "종목코드": stock_code,
                "투자자구분": label,
                "매도거래량": sell_volume,
                "매수거래량": buy_volume,
                "순매수거래량": float(values["순매수거래량"]),
                "매수비중": buy_volume / total_buys * 100 if total_buys else 0.0,
                "매도비중": sell_volume / total_sells * 100 if total_sells else 0.0,
            }
        )
    return pd.DataFrame(rows, columns=INVESTOR_COLUMNS)


def get_investor_trading(
    company_name: str, stock_code: str, start_date: date, end_date: date
) -> pd.DataFrame:
    """공개 종목 동향에서 최근 최대 10거래일의 투자자별 거래량을 조회한다."""
    request = Request(
        f"{TREND_URL}?{urlencode({'code': stock_code})}",
        headers={
            "User-Agent": "dart-financial-analysis/2.0",
            "Referer": f"https://m.stock.naver.com/domestic/stock/{stock_code}/total",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvestorDataError(f"투자자 동향 조회 실패: {error}") from error

    if not payload.get("isSuccess"):
        raise InvestorDataError(payload.get("message") or "투자자 동향 응답 오류")
    items = (payload.get("result") or {}).get("items") or []
    selected = []
    for item in items:
        try:
            traded_at = date.fromisoformat(str(item.get("localTradedAt", "")))
        except ValueError:
            continue
        if start_date <= traded_at <= end_date and isinstance(item.get("krx"), dict):
            selected.append(item["krx"])
    if not selected:
        return empty_investor_summary()

    fields = {
        "기관": ("organizationBuyVolume", "organizationSellVolume"),
        "개인": ("individualBuyVolume", "individualSellVolume"),
        "외국인": ("foreignBuyVolume", "foreignSellVolume"),
    }

    def number(value: object) -> float:
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    grouped: dict[str, tuple[float, float]] = {}
    for label, (buy_field, sell_field) in fields.items():
        grouped[label] = (
            sum(number(item.get(buy_field)) for item in selected),
            sum(number(item.get(sell_field)) for item in selected),
        )
    total_volume = sum(number(item.get("tradingVolume")) for item in selected)
    known_buys = sum(values[0] for values in grouped.values())
    known_sells = sum(values[1] for values in grouped.values())
    grouped["기타"] = (max(total_volume - known_buys, 0), max(total_volume - known_sells, 0))

    total_buys = sum(values[0] for values in grouped.values())
    total_sells = sum(values[1] for values in grouped.values())
    rows = [
        {
            "기업명": company_name,
            "종목코드": stock_code,
            "투자자구분": label,
            "매도거래량": sell_volume,
            "매수거래량": buy_volume,
            "순매수거래량": buy_volume - sell_volume,
            "매수비중": buy_volume / total_buys * 100 if total_buys else 0.0,
            "매도비중": sell_volume / total_sells * 100 if total_sells else 0.0,
        }
        for label, (buy_volume, sell_volume) in grouped.items()
    ]
    return pd.DataFrame(rows, columns=INVESTOR_COLUMNS)
