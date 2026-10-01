"""단일 기업 추세 또는 여러 기업 비교 차트를 생성한다."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd


LOGGER = logging.getLogger(__name__)
COLORS = ["#2563EB", "#F97316", "#16A34A", "#DC2626", "#7C3AED", "#0891B2"]


def configure_korean_font() -> None:
    """설치된 한글 글꼴을 찾아 Matplotlib에 적용한다."""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in ("Malgun Gothic", "AppleGothic", "Noto Sans CJK KR", "NanumGothic"):
        if candidate in installed:
            plt.rcParams["font.family"] = candidate
            break
    else:
        LOGGER.warning("한글 글꼴을 찾지 못해 그래프 글자가 깨질 수 있습니다.")
    plt.rcParams["axes.unicode_minus"] = False


def _finish_axis(ax, title: str, ylabel: str) -> None:
    ax.set_title(title)
    ax.set_xlabel("연도")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend()


def _line_chart(
    data: pd.DataFrame,
    columns: list[str],
    title: str,
    ylabel: str,
    scale: float = 1,
):
    fig, ax = plt.subplots(figsize=(9, 5))
    available_columns = [column for column in columns if column in data and data[column].notna().any()]
    for index, column in enumerate(available_columns):
        ax.plot(
            data["연도"],
            data[column] / scale,
            marker="o",
            linewidth=2,
            label=column,
            color=COLORS[index % len(COLORS)],
        )
    if not available_columns:
        ax.text(
            0.5,
            0.5,
            "사용 가능한 원천 데이터 없음",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    _finish_axis(ax, title, ylabel)
    ax.set_xticks(data["연도"])
    if len(data) > 1:
        ax.set_xlim(data["연도"].min() - 0.5, data["연도"].max() + 0.5)
    fig.tight_layout()
    return fig


def _save_figure(fig, path: Path) -> None:
    fig.savefig(path, dpi=160, bbox_inches="tight")


def create_single_company_charts(data: pd.DataFrame, charts_dir: Path) -> list:
    """한 기업의 분석유형에 맞는 연도별 변화 차트를 만든다."""
    company = data["기업명"].iloc[0]
    analysis_type = data["분석유형"].iloc[0]
    data = data.sort_values("연도")
    figures = []

    if analysis_type == "일반기업":
        fig, ax = plt.subplots(figsize=(9, 5))
        x = np.arange(len(data))
        width = 0.36
        ax.bar(x - width / 2, data["매출"] / 1e12, width, label="매출", color=COLORS[0])
        ax.bar(x + width / 2, data["영업이익"] / 1e12, width, label="영업이익", color=COLORS[1])
        ax.set_xticks(x, data["연도"])
        _finish_axis(ax, f"{company} 매출과 영업이익", "조 원")
        fig.tight_layout()
        _save_figure(fig, charts_dir / "revenue_operating_profit.png")
        figures.append(fig)
        chart_specs = [
            (["영업이익률"], f"{company} 영업이익률", "비율 (%)", 1, "operating_margin.png"),
            (["부채비율"], f"{company} 부채비율", "비율 (%)", 1, "debt_ratio.png"),
            (["이자보상배율"], f"{company} 이자보상배율", "배", 1, "interest_coverage.png"),
            (["ROE", "매출성장"], f"{company} ROE와 매출성장", "비율 (%)", 1, "roe_revenue_growth.png"),
            (["매출채권회전일수"], f"{company} 매출채권회전일수", "일", 1, "receivables_days.png"),
        ]
    elif analysis_type == "금융업":
        chart_specs = [
            (["총자산"], f"{company} 총자산", "조 원", 1e12, "total_assets.png"),
            (["영업이익", "당기순이익"], f"{company} 이익", "조 원", 1e12, "financial_profit.png"),
            (["순이자손익", "순수수료손익"], f"{company} 주요 영업손익", "조 원", 1e12, "financial_income.png"),
            (
                ["ROE", "총자산성장", "영업이익성장", "당기순이익성장"],
                f"{company} 수익성과 성장",
                "비율 (%)",
                1,
                "financial_growth.png",
            ),
        ]
    else:
        chart_specs = [
            (
                ["보험서비스수익", "영업이익", "당기순이익"],
                f"{company} 보험서비스수익과 이익",
                "조 원",
                1e12,
                "insurance_revenue_profit.png",
            ),
            (
                ["보험서비스손익", "투자손익"],
                f"{company} 보험서비스손익과 투자손익",
                "조 원",
                1e12,
                "insurance_results.png",
            ),
            (["총자산"], f"{company} 총자산", "조 원", 1e12, "total_assets.png"),
            (
                ["보험서비스마진", "ROE", "보험서비스수익성장", "총자산성장"],
                f"{company} 보험 수익성과 성장",
                "비율 (%)",
                1,
                "insurance_growth.png",
            ),
        ]

    for columns, title, ylabel, scale, filename in chart_specs:
        fig = _line_chart(data, columns, title, ylabel, scale=scale)
        _save_figure(fig, charts_dir / filename)
        figures.append(fig)
    return figures


def _latest_common_year(data: pd.DataFrame) -> int:
    year_sets = [set(group["연도"]) for _, group in data.groupby("기업명")]
    common_years = set.intersection(*year_sets) if year_sets else set()
    if not common_years:
        raise ValueError("모든 기업에 공통으로 존재하는 분석 연도가 없습니다.")
    return max(common_years)


def create_comparison_charts(data: pd.DataFrame, charts_dir: Path) -> list:
    """가장 최근 공통 연도의 적용 가능한 지표를 기업별로 비교한다."""
    year = _latest_common_year(data)
    comparison = data[data["연도"] == year].copy()
    specs = [
        ("매출", "조 원", 1e12, "comparison_revenue.png"),
        ("보험서비스수익", "조 원", 1e12, "comparison_insurance_revenue.png"),
        ("순이자손익", "조 원", 1e12, "comparison_net_interest_income.png"),
        ("순수수료손익", "조 원", 1e12, "comparison_net_fee_income.png"),
        ("총자산", "조 원", 1e12, "comparison_total_assets.png"),
        ("영업이익", "조 원", 1e12, "comparison_operating_profit.png"),
        ("당기순이익", "조 원", 1e12, "comparison_net_income.png"),
        ("영업이익률", "%", 1, "comparison_operating_margin.png"),
        ("보험서비스마진", "%", 1, "comparison_insurance_margin.png"),
        ("부채비율", "%", 1, "comparison_debt_ratio.png"),
        ("이자보상배율", "배", 1, "comparison_interest_coverage.png"),
        ("ROE", "%", 1, "comparison_roe.png"),
        ("매출성장", "%", 1, "comparison_revenue_growth.png"),
        ("보험서비스수익성장", "%", 1, "comparison_insurance_revenue_growth.png"),
        ("총자산성장", "%", 1, "comparison_asset_growth.png"),
        ("매출채권회전일수", "일", 1, "comparison_receivables_days.png"),
    ]
    figures = []
    for metric, unit, scale, filename in specs:
        plot_data = comparison[["기업명", metric]].dropna()
        if plot_data.empty:
            continue
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.bar(
            plot_data["기업명"],
            plot_data[metric] / scale,
            color=[COLORS[index % len(COLORS)] for index in range(len(plot_data))],
        )
        ax.set_title(f"{year}년 기업별 {metric}")
        ax.set_xlabel("기업명")
        ax.set_ylabel(unit)
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        _save_figure(fig, charts_dir / filename)
        figures.append(fig)
    return figures


def create_visualizations(
    data: pd.DataFrame,
    charts_dir: Path,
    show_charts: bool = True,
) -> None:
    """기업 수에 따라 추세 또는 비교 차트를 자동 생성한다."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    configure_korean_font()
    company_count = data["기업명"].nunique()
    if company_count == 1:
        figures = create_single_company_charts(data, charts_dir)
    else:
        figures = create_comparison_charts(data, charts_dir)

    if show_charts:
        plt.show()
    for fig in figures:
        plt.close(fig)
