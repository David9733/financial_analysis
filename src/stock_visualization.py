"""단일 기업 주가·거래량 및 복수 기업 정규화 주가 차트."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .data_quality import IQR_MULTIPLIER, daily_change, iqr_bounds, pair_valid
    from .macro_analysis import (
        FX_COLUMN,
        FX_FILLED_COLUMN,
        FX_OUTLIER_COLUMN,
        PRICE_OUTLIER_COLUMN,
        RATE_COLUMN,
        RATE_FILLED_COLUMN,
        RATE_OUTLIER_COLUMN,
    )
    from .stock_analysis import (
        MOVING_AVERAGE_WINDOWS,
        add_bollinger_bands,
        add_moving_averages,
        normalize_for_comparison,
    )
    from .visualization import COLORS, configure_korean_font
else:
    from data_quality import IQR_MULTIPLIER, daily_change, iqr_bounds, pair_valid
    from macro_analysis import (
        FX_COLUMN,
        FX_FILLED_COLUMN,
        FX_OUTLIER_COLUMN,
        PRICE_OUTLIER_COLUMN,
        RATE_COLUMN,
        RATE_FILLED_COLUMN,
        RATE_OUTLIER_COLUMN,
    )
    from stock_analysis import (
        MOVING_AVERAGE_WINDOWS,
        add_bollinger_bands,
        add_moving_averages,
        normalize_for_comparison,
    )
    from visualization import COLORS, configure_korean_font


def _finish_date_axis(ax) -> None:
    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.grid(axis="y", alpha=0.25)


def _create_volume_chart(data: pd.DataFrame, company: str, output_path: Path) -> None:
    """시가 대비 종가 방향을 매수·매도 우세의 시각적 대용치로 표시한다."""
    colors = data.apply(
        lambda row: "#E53935"
        if pd.notna(row["시가"]) and row["종가"] >= row["시가"]
        else "#1E6BD6",
        axis=1,
    )
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.bar(data["기준일"], data["거래량"], color=colors, width=1)
    ax.set_title(f"{company} 거래량 추이")
    ax.set_ylabel("주")
    ax.plot([], [], color="#E53935", linewidth=7, label="매수 우세 (종가 ≥ 시가)")
    ax.plot([], [], color="#1E6BD6", linewidth=7, label="매도 우세 (종가 < 시가)")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    _finish_date_axis(ax)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _create_price_chart(data: pd.DataFrame, company: str, output_path: Path) -> None:
    data = add_moving_averages(data)
    data = add_bollinger_bands(data)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        data["기준일"],
        data["종가"],
        color=COLORS[0],
        linewidth=1.8,
        label="종가",
    )
    moving_average_colors = {5: "#F59E0B", 20: "#E53935", 60: "#7656C9"}
    for window in MOVING_AVERAGE_WINDOWS:
        column = f"이동평균{window}일"
        if data[column].notna().any():
            ax.plot(
                data["기준일"],
                data[column],
                color=moving_average_colors[window],
                linewidth=1.4,
                label=f"{window}일선",
            )
    if data["BB중간"].notna().any():
        ax.plot(
            data["기준일"],
            data["BB중간"],
            color="#0F766E",
            linewidth=1.2,
            linestyle="--",
            label="BB중간(20일)",
        )
        ax.plot(
            data["기준일"],
            data["BB상한"],
            color="#14B8A6",
            linewidth=1,
            label="BB상한",
        )
        ax.plot(
            data["기준일"],
            data["BB하한"],
            color="#14B8A6",
            linewidth=1,
            label="BB하한",
        )
        ax.fill_between(
            data["기준일"],
            data["BB하한"],
            data["BB상한"],
            color="#5EEAD4",
            alpha=0.12,
        )
    ax.set_title(f"{company} 종가·이동평균선·볼린저 밴드")
    ax.set_ylabel("원")
    ax.legend(loc="best", frameon=False)
    _finish_date_axis(ax)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _create_investor_pie(data: pd.DataFrame, company: str, output_path: Path) -> None:
    values = pd.to_numeric(data["매수거래량"], errors="coerce").fillna(0).clip(lower=0)
    if values.sum() <= 0:
        return
    fig, ax = plt.subplots(figsize=(7, 5.5))
    ax.pie(
        values,
        labels=data["투자자구분"],
        autopct="%1.1f%%",
        startangle=90,
        colors=["#7656C9", "#20B486", "#E53935", "#94A3B8"],
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )
    ax.set_title(f"{company} 최근 투자자별 매수 거래량 비중")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


OUTLIER_COLOR = "#E53935"


def _true_rows(data: pd.DataFrame, column: str) -> pd.DataFrame:
    if column not in data:
        return data.iloc[0:0]
    return data[data[column].fillna(False).astype(bool)]


def _plot_close_with_macro(
    ax, data: pd.DataFrame, column: str, flag: str, outlier: str, label: str, color: str
) -> None:
    """왼쪽 축에 종가, 오른쪽 축에 매크로 값을 같은 거래일 기준으로 그린다."""
    ax.plot(data["기준일"], data["종가"], color=COLORS[0], linewidth=1.6, label="종가")
    ax.set_ylabel("종가(원)")
    macro_ax = ax.twinx()
    macro_ax.plot(data["기준일"], data[column], color=color, linewidth=1.4, label=label)
    filled = _true_rows(data, flag)
    if not filled.empty:
        macro_ax.scatter(
            filled["기준일"],
            filled[column],
            color=color,
            marker="x",
            s=24,
            zorder=3,
            label="직전 값으로 보간",
        )
    outliers = _true_rows(data, outlier)
    if not outliers.empty:
        macro_ax.scatter(
            outliers["기준일"],
            outliers[column],
            color=OUTLIER_COLOR,
            s=26,
            zorder=4,
            label="하루 변화 이상치",
        )
    macro_ax.set_ylabel(label)
    handles, labels = ax.get_legend_handles_labels()
    macro_handles, macro_labels = macro_ax.get_legend_handles_labels()
    ax.legend(handles + macro_handles, labels + macro_labels, loc="upper left", frameon=False, fontsize=9)
    _finish_date_axis(ax)


def create_macro_visualizations(market_macro: pd.DataFrame, charts_dir: Path) -> None:
    """기업별 주가와 원/달러 환율·국고채 3년 금리를 거래일 기준으로 비교한다."""
    if market_macro.empty:
        return
    has_fx = market_macro[FX_COLUMN].notna().any()
    has_rate = market_macro[RATE_COLUMN].notna().any()
    if not (has_fx or has_rate):
        return
    charts_dir.mkdir(parents=True, exist_ok=True)
    configure_korean_font()
    panels = []
    if has_fx:
        panels.append((FX_COLUMN, FX_FILLED_COLUMN, FX_OUTLIER_COLUMN, "원/달러 환율(원)", "#F59E0B"))
    if has_rate:
        panels.append((RATE_COLUMN, RATE_FILLED_COLUMN, RATE_OUTLIER_COLUMN, "국고채 3년(%)", "#7656C9"))

    for (company, code), data in market_macro.groupby(["기업명", "종목코드"], sort=False):
        data = data.sort_values("기준일")
        fig, axes = plt.subplots(len(panels), 1, figsize=(10, 4.2 * len(panels)), sharex=True, squeeze=False)
        for ax, (column, flag, outlier, label, color) in zip(axes[:, 0], panels):
            _plot_close_with_macro(ax, data, column, flag, outlier, label, color)
        axes[0, 0].set_title(f"{company} 주가와 환율, 금리")
        fig.tight_layout()
        fig.savefig(charts_dir / f"macro_{code}.png", dpi=160, bbox_inches="tight")
        plt.close(fig)


def create_daily_change_visualizations(market_macro: pd.DataFrame, charts_dir: Path) -> None:
    """하루 변화 분포와 IQR 경계를 그려 튀는 날(빨강)을 바로 보이게 한다."""
    if market_macro.empty:
        return
    charts_dir.mkdir(parents=True, exist_ok=True)
    configure_korean_font()
    # (값 열, 보간 열, 이상치 열, 변화 방식, 표시 배율, 축 이름, 선 색)
    series_specs = [
        ("종가", None, PRICE_OUTLIER_COLUMN, "pct", 1, "종가 변화율(%)", COLORS[0]),
        (FX_COLUMN, FX_FILLED_COLUMN, FX_OUTLIER_COLUMN, "pct", 1, "환율 변화율(%)", "#F59E0B"),
        (RATE_COLUMN, RATE_FILLED_COLUMN, RATE_OUTLIER_COLUMN, "diff", 100, "금리 변화(bp)", "#7656C9"),
    ]
    for (company, code), data in market_macro.groupby(["기업명", "종목코드"], sort=False):
        data = data.sort_values("기준일").reset_index(drop=True)
        specs = [spec for spec in series_specs if data[spec[0]].notna().any()]
        if not specs:
            continue
        fig, axes = plt.subplots(len(specs), 1, figsize=(10, 3.2 * len(specs)), sharex=True, squeeze=False)
        for ax, (column, filled_column, outlier_column, kind, scale, label, color) in zip(axes[:, 0], specs):
            changes = daily_change(data[column], kind)
            filled = (
                data[filled_column]
                if filled_column is not None
                else pd.Series(False, index=data.index)
            )
            bounds = iqr_bounds(changes, pair_valid(filled))
            ax.bar(data["기준일"], changes * scale, color=color, width=1, alpha=0.55)
            ax.axhline(0, color="#94A3B8", linewidth=0.8)
            if bounds is not None:
                for bound in bounds:
                    ax.axhline(bound * scale, color=OUTLIER_COLOR, linewidth=0.9, linestyle="--")
            outliers = data[data[outlier_column].fillna(False).astype(bool)]
            if not outliers.empty:
                ax.scatter(
                    outliers["기준일"],
                    changes.loc[outliers.index] * scale,
                    color=OUTLIER_COLOR,
                    s=28,
                    zorder=3,
                    label=f"IQR 밖 {len(outliers)}일",
                )
                ax.legend(loc="upper left", frameon=False, fontsize=9)
            ax.set_ylabel(label)
            _finish_date_axis(ax)
        axes[0, 0].set_title(f"{company} 하루 변화와 이상치(IQR {IQR_MULTIPLIER}배 경계)")
        fig.tight_layout()
        fig.savefig(charts_dir / f"daily_change_{code}.png", dpi=160, bbox_inches="tight")
        plt.close(fig)


def create_stock_visualizations(
    prices: pd.DataFrame,
    charts_dir: Path,
    investor_summary: pd.DataFrame | None = None,
) -> None:
    """기업 수에 맞는 주식시장 차트를 생성한다."""
    if prices.empty:
        return
    charts_dir.mkdir(parents=True, exist_ok=True)
    configure_korean_font()

    if prices["기업명"].nunique() == 1:
        data = prices.sort_values("기준일")
        company = data["기업명"].iloc[0]

        _create_price_chart(data, company, charts_dir / "stock_price.png")

        _create_volume_chart(data, company, charts_dir / "stock_volume.png")
        if investor_summary is not None and not investor_summary.empty:
            _create_investor_pie(
                investor_summary,
                company,
                charts_dir / "stock_investor_ratio.png",
            )
        return

    comparison = normalize_for_comparison(prices)
    if comparison["정규화주가"].notna().any():
        fig, ax = plt.subplots(figsize=(11, 6))
        for index, (company, group) in enumerate(comparison.groupby("기업명")):
            group = group.sort_values("기준일")
            ax.plot(
                group["기준일"],
                group["정규화주가"],
                label=company,
                linewidth=2,
                color=COLORS[index % len(COLORS)],
            )
        ax.axhline(100, color="#94A3B8", linewidth=1, linestyle="--")
        ax.set_title("기업별 주가 성과 비교")
        ax.set_ylabel("첫 공통 거래일 = 100")
        ax.legend()
        _finish_date_axis(ax)
        fig.tight_layout()
        fig.savefig(charts_dir / "stock_comparison.png", dpi=160, bbox_inches="tight")
        plt.close(fig)

    for company, data in prices.groupby("기업명", sort=False):
        code = str(data["종목코드"].iloc[0])
        data = data.sort_values("기준일")
        _create_price_chart(data, company, charts_dir / f"stock_price_{code}.png")
        _create_volume_chart(data, company, charts_dir / f"stock_volume_{code}.png")
        if investor_summary is not None and not investor_summary.empty:
            investor_data = investor_summary[investor_summary["종목코드"] == code]
            if not investor_data.empty:
                _create_investor_pie(
                    investor_data,
                    company,
                    charts_dir / f"stock_investor_ratio_{code}.png",
                )
