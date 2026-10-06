"""
統計圖表 (取代原版 ECharts)。以 matplotlib 嵌入 Qt,深色主題,
類別軸圖表滑鼠移上去會顯示該區間所有數列的數值。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib

matplotlib.use("Qt5Agg")

from matplotlib import rcParams  # noqa: E402
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PyQt5.QtWidgets import QSizePolicy  # noqa: E402

from .. import fmt  # noqa: E402

rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei", "Noto Sans CJK TC", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False

AXIS = "#5d738f"
GRID = (0.58, 0.70, 0.84, 0.10)
TEXT = "#8ba3c0"


@dataclass
class Series:
    name: str
    values: list
    kind: str = "line"  # line | bar | area
    color: str = fmt.ACCENT
    axis: int = 0  # 0 左軸 / 1 右軸
    stack: bool = False
    dashed: bool = False
    marker: bool = False


@dataclass
class _HoverInfo:
    labels: list[str] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)
    unit: str = ""
    extra: dict[int, str] = field(default_factory=dict)


class ChartWidget(FigureCanvasQTAgg):
    def __init__(self, height: int = 300, parent=None):
        self.fig = Figure(figsize=(6, height / 100), dpi=100, facecolor="none")
        super().__init__(self.fig)
        self.setParent(parent)
        self.setStyleSheet("background: transparent")
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(height)
        self._hover = _HoverInfo()
        self._annot = None
        self._axes = []
        self.mpl_connect("motion_notify_event", self._on_move)
        self.mpl_connect("figure_leave_event", lambda _e: self._hide_annot())
        self._last_render = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_last_render", None) is not None:  # 寬度改變時重算 x 軸標籤密度
            args, kwargs = self._last_render
            self.category_chart(*args, **kwargs, _remember=False)

    # ------------------------------------------------------------------ 樣式

    def _style_axis(self, ax, ylabel: str = ""):
        ax.set_facecolor("none")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color((0.58, 0.70, 0.84, 0.25))
        ax.tick_params(colors=TEXT, labelsize=8, length=0)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        if ylabel:
            ax.set_ylabel(ylabel, color=AXIS, fontsize=8)

    def _legend(self, ax, handles=None):
        leg = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, 1.13), ncol=6, frameon=False,
                        fontsize=8.5, labelcolor=TEXT, handlelength=1.4, columnspacing=1.2)
        return leg

    def _x_ticks(self, ax, labels: list[str]):
        n = len(labels)
        # 日期只顯示 MM-DD,並依圖寬抽稀標籤避免重疊
        short = [lb[5:] if len(lb) == 10 and lb[4] == "-" and lb[7] == "-" else lb for lb in labels]
        width_px = self.fig.get_figwidth() * self.fig.dpi * 0.85
        max_len = max((len(x) for x in short), default=1)
        fit = max(2, int(width_px / (max_len * 7.5 + 18)))
        step = max(1, -(-n // fit))
        ax.set_xticks(range(n))
        ax.set_xticklabels([lb if i % step == 0 else "" for i, lb in enumerate(short)], rotation=0)
        ax.set_xlim(-0.6, n - 0.4 if n else 0.6)

    # ------------------------------------------------------------------ 圖表

    def category_chart(self, labels: list[str], series: list[Series], ylabels: tuple[str, str] = ("", ""),
                       unit: str = "", extra: dict[int, str] | None = None, integer_y: bool = False,
                       legend: bool = True, _remember: bool = True) -> None:
        """類別 x 軸的長條 / 折線 / 面積 / 堆疊圖,可雙 y 軸。"""
        if _remember:
            self._last_render = ((labels, series),
                                 dict(ylabels=ylabels, unit=unit, extra=extra, integer_y=integer_y, legend=legend))
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        self._style_axis(ax, ylabels[0])
        ax2 = None
        if any(s.axis == 1 for s in series):
            ax2 = ax.twinx()
            self._style_axis(ax2, ylabels[1])
            ax2.grid(False)
            ax2.spines["right"].set_visible(True)
            ax2.spines["right"].set_color((0.58, 0.70, 0.84, 0.25))
        x = list(range(len(labels)))
        bars = [s for s in series if s.kind == "bar"]
        stacked = [s for s in bars if s.stack]
        grouped = [s for s in bars if not s.stack]
        width = 0.62 if len(grouped) <= 1 else 0.7 / len(grouped)
        handles = []

        bottom = [0.0] * len(labels)
        for s in stacked:
            vals = [float(v or 0) for v in s.values]
            h = (ax if s.axis == 0 else ax2).bar(x, vals, 0.6, bottom=bottom, color=s.color, alpha=0.88,
                                                 label=s.name, linewidth=0)
            handles.append(h)
            bottom = [b + v for b, v in zip(bottom, vals)]
        for i, s in enumerate(grouped):
            offset = (i - (len(grouped) - 1) / 2) * width
            target = ax if s.axis == 0 else ax2
            h = target.bar([xi + offset for xi in x], [float(v or 0) for v in s.values], width * 0.9,
                           color=s.color, alpha=0.85, label=s.name, linewidth=0)
            handles.append(h)
        for s in series:
            if s.kind not in ("line", "area"):
                continue
            target = ax if s.axis == 0 else ax2
            xs = [xi for xi, v in zip(x, s.values) if v is not None]
            ys = [float(v) for v in s.values if v is not None]
            (h,) = target.plot(xs, ys, color=s.color, linewidth=1.8, label=s.name,
                               linestyle="--" if s.dashed else "-", marker="o" if s.marker else None,
                               markersize=3.5)
            if s.kind == "area" and xs:
                target.fill_between(xs, ys, color=s.color, alpha=0.16, linewidth=0)
            handles.append(h)

        self._x_ticks(ax, labels)
        if integer_y:
            ax.yaxis.get_major_locator().set_params(integer=True)
        if legend and series:
            self._legend(ax, handles)
        self._axes = [ax] + ([ax2] if ax2 else [])
        self._hover = _HoverInfo(labels, series, unit, extra or {})
        self._annot = None
        self.fig.subplots_adjust(left=0.07, right=0.93 if ax2 else 0.98, top=0.86, bottom=0.12)
        self.draw_idle()

    def hbar_chart(self, names: list[str], values: list[float], color: str = fmt.OK, xlabel: str = "") -> None:
        self._last_render = None
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        self._style_axis(ax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        y = list(range(len(names)))
        ax.barh(y, values, 0.55, color=color, alpha=0.85, linewidth=0)
        ax.set_yticks(y)
        ax.set_yticklabels(names)
        if xlabel:
            ax.set_xlabel(xlabel, color=AXIS, fontsize=8)
        for yi, v in zip(y, values):
            ax.text(v, yi, f" {v:,.0f}", va="center", color=TEXT, fontsize=8)
        self._hover = _HoverInfo()
        self._axes = [ax]
        self.fig.subplots_adjust(left=0.2, right=0.94, top=0.95, bottom=0.12)
        self.draw_idle()

    def donut_chart(self, items: list[tuple[str, float, str]]) -> None:
        """items: [(名稱, 值, 顏色)]"""
        self._last_render = None
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor("none")
        total = sum(v for _, v, _ in items)
        if total <= 0:
            ax.text(0.5, 0.5, "此區間沒有資料", ha="center", va="center", color=AXIS, transform=ax.transAxes)
            ax.axis("off")
        else:
            wedges, _ = ax.pie([v for _, v, _ in items], colors=[c for _, _, c in items], startangle=90,
                               counterclock=False, wedgeprops={"width": 0.36, "edgecolor": "#0d1628", "linewidth": 2})
            ax.text(0, 0.08, f"{int(total)}", ha="center", va="center", color=fmt.ACCENT, fontsize=18,
                    fontweight="bold", family="Consolas")
            ax.text(0, -0.18, "張工單", ha="center", va="center", color=AXIS, fontsize=8.5)
            labels = [f"{n}  {int(v)} ({v / total * 100:.0f}%)" for n, v, _ in items]
            ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=9,
                      labelcolor=TEXT)
            ax.set_aspect("equal")
        self._hover = _HoverInfo()
        self._axes = [ax]
        self.fig.subplots_adjust(left=0.02, right=0.62, top=0.96, bottom=0.04)
        self.draw_idle()

    def empty(self, text: str = "尚無資料") -> None:
        self._last_render = None
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.axis("off")
        ax.text(0.5, 0.5, text, ha="center", va="center", color=AXIS, transform=ax.transAxes, fontsize=10)
        self._hover = _HoverInfo()
        self.draw_idle()

    # ------------------------------------------------------------------ 滑鼠提示

    def _hide_annot(self):
        if self._annot is not None and self._annot.get_visible():
            self._annot.set_visible(False)
            self.draw_idle()

    def _on_move(self, event):
        info = self._hover
        if not info.labels or not self._axes or event.inaxes not in self._axes or event.xdata is None:
            self._hide_annot()
            return
        idx = int(round(event.xdata))
        if idx < 0 or idx >= len(info.labels):
            self._hide_annot()
            return
        lines = [info.labels[idx]]
        for s in info.series:
            v = s.values[idx] if idx < len(s.values) else None
            text = "—" if v is None else (f"{v:,.1f}" if isinstance(v, float) and not float(v).is_integer() else f"{v:,.0f}")
            lines.append(f"● {s.name}: {text}{(' ' + info.unit) if info.unit and v is not None else ''}")
        if idx in info.extra:
            lines.append(info.extra[idx])
        ax = self._axes[0]
        if self._annot is None:
            self._annot = ax.annotate("", xy=(0, 0), xytext=(12, -12), textcoords="offset points", fontsize=8.5,
                                      color="#dceaf7", va="top",
                                      bbox={"boxstyle": "round,pad=0.5", "fc": "#12203a", "ec": fmt.ACCENT,
                                            "alpha": 0.95})
        ylim = ax.get_ylim()
        self._annot.xy = (idx, ylim[0] + (ylim[1] - ylim[0]) * 0.95)
        self._annot.set_text("\n".join(lines))
        # 靠右時把提示框翻到左側
        flip = idx > len(info.labels) * 0.6
        self._annot.xyann = (-12 if flip else 12, -12)
        self._annot.set_horizontalalignment("right" if flip else "left")
        self._annot.set_visible(True)
        self.draw_idle()
