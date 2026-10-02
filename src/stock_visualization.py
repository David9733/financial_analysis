"""단일 기업 주가·거래량 및 복수 기업 정규화 주가 차트."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .stock_analysis import (
        MOVING_AVERAGE_WINDOWS,
        add_bollinger_bands,
        add_moving_averages,
        normalize_for_comparison,
    )
    from .visualization import COLORS, configure_korean_font
else:
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
