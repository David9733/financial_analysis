"""단일 기업 주가·거래량 및 복수 기업 정규화 주가 차트."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

if __package__:
    from .correlation_settings import ROLLING_CORRELATION_SETTINGS
    from .data_quality import iqr_bounds, pair_valid
    from .macro_analysis import (
        CREDIT_SPREAD_CHANGE_BP_COLUMN,
        CREDIT_SPREAD_COLUMN,
        CREDIT_SPREAD_FILLED_COLUMN,
        CREDIT_SPREAD_OUTLIER_COLUMN,
        FX_COLUMN,
        FX_FILLED_COLUMN,
        FX_OUTLIER_COLUMN,
        FX_CHANGE_COLUMN,
        MARKET_INDEX_COLUMN,
        MARKET_INDEX_FILLED_COLUMN,
        MARKET_INDEX_NAME_COLUMN,
        MARKET_INDEX_OUTLIER_COLUMN,
        MARKET_INDEX_RETURN_COLUMN,
        PRICE_CHANGE_COLUMN,
        PRICE_OUTLIER_COLUMN,
        RATE_CHANGE_BP_COLUMN,
        RATE_CHANGE_PP_COLUMN,
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
    from correlation_settings import ROLLING_CORRELATION_SETTINGS
    from data_quality import iqr_bounds, pair_valid
    from macro_analysis import (
        CREDIT_SPREAD_CHANGE_BP_COLUMN,
        CREDIT_SPREAD_COLUMN,
        CREDIT_SPREAD_FILLED_COLUMN,
        CREDIT_SPREAD_OUTLIER_COLUMN,
        FX_COLUMN,
        FX_FILLED_COLUMN,
        FX_OUTLIER_COLUMN,
        FX_CHANGE_COLUMN,
        MARKET_INDEX_COLUMN,
        MARKET_INDEX_FILLED_COLUMN,
        MARKET_INDEX_NAME_COLUMN,
        MARKET_INDEX_OUTLIER_COLUMN,
        MARKET_INDEX_RETURN_COLUMN,
        PRICE_CHANGE_COLUMN,
        PRICE_OUTLIER_COLUMN,
        RATE_CHANGE_BP_COLUMN,
        RATE_CHANGE_PP_COLUMN,
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


MONTHLY_VOLUME_MIN_MONTHS = 6


def monthly_volume_summary(data: pd.DataFrame) -> pd.DataFrame:
    """일별 거래량을 월말 기준으로 묶어 월평균, 그달 최대 하루 거래량, 거래일 수를 만든다.

    시작·마지막 달이나 연휴가 낀 달은 거래일이 적어 합계가 작게 보이므로 평균을 쓴다.
    """
    volume = pd.to_numeric(
        data.set_index("기준일").sort_index()["거래량"], errors="coerce"
    ).dropna()
    monthly = volume.resample("ME").agg(["mean", "max", "count"])
    monthly.columns = ["월평균거래량", "최대일거래량", "거래일수"]
    return monthly[monthly["거래일수"] > 0]


def _create_monthly_volume_chart(data: pd.DataFrame, company: str, output_path: Path) -> None:
    """긴 기간의 거래량 흐름을 월 단위로 보여 주되, 하루 폭증은 최대값으로 남긴다."""
    monthly = monthly_volume_summary(data)
    if len(monthly) < MONTHLY_VOLUME_MIN_MONTHS:
        return
    # 월말 날짜 대신 그달 가운데에 막대를 놓아 날짜축과 맞춘다.
    centers = monthly.index - pd.Timedelta(days=15)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    bars = ax.bar(
        centers, monthly["월평균거래량"], width=24, color="#93B4E8", label="월평균 일거래량"
    )
    ax.plot(
        centers,
        monthly["최대일거래량"],
        color="#E53935",
        marker="o",
        markersize=4,
        linewidth=1,
        label="그달 최대 하루 거래량",
    )
    # 거래일 수는 막대 아래쪽 안에 적어 최대 거래량 점과 겹치지 않게 한다.
    for bar, days in zip(bars, monthly["거래일수"]):
        ax.annotate(
            f"{int(days)}일",
            (bar.get_x() + bar.get_width() / 2, 0),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7,
            color="#1E3A8A",
        )
    ax.set_title(f"{company} 월별 거래량 (막대 안 숫자: 거래일 수)")
    ax.set_ylabel("주")
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda value, _: f"{value:,.0f}")
    )
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
    """기업별 주가와 환율·금리·신용 스프레드를 거래일 기준으로 비교한다."""
    if market_macro.empty:
        return
    has_market_index = (
        MARKET_INDEX_COLUMN in market_macro
        and market_macro[MARKET_INDEX_COLUMN].notna().any()
    )
    has_fx = market_macro[FX_COLUMN].notna().any()
    has_rate = market_macro[RATE_COLUMN].notna().any()
    has_spread = (
        CREDIT_SPREAD_COLUMN in market_macro
        and market_macro[CREDIT_SPREAD_COLUMN].notna().any()
    )
    if not (has_market_index or has_fx or has_rate or has_spread):
        return
    charts_dir.mkdir(parents=True, exist_ok=True)
    configure_korean_font()
    panels = []
    if has_market_index:
        panels.append(
            (
                MARKET_INDEX_COLUMN,
                MARKET_INDEX_FILLED_COLUMN,
                MARKET_INDEX_OUTLIER_COLUMN,
                "시장지수(p)",
                "#DC2626",
            )
        )
    if has_fx:
        panels.append((FX_COLUMN, FX_FILLED_COLUMN, FX_OUTLIER_COLUMN, "원/달러 환율(원)", "#F59E0B"))
    if has_rate:
        panels.append((RATE_COLUMN, RATE_FILLED_COLUMN, RATE_OUTLIER_COLUMN, "국고채 3년(%)", "#7656C9"))
    if has_spread:
        panels.append(
            (
                CREDIT_SPREAD_COLUMN,
                CREDIT_SPREAD_FILLED_COLUMN,
                CREDIT_SPREAD_OUTLIER_COLUMN,
                "신용 스프레드(bp)",
                "#0F766E",
            )
        )

    for (company, code), data in market_macro.groupby(["기업명", "종목코드"], sort=False):
        data = data.sort_values("기준일")
        index_names = data.get(
            MARKET_INDEX_NAME_COLUMN, pd.Series(dtype="object")
        ).dropna()
        index_name = str(index_names.iloc[-1]) if not index_names.empty else "시장"
        company_panels = [
            (
                column,
                flag,
                outlier,
                f"{index_name} 지수(p)" if column == MARKET_INDEX_COLUMN else label,
                color,
            )
            for column, flag, outlier, label, color in panels
        ]
        fig, axes = plt.subplots(len(company_panels), 1, figsize=(10, 4.2 * len(company_panels)), sharex=True, squeeze=False)
        for ax, (column, flag, outlier, label, color) in zip(axes[:, 0], company_panels):
            _plot_close_with_macro(ax, data, column, flag, outlier, label, color)
        axes[0, 0].set_title(
            f"{company} 주가와 {index_name}, 환율, 금리, 신용 스프레드"
        )
        fig.tight_layout()
        fig.savefig(charts_dir / f"macro_{code}.png", dpi=160, bbox_inches="tight")
        plt.close(fig)


STATUS_MUTED_COLOR = "#64748B"


def _outlier_status_text(outlier_count: int, bounds: tuple[float, float] | None) -> str:
    """하루 변화 패널에 항상 표시할 이상치 판정 상태 문구."""
    if bounds is None:
        return "관측일 부족으로 판정 안 함"
    if outlier_count:
        return f"이상치 {outlier_count}일 (원인 확인 필요)"
    return "이상치 0일"


def create_daily_change_visualizations(market_macro: pd.DataFrame, charts_dir: Path) -> None:
    """하루 변화 분포와 IQR 경계를 그려 튀는 날(빨강)을 바로 보이게 한다."""
    if market_macro.empty:
        return
    charts_dir.mkdir(parents=True, exist_ok=True)
    configure_korean_font()
    # (값 열, 판정에 쓴 하루 변화 열, 표시할 하루 변화 열, 보간 열, 이상치 열, 축 이름, 선 색)
    # 금리는 %p로 판정하고 bp(= %p × 100)로 표시한다.
    series_specs = [
        ("종가", PRICE_CHANGE_COLUMN, PRICE_CHANGE_COLUMN, None, PRICE_OUTLIER_COLUMN, "종가 등락률(%)", COLORS[0]),
        (MARKET_INDEX_COLUMN, MARKET_INDEX_RETURN_COLUMN, MARKET_INDEX_RETURN_COLUMN, MARKET_INDEX_FILLED_COLUMN, MARKET_INDEX_OUTLIER_COLUMN, "시장지수 수익률(%)", "#DC2626"),
        (FX_COLUMN, FX_CHANGE_COLUMN, FX_CHANGE_COLUMN, FX_FILLED_COLUMN, FX_OUTLIER_COLUMN, "환율 변화율(%)", "#F59E0B"),
        (RATE_COLUMN, RATE_CHANGE_PP_COLUMN, RATE_CHANGE_BP_COLUMN, RATE_FILLED_COLUMN, RATE_OUTLIER_COLUMN, "금리 변화폭(bp)", "#7656C9"),
        (
            CREDIT_SPREAD_COLUMN,
            CREDIT_SPREAD_CHANGE_BP_COLUMN,
            CREDIT_SPREAD_CHANGE_BP_COLUMN,
            CREDIT_SPREAD_FILLED_COLUMN,
            CREDIT_SPREAD_OUTLIER_COLUMN,
            "신용 스프레드 변화폭(bp)",
            "#0F766E",
        ),
    ]
    for (company, code), data in market_macro.groupby(["기업명", "종목코드"], sort=False):
        data = data.sort_values("기준일").reset_index(drop=True)
        specs = [spec for spec in series_specs if data[spec[0]].notna().any()]
        if not specs:
            continue
        fig, axes = plt.subplots(len(specs), 1, figsize=(10, 3.2 * len(specs)), sharex=True, squeeze=False)
        for ax, (column, judged_column, shown_column, filled_column, outlier_column, label, color) in zip(axes[:, 0], specs):
            judged = data[judged_column]
            shown = data[shown_column]
            # 판정 단위(%p)와 표시 단위(bp)가 다르면 경계선도 같은 배율로 옮긴다.
            scale = 100 if shown_column == RATE_CHANGE_BP_COLUMN else 1
            filled = (
                data[filled_column]
                if filled_column is not None
                else pd.Series(False, index=data.index)
            )
            bounds = iqr_bounds(judged, pair_valid(filled))
            ax.bar(data["기준일"], shown, color=color, width=1, alpha=0.55)
            ax.axhline(0, color="#94A3B8", linewidth=0.8)
            if bounds is not None:
                for bound in bounds:
                    ax.axhline(bound * scale, color=OUTLIER_COLOR, linewidth=0.9, linestyle="--")
            outliers = data[data[outlier_column].fillna(False).astype(bool)]
            if not outliers.empty:
                ax.scatter(
                    outliers["기준일"],
                    shown.loc[outliers.index],
                    color=OUTLIER_COLOR,
                    s=28,
                    zorder=3,
                )
            # 이상치가 없거나 판정하지 않은 경우도 구분되도록 상태를 항상 표시한다.
            ax.text(
                0.01,
                0.95,
                _outlier_status_text(len(outliers), bounds),
                transform=ax.transAxes,
                va="top",
                fontsize=9,
                color=OUTLIER_COLOR if not outliers.empty else STATUS_MUTED_COLOR,
                bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 2},
            )
            ax.set_ylabel(label)
            _finish_date_axis(ax)
        axes[0, 0].set_title(f"{company} 하루 변화와 이상치 (빨간 점선: 통상 범위)")
        fig.tight_layout()
        fig.savefig(charts_dir / f"daily_change_{code}.png", dpi=160, bbox_inches="tight")
        plt.close(fig)


def _build_fx_rate_scatter_figure(
    data: pd.DataFrame, company: str
) -> tuple[plt.Figure, float] | None:
    """환율 변화율(x)과 금리 변화폭(y)의 산점도·선형 추세선을 만든다."""
    fx_filled = data[FX_FILLED_COLUMN].fillna(False).astype(bool)
    rate_filled = data[RATE_FILLED_COLUMN].fillna(False).astype(bool)
    valid = pair_valid(fx_filled) & pair_valid(rate_filled)
    points = pd.DataFrame(
        {
            "환율 변화율(%)": pd.to_numeric(data[FX_CHANGE_COLUMN], errors="coerce"),
            "금리 변화폭(bp)": pd.to_numeric(data[RATE_CHANGE_BP_COLUMN], errors="coerce"),
        }
    )[valid].dropna()
    if len(points) < 2 or points["환율 변화율(%)"].nunique() < 2:
        return None

    x = points["환율 변화율(%)"].to_numpy(dtype=float)
    y = points["금리 변화폭(bp)"].to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    trend_x = np.linspace(x.min(), x.max(), 100)
    trend_y = slope * trend_x + intercept

    configure_korean_font()
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.scatter(
        x,
        y,
        s=38,
        alpha=0.7,
        color="#2563EB",
        edgecolors="white",
        linewidths=0.6,
        label="일별 관측값",
    )
    ax.plot(
        trend_x,
        trend_y,
        color="#E53935",
        linewidth=1.8,
        linestyle="--",
        label="선형 추세선",
    )
    ax.axhline(0, color="#94A3B8", linewidth=0.8)
    ax.axvline(0, color="#94A3B8", linewidth=0.8)
    ax.set_title(f"{company} 환율 변화율과 금리 변화폭 산점도")
    ax.set_xlabel("환율 변화율(%)")
    ax.set_ylabel("금리 변화폭(bp)")
    ax.text(
        0.02,
        0.97,
        f"추세선 기울기: {slope:+.4f} bp/%",
        transform=ax.transAxes,
        va="top",
        fontsize=10,
        bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "#CBD5E1", "pad": 5},
    )
    ax.grid(alpha=0.22)
    ax.legend(loc="best", frameon=False)
    fig.tight_layout()
    return fig, float(slope)


def create_fx_rate_scatter_visualizations(
    market_macro: pd.DataFrame, charts_dir: Path
) -> None:
    """기업별 환율 변화율·금리 변화폭 산점도를 PNG로 저장한다."""
    if market_macro.empty:
        return
    required = {
        FX_CHANGE_COLUMN,
        RATE_CHANGE_BP_COLUMN,
        FX_FILLED_COLUMN,
        RATE_FILLED_COLUMN,
    }
    if not required.issubset(market_macro.columns):
        return

    charts_dir.mkdir(parents=True, exist_ok=True)
    for (company, code), data in market_macro.groupby(["기업명", "종목코드"], sort=False):
        built = _build_fx_rate_scatter_figure(
            data.sort_values("기준일").reset_index(drop=True), company
        )
        if built is None:
            continue
        fig, _ = built
        fig.savefig(
            charts_dir / f"fx_rate_scatter_{code}.png",
            dpi=160,
            bbox_inches="tight",
        )
        plt.close(fig)


MIN_HEATMAP_OBSERVATIONS = 10
HEATMAP_COLUMNS = (
    "주가 수익률(%)",
    "시장지수 수익률(%)",
    "환율 변화율(%)",
    "금리 변화폭(bp)",
    "신용 스프레드 변화폭(bp)",
)


def _build_market_correlation_heatmap_figure(
    data: pd.DataFrame, company: str
) -> tuple[plt.Figure, pd.DataFrame, int] | None:
    """주가와 세 외부 요인의 일간 변화 Pearson 상관행렬을 만든다."""
    fx_filled = data[FX_FILLED_COLUMN].fillna(False).astype(bool)
    rate_filled = data[RATE_FILLED_COLUMN].fillna(False).astype(bool)
    valid = pair_valid(fx_filled) & pair_valid(rate_filled)
    change_series = {
        HEATMAP_COLUMNS[0]: pd.to_numeric(
            data[PRICE_CHANGE_COLUMN], errors="coerce"
        ),
    }
    has_market_index = {
        MARKET_INDEX_RETURN_COLUMN,
        MARKET_INDEX_FILLED_COLUMN,
    }.issubset(data.columns) and data[MARKET_INDEX_RETURN_COLUMN].notna().any()
    if has_market_index:
        market_index_filled = data[MARKET_INDEX_FILLED_COLUMN].fillna(False).astype(bool)
        valid &= pair_valid(market_index_filled)
        change_series[HEATMAP_COLUMNS[1]] = pd.to_numeric(
            data[MARKET_INDEX_RETURN_COLUMN], errors="coerce"
        )
    change_series.update(
        {
        HEATMAP_COLUMNS[2]: pd.to_numeric(
            data[FX_CHANGE_COLUMN], errors="coerce"
        ),
        HEATMAP_COLUMNS[3]: pd.to_numeric(
            data[RATE_CHANGE_BP_COLUMN], errors="coerce"
        ),
        }
    )
    has_spread = {
        CREDIT_SPREAD_CHANGE_BP_COLUMN,
        CREDIT_SPREAD_FILLED_COLUMN,
    }.issubset(data.columns) and data[CREDIT_SPREAD_CHANGE_BP_COLUMN].notna().any()
    if has_spread:
        spread_filled = data[CREDIT_SPREAD_FILLED_COLUMN].fillna(False).astype(bool)
        valid &= pair_valid(spread_filled)
        change_series[HEATMAP_COLUMNS[4]] = pd.to_numeric(
            data[CREDIT_SPREAD_CHANGE_BP_COLUMN], errors="coerce"
        )
    changes = pd.DataFrame(change_series)[valid].dropna()
    columns = tuple(changes.columns)
    if len(changes) < MIN_HEATMAP_OBSERVATIONS:
        return None
    if any(changes[column].nunique() < 2 for column in columns):
        return None

    correlation = changes.corr(method="pearson")
    configure_korean_font()
    fig, ax = plt.subplots(figsize=(9.2, 7.2))
    diagonal_mask = np.eye(len(columns), dtype=bool)
    visible_correlation = np.ma.array(
        correlation.to_numpy(), mask=diagonal_mask
    )
    color_map = matplotlib.colormaps["RdBu_r"].with_extremes(bad="#F1F5F9")
    image = ax.imshow(visible_correlation, cmap=color_map, vmin=-1, vmax=1)
    ax.set_xticks(range(len(columns)), columns, rotation=15, ha="right")
    ax.set_yticks(range(len(columns)), columns)
    title_factors = "·".join(
        column.replace("(%)", "").replace("(bp)", "") for column in columns
    )
    ax.set_title(
        f"{company} {title_factors} 상관관계 히트맵\n"
        f"Pearson 상관계수 · 유효 관측 {len(changes)}일"
    )

    for row in range(len(columns)):
        for column in range(len(columns)):
            if row == column:
                continue
            value = correlation.iloc[row, column]
            ax.text(
                column,
                row,
                f"{value:.2f}",
                ha="center",
                va="center",
                color="white" if abs(value) >= 0.55 else "#111827",
                fontsize=12,
                fontweight="bold",
            )

    ax.set_xticks(np.arange(-0.5, len(columns), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(columns), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    colorbar.set_label("Pearson 상관계수 (-1 ~ 1)")
    fig.tight_layout()
    return fig, correlation, len(changes)


def create_market_correlation_heatmaps(
    market_macro: pd.DataFrame, charts_dir: Path
) -> None:
    """기업별 주가와 세 외부 요인의 변화 상관행렬을 PNG로 저장한다."""
    if market_macro.empty:
        return
    required = {
        PRICE_CHANGE_COLUMN,
        FX_CHANGE_COLUMN,
        RATE_CHANGE_BP_COLUMN,
        FX_FILLED_COLUMN,
        RATE_FILLED_COLUMN,
    }
    if not required.issubset(market_macro.columns):
        return

    charts_dir.mkdir(parents=True, exist_ok=True)
    for (company, code), data in market_macro.groupby(["기업명", "종목코드"], sort=False):
        built = _build_market_correlation_heatmap_figure(
            data.sort_values("기준일").reset_index(drop=True), company
        )
        if built is None:
            continue
        fig, _, _ = built
        fig.savefig(
            charts_dir / f"market_correlation_heatmap_{code}.png",
            dpi=160,
            bbox_inches="tight",
        )
        plt.close(fig)


def _rolling_correlation(
    first: pd.Series,
    second: pd.Series,
    valid: pd.Series,
    window: int,
    min_observations: int,
) -> pd.Series:
    """지정한 창에서 최소 관측치를 충족하는 Pearson 이동상관을 계산한다."""
    first_valid = pd.to_numeric(first, errors="coerce").where(valid)
    second_valid = pd.to_numeric(second, errors="coerce").where(valid)
    return first_valid.rolling(
        window=window,
        min_periods=min_observations,
    ).corr(second_valid)


def _build_rolling_correlation_figure(
    data: pd.DataFrame, company: str, stock_period: str
) -> tuple[plt.Figure, pd.DataFrame] | None:
    """조회기간에 맞는 창으로 기업 수익률과 네 요인의 이동상관을 만든다."""
    if stock_period not in ROLLING_CORRELATION_SETTINGS:
        raise ValueError(f"지원하지 않는 주가 조회기간입니다: {stock_period}")
    period_label, window, min_observations = ROLLING_CORRELATION_SETTINGS[stock_period]
    data = data.sort_values("기준일").reset_index(drop=True)
    fx_valid = pair_valid(data[FX_FILLED_COLUMN].fillna(False).astype(bool))
    rate_valid = pair_valid(data[RATE_FILLED_COLUMN].fillna(False).astype(bool))
    stock_return = pd.to_numeric(data[PRICE_CHANGE_COLUMN], errors="coerce")
    fx_change = pd.to_numeric(data[FX_CHANGE_COLUMN], errors="coerce")
    rate_change = pd.to_numeric(data[RATE_CHANGE_BP_COLUMN], errors="coerce")
    rolling_series = {
        "기준일": data["기준일"],
    }
    has_market_index = {
        MARKET_INDEX_RETURN_COLUMN,
        MARKET_INDEX_FILLED_COLUMN,
    }.issubset(data.columns) and data[MARKET_INDEX_RETURN_COLUMN].notna().any()
    if has_market_index:
        market_index_valid = pair_valid(
            data[MARKET_INDEX_FILLED_COLUMN].fillna(False).astype(bool)
        )
        market_index_return = pd.to_numeric(
            data[MARKET_INDEX_RETURN_COLUMN], errors="coerce"
        )
        rolling_series["주가 수익률-시장지수 수익률"] = _rolling_correlation(
            stock_return,
            market_index_return,
            market_index_valid,
            window,
            min_observations,
        )
    rolling_series.update(
        {
            "주가 수익률-환율 변화율": _rolling_correlation(
                stock_return, fx_change, fx_valid, window, min_observations
            ),
            "주가 수익률-금리 변화폭": _rolling_correlation(
                stock_return, rate_change, rate_valid, window, min_observations
            ),
        }
    )
    has_spread = {
        CREDIT_SPREAD_CHANGE_BP_COLUMN,
        CREDIT_SPREAD_FILLED_COLUMN,
    }.issubset(data.columns) and data[CREDIT_SPREAD_CHANGE_BP_COLUMN].notna().any()
    if has_spread:
        spread_valid = pair_valid(
            data[CREDIT_SPREAD_FILLED_COLUMN].fillna(False).astype(bool)
        )
        spread_change = pd.to_numeric(
            data[CREDIT_SPREAD_CHANGE_BP_COLUMN], errors="coerce"
        )
        rolling_series["주가 수익률-신용 스프레드 변화폭"] = _rolling_correlation(
            stock_return,
            spread_change,
            spread_valid,
            window,
            min_observations,
        )
    rolling = pd.DataFrame(rolling_series)
    correlation_columns = [column for column in rolling.columns if column != "기준일"]
    if not any(rolling[column].notna().any() for column in correlation_columns):
        return None

    configure_korean_font()
    colors = ("#DC2626", "#2563EB", "#F97316", "#0F766E")
    fig, axes_grid = plt.subplots(
        len(correlation_columns),
        1,
        figsize=(10, 2.7 * len(correlation_columns) + 1),
        sharex=True,
        squeeze=False,
    )
    axes = axes_grid[:, 0]
    for ax, column, color in zip(axes, correlation_columns, colors):
        ax.plot(
            rolling["기준일"],
            rolling[column],
            color=color,
            linewidth=1.8,
        )
        ax.axhline(0, color="#64748B", linewidth=0.9, linestyle="--")
        for boundary in (-0.7, -0.3, 0.3, 0.7):
            ax.axhline(
                boundary,
                color="#CBD5E1",
                linewidth=0.8,
                linestyle=":",
            )
        ax.set_ylim(-1.05, 1.05)
        ax.set_ylabel("상관계수")
        ax.set_title(column, loc="left", fontsize=11)
        latest = (
            rolling.loc[rolling[column].last_valid_index()]
            if rolling[column].notna().any()
            else None
        )
        if latest is not None:
            ax.annotate(
                f"최근 {latest[column]:+.2f}",
                xy=(latest["기준일"], latest[column]),
                xytext=(-8, 8),
                textcoords="offset points",
                ha="right",
                color=color,
                fontsize=9,
            )
        _finish_date_axis(ax)

    axes[-1].set_xlabel("날짜")
    fig.suptitle(
        f"{company} {period_label} 조회 · {window}거래일 이동상관\n"
        f"최근 {window}거래일 중 유효 관측 {min_observations}일 이상",
        fontsize=14,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig, rolling


def create_rolling_correlation_visualizations(
    market_macro: pd.DataFrame, charts_dir: Path, stock_period: str
) -> None:
    """조회기간별 설정을 적용한 기업별 이동상관 차트를 PNG로 저장한다."""
    if market_macro.empty:
        return
    required = {
        "기준일",
        PRICE_CHANGE_COLUMN,
        FX_CHANGE_COLUMN,
        RATE_CHANGE_BP_COLUMN,
        FX_FILLED_COLUMN,
        RATE_FILLED_COLUMN,
    }
    if not required.issubset(market_macro.columns):
        return

    charts_dir.mkdir(parents=True, exist_ok=True)
    for (company, code), data in market_macro.groupby(["기업명", "종목코드"], sort=False):
        built = _build_rolling_correlation_figure(data, company, stock_period)
        if built is None:
            continue
        fig, _ = built
        fig.savefig(
            charts_dir / f"rolling_correlation_{stock_period}_{code}.png",
            dpi=160,
            bbox_inches="tight",
        )
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
        _create_monthly_volume_chart(data, company, charts_dir / "stock_volume_monthly.png")
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
        _create_monthly_volume_chart(
            data, company, charts_dir / f"stock_volume_monthly_{code}.png"
        )
        if investor_summary is not None and not investor_summary.empty:
            investor_data = investor_summary[investor_summary["종목코드"] == code]
            if not investor_data.empty:
                _create_investor_pie(
                    investor_data,
                    company,
                    charts_dir / f"stock_investor_ratio_{code}.png",
                )
