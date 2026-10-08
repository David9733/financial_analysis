"""조회기간별 이동상관 공통 설정."""

from __future__ import annotations


# 표시명, 이동 창, 창 안의 최소 유효 관측치
ROLLING_CORRELATION_SETTINGS = {
    "1m": ("1개월", 10, 10),
    "3m": ("3개월", 20, 20),
    "6m": ("6개월", 60, 60),
    "1y": ("1년", 60, 60),
    "3y": ("3년", 60, 60),
}

SHORT_TERM_CORRELATION_PERIODS = {"1m", "3m"}
