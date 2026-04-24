from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractScrollArea, QFileDialog, QLabel, QFrame, QScrollArea, QVBoxLayout, QWidget

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
    MATPLOTLIB_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - import guard for user env
    FigureCanvasQTAgg = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]
    MATPLOTLIB_AVAILABLE = False
    MATPLOTLIB_IMPORT_ERROR = str(exc)


THEMES = {
    "dark": {
        "figure_face": "#071227",
        "axes_face": "#08142a",
        "spine": "#36506d",
        "text": "#dbeafe",
        "title": "#f8fafc",
        "grid": "#29425e",
        "pattern_fill": "#7dd3fc",
        "pattern_line": "#7dd3fc",
        "threshold_fill": "#facc15",
        "measured_line": "#0ea5e9",
        "feedback_line": "#f59e0b",
        "partial_fill": "#94a3b8",
        "partial_line": "#f97316",
    },
    "light": {
        "figure_face": "#ffffff",
        "axes_face": "#ffffff",
        "spine": "#cbd5e1",
        "text": "#0f172a",
        "title": "#0f172a",
        "grid": "#cbd5e1",
        "pattern_fill": "#93c5fd",
        "pattern_line": "#2563eb",
        "threshold_fill": "#facc15",
        "measured_line": "#0f766e",
        "feedback_line": "#d97706",
        "partial_fill": "#cbd5e1",
        "partial_line": "#ea580c",
    },
}


class _ScrollFriendlyCanvas(FigureCanvasQTAgg):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return

        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()

        if isinstance(parent, QAbstractScrollArea):
            delta = event.angleDelta().y()
            if delta:
                bar = parent.verticalScrollBar()
                bar.setValue(bar.value() - delta)
                event.accept()
                return

        super().wheelEvent(event)


class AnalysisFigureWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._analysis_data: dict[str, Any] | None = None
        self._plot_specs: list[dict[str, Any]] = []
        self._theme = "dark"

        self._message = QLabel()
        self._message.setObjectName("Hint")
        self._message.setWordWrap(True)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(10)
        self._scroll.setWidget(self._host)
        self._scroll.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._message)
        layout.addWidget(self._scroll, 1)

        if MATPLOTLIB_AVAILABLE:
            self.set_message("Wybierz run i kliknij Generuj wykresy.")
        else:
            self.set_message(
                "Brakuje matplotlib. Uruchom ponownie instalację RemoteGUI, aby włączyć wykresy.\n"
                f"Szczegóły: {MATPLOTLIB_IMPORT_ERROR}"
            )

    def has_data(self) -> bool:
        return bool(self._analysis_data) and bool(self._plot_specs) and MATPLOTLIB_AVAILABLE

    def set_theme(self, theme: str) -> None:
        self._theme = theme if theme in THEMES else "dark"
        if self._analysis_data is not None:
            self.render_analysis(self._analysis_data)

    def set_message(self, text: str) -> None:
        self._message.setText(text)
        self._message.show()
        self._scroll.hide()

    def render_analysis(self, payload: dict[str, Any]) -> None:
        self._analysis_data = payload
        if not MATPLOTLIB_AVAILABLE or Figure is None or FigureCanvasQTAgg is None:
            self.set_message(
                "Brakuje matplotlib. Uruchom ponownie instalację RemoteGUI, aby włączyć wykresy."
            )
            return

        self._plot_specs = self._build_plot_specs(payload)
        if not self._plot_specs:
            self.set_message("No analysis data available for this run yet.")
            return

        self._clear_cards()
        for spec in self._plot_specs:
            card = QFrame()
            card.setObjectName("Card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 12)
            card_layout.setSpacing(8)

            title = QLabel(spec["title"])
            title.setObjectName("SectionTitle")
            card_layout.addWidget(title)

            note = str(spec.get("note") or "").strip()
            if note:
                hint = QLabel(note)
                hint.setObjectName("Hint")
                hint.setWordWrap(True)
                card_layout.addWidget(hint)

            palette = self._palette()
            figure = Figure(figsize=(8.8, 2.8), facecolor=palette["figure_face"])
            canvas = _ScrollFriendlyCanvas(figure)
            canvas.setMinimumHeight(280)
            ax = figure.subplots(1, 1)
            self._style_axes(ax)
            self._render_spec(ax, spec, include_title=False)
            figure.tight_layout(pad=1.4, rect=[0, 0.14, 1, 1])
            card_layout.addWidget(canvas)
            self._host_layout.addWidget(card)

        self._host_layout.addStretch(1)
        self._message.hide()
        self._scroll.show()

    def export_png(self) -> bool:
        if not self.has_data() or Figure is None:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz wykresy PNG", "analysis_report.png", "PNG (*.png)")
        if not path:
            return False
        figure = self._build_export_figure()
        figure.savefig(path, dpi=220, bbox_inches="tight", facecolor=figure.get_facecolor())
        figure.clear()
        return True

    def export_svg(self) -> bool:
        if not self.has_data() or Figure is None:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz wykresy SVG", "analysis_report.svg", "SVG (*.svg)")
        if not path:
            return False
        figure = self._build_export_figure()
        figure.savefig(path, format="svg", bbox_inches="tight", facecolor=figure.get_facecolor())
        figure.clear()
        return True

    def export_csv(self) -> bool:
        if self._analysis_data is None:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz dane CSV", "analysis_data.csv", "CSV (*.csv)")
        if not path:
            return False
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._csv_fieldnames())
            writer.writeheader()
            for row in self._csv_rows(self._analysis_data):
                writer.writerow(row)
        return True

    _METRIC_CARD_TITLES = {
        "duration_seconds": "Czas trwania ruchow podczas sekwencji",
        "step_length_normalized": "Dlugosc kroku",
        "max_knee_angle": "Kat kolana",
        "max_arm_angle": "Kat reki",
        "max_head_angle": "Kat glowy",
    }

    _METRIC_CHART_TITLES = {
        "duration_seconds": "Movement duration during sequence",
        "step_length_normalized": "Step length",
        "max_knee_angle": "Knee angle",
        "max_arm_angle": "Arm angle",
        "max_head_angle": "Head angle",
    }

    def _build_plot_specs(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        charts = dict(payload.get("charts", {}))
        chart_meta = dict(charts.get("meta", {}))
        event_metrics = dict(charts.get("event_metrics", {}))
        shoulders = list(charts.get("stability", {}).get("shoulders", []))
        elbows = list(charts.get("stability", {}).get("elbows", []))
        window_scores = list(charts.get("window_scores", []))

        specs: list[dict[str, Any]] = []
        for key in [
            "step_length_normalized",
            "duration_seconds",
            "max_knee_angle",
            "max_arm_angle",
            "max_head_angle",
        ]:
            metric = event_metrics.get(key)
            if metric and metric.get("points"):
                specs.append(
                    {
                        "kind": "metric",
                        "title": self._METRIC_CARD_TITLES.get(key, metric.get("title", "Metryka")),
                        "chart_title": self._METRIC_CHART_TITLES.get(key, key),
                        "note": self._metric_note(chart_meta),
                        "data": metric,
                        "meta": chart_meta,
                    }
                )
        if shoulders:
            specs.append(
                {
                    "kind": "stability_shoulders",
                    "title": "Stabilnosc barkow",
                    "chart_title": "Shoulder stability",
                    "note": "Porownanie sredniego ustawienia wzgledem wzorca.",
                    "data": shoulders,
                }
            )
        if elbows:
            specs.append(
                {
                    "kind": "stability_elbows",
                    "title": "Stabilnosc lokci",
                    "chart_title": "Elbow stability",
                    "note": "Porownanie sredniego ustawienia wzgledem wzorca.",
                    "data": elbows,
                }
            )
        if window_scores:
            note = "Wyniki policzone osobno dla kolejnych okien czasowych."
            if chart_meta.get("is_partial"):
                processed = int(chart_meta.get("processed_window_count", len(window_scores)))
                captured = int(chart_meta.get("capture_window_count", processed))
                note = (
                    f"Analiza czesciowa: przetworzono {processed} z {captured} okien. "
                    "Pionowa linia i zacienienie pokazuja nieprzetworzony koniec sesji."
                )
            specs.append(
                {
                    "kind": "window_scores",
                    "title": "Kolejnosc i wynik zbiorczy",
                    "chart_title": "Order & composite scores",
                    "note": note,
                    "data": window_scores,
                    "meta": chart_meta,
                }
            )
        return specs

    def _clear_cards(self) -> None:
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_export_figure(self):
        assert Figure is not None
        palette = self._palette()
        figure = Figure(figsize=(10.5, max(3.0, len(self._plot_specs) * 2.6)), facecolor=palette["figure_face"])
        axes = figure.subplots(len(self._plot_specs), 1, squeeze=False)
        for ax, spec in zip([row[0] for row in axes], self._plot_specs):
            self._style_axes(ax)
            self._render_spec(ax, spec, include_title=True)
        figure.tight_layout(h_pad=1.8, rect=[0, 0.04, 1, 1])
        return figure

    def _palette(self) -> dict[str, str]:
        return THEMES.get(self._theme, THEMES["dark"])

    @staticmethod
    def _safe_plot_float(value: Any, *, default: float = math.nan) -> float:
        if value is None:
            return default
        try:
            number = float(value)
        except Exception:
            return default
        return number if math.isfinite(number) else default

    def _render_spec(self, ax, spec: dict[str, Any], *, include_title: bool) -> None:
        kind = str(spec.get("kind") or "")
        chart_title = spec.get("chart_title", spec["title"]) if include_title else ""
        if kind == "metric":
            self._plot_metric(ax, spec["data"], chart_title, spec.get("meta", {}))
        elif kind == "stability_shoulders":
            self._plot_stability(ax, spec["data"], chart_title)
        elif kind == "stability_elbows":
            self._plot_stability(ax, spec["data"], chart_title)
        else:
            self._plot_window_scores(ax, spec["data"], chart_title, spec.get("meta", {}))

    def _style_axes(self, ax) -> None:
        palette = self._palette()
        ax.set_facecolor(palette["axes_face"])
        for spine in ax.spines.values():
            spine.set_color(palette["spine"])
        ax.tick_params(colors=palette["text"], labelsize=9)
        ax.grid(color=palette["grid"], alpha=0.28, linestyle="--", linewidth=0.6)

    def _metric_note(self, meta: dict[str, Any]) -> str:
        threshold = self._safe_plot_float(meta.get("live_z_threshold"), default=1.0)
        note = "Punkty sa ulozone w kolejnosci zdarzen wykrytych w runie."
        if threshold > 1.0:
            threshold_label = f"{threshold:.2f}".rstrip("0").rstrip(".")
            note += f" Niebieski pas pokazuje avg ± std, zolty pas pokazuje zakres live dla progu z = {threshold_label}."
        return note

    def _plot_metric(self, ax, metric: dict[str, Any], title: str, meta: dict[str, Any]) -> None:
        palette = self._palette()
        points = list(metric.get("points", []))
        x = [point.get("index", idx + 1) for idx, point in enumerate(points)]
        measured = [self._safe_plot_float(point.get("measured")) for point in points]
        expected = [self._safe_plot_float(point.get("expected_avg")) for point in points]
        stdev = [self._safe_plot_float(point.get("expected_stdev"), default=0.0) for point in points]
        live_z_threshold = self._safe_plot_float(meta.get("live_z_threshold"), default=1.0)
        lower = [exp - sd for exp, sd in zip(expected, stdev)]
        upper = [exp + sd for exp, sd in zip(expected, stdev)]

        if live_z_threshold > 1.0:
            threshold_lower = [exp - (sd * live_z_threshold) for exp, sd in zip(expected, stdev)]
            threshold_upper = [exp + (sd * live_z_threshold) for exp, sd in zip(expected, stdev)]
            threshold_label = f"{live_z_threshold:.2f}".rstrip("0").rstrip(".")
            ax.fill_between(
                x,
                threshold_lower,
                threshold_upper,
                color=palette["threshold_fill"],
                alpha=0.22,
                label=f"Live threshold range (avg ± {threshold_label}σ)",
            )
        ax.fill_between(x, lower, upper, color=palette["pattern_fill"], alpha=0.16, label="Reference range (avg ± std)")
        ax.plot(x, expected, color=palette["pattern_line"], linewidth=2.0, linestyle="--", marker="o", markersize=3, label="Reference avg")
        ax.plot(x, measured, color=palette["measured_line"], linewidth=2.4, marker="o", markersize=4, label="Measured")

        if title:
            ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=palette["title"])
        unit = str(metric.get("unit") or "")
        ax.set_ylabel(unit, color=palette["text"])
        ax.set_xlabel("Event order", color=palette["text"])
        self._apply_simple_xticks(ax, x)
        self._legend_below(ax, None, palette, handles=ax.get_legend_handles_labels()[0])

    _LABEL_PL_TO_EN = {
        "Lewy bark X": "L shoulder X",
        "Prawy bark X": "R shoulder X",
        "Lewy bark Y": "L shoulder Y",
        "Prawy bark Y": "R shoulder Y",
        "Lewy łokieć": "L elbow",
        "Prawy łokieć": "R elbow",
    }

    def _plot_stability(self, ax, points: list[dict[str, Any]], title: str) -> None:
        palette = self._palette()
        labels = [self._LABEL_PL_TO_EN.get(str(point.get("label") or ""), str(point.get("label") or "")) for point in points]
        x = list(range(len(points)))
        expected = [self._safe_plot_float(point.get("expected_angle_avg")) for point in points]
        measured = [self._safe_plot_float(point.get("measured_angle_avg")) for point in points]
        width = 0.36

        left_x = [value - width / 2 for value in x]
        right_x = [value + width / 2 for value in x]
        ax.bar(left_x, expected, width=width, color=palette["pattern_fill"], alpha=0.78)
        ax.bar(right_x, measured, width=width, color=palette["measured_line"], alpha=0.96)

        if title:
            ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=palette["title"])
        ax.set_ylabel("deg", color=palette["text"])
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=0, ha="center", color=palette["text"])
        self._legend_below(ax, ["Reference pattern", "Measured"], palette)

    def _plot_window_scores(self, ax, points: list[dict[str, Any]], title: str, meta: dict[str, Any]) -> None:
        palette = self._palette()
        x = [int(point.get("window_index", idx)) + 1 for idx, point in enumerate(points)]
        order_score = [self._safe_plot_float(point.get("order_score"), default=0.0) for point in points]
        composite_score = [self._safe_plot_float(point.get("composite_score"), default=0.0) for point in points]
        feedback_score = [point.get("feedback_score") for point in points]
        total_windows = max(int(meta.get("capture_window_count", 0)), max(x, default=0))
        if total_windows <= 0:
            total_windows = len(points)

        order_line, = ax.plot(x, order_score, color=palette["pattern_line"], linewidth=2.0, marker="o", markersize=4, label="Order score")
        composite_line, = ax.plot(x, composite_score, color=palette["measured_line"], linewidth=2.3, marker="o", markersize=4, label="Composite score")

        partial_line = None
        missing_indices = [int(value) for value in meta.get("missing_window_indices", []) if isinstance(value, int)]
        trailing_missing_start = meta.get("trailing_missing_start_index")
        if missing_indices:
            for missing_idx in missing_indices:
                left = missing_idx + 0.5
                right = missing_idx + 1.5
                ax.axvspan(left, right, color=palette["partial_fill"], alpha=0.16, zorder=0)
            if isinstance(trailing_missing_start, int):
                partial_line = ax.axvline(
                    trailing_missing_start + 0.5,
                    color=palette["partial_line"],
                    linewidth=1.8,
                    linestyle="--",
                    label="Session ended / not processed",
                )

        feedback_points = [
            (xx, self._safe_plot_float(score))
            for xx, score in zip(x, feedback_score)
            if isinstance(score, (int, float))
        ]
        feedback_line = None
        if feedback_points:
            ax2 = ax.twinx()
            ax2.set_ylim(1, 5.2)
            ax2.set_ylabel("Feedback (1\u20135)", color=palette["text"])
            ax2.tick_params(colors=palette["text"], labelsize=9)
            for spine in ax2.spines.values():
                spine.set_color(palette["spine"])
            (feedback_line,) = ax2.plot(
                [item[0] for item in feedback_points],
                [item[1] for item in feedback_points],
                color=palette["feedback_line"],
                linewidth=1.8,
                marker="o",
                markersize=4,
                label="Feedback (1\u20135)",
            )

        if title:
            ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=palette["title"])
        ax.set_ylim(0, 105)
        ax.set_xlim(0.5, total_windows + 0.5)
        ax.set_ylabel("Score", color=palette["text"])
        ax.set_xlabel("Time windows", color=palette["text"])
        tick_step = max(1, total_windows // 12)
        tick_positions = list(range(1, total_windows + 1, tick_step))
        tick_labels = [f"W{pos - 1}" for pos in tick_positions]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=0, ha="center", color=palette["text"])
        handles = [order_line, composite_line]
        if feedback_line is not None:
            handles.append(feedback_line)
        if partial_line is not None:
            handles.append(partial_line)
        self._legend_below(ax, None, palette, handles=handles)

    def _legend_below(self, ax, labels: list[str] | None, palette: dict[str, str], *, handles=None) -> None:
        kwargs: dict[str, Any] = {
            "loc": "upper center",
            "bbox_to_anchor": (0.5, -0.25),
            "frameon": False,
            "labelcolor": palette["text"],
            "fontsize": 8,
        }
        if handles is not None:
            kwargs["handles"] = handles
            kwargs["ncol"] = len(handles)
        elif labels is not None:
            kwargs["labels"] = labels
            kwargs["ncol"] = len(labels)
        ax.legend(**kwargs)

    def _apply_simple_xticks(self, ax, x_values: list[Any]) -> None:
        if not x_values:
            return
        max_labels = 12
        step = max(1, len(x_values) // max_labels)
        shown_x = [x_values[idx] for idx in range(0, len(x_values), step)]
        shown_labels = [str(idx + 1) for idx in range(0, len(x_values), step)]
        ax.set_xticks(shown_x)
        ax.set_xticklabels(shown_labels, color=self._palette()["text"])

    def _csv_fieldnames(self) -> list[str]:
        return [
            "group",
            "metric",
            "label",
            "index",
            "window_index",
            "event_label",
            "measured",
            "expected_avg",
            "expected_stdev",
            "order_score",
            "composite_score",
            "feedback_score",
            "feedback",
        ]

    def _csv_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        charts = dict(payload.get("charts", {}))
        for metric_name, metric in dict(charts.get("event_metrics", {})).items():
            for point in metric.get("points", []):
                rows.append(
                    {
                        "group": "event_metric",
                        "metric": metric_name,
                        "label": point.get("x_label", ""),
                        "index": point.get("index", ""),
                        "window_index": point.get("window_index", ""),
                        "event_label": point.get("event_label", ""),
                        "measured": point.get("measured", ""),
                        "expected_avg": point.get("expected_avg", ""),
                        "expected_stdev": point.get("expected_stdev", ""),
                        "order_score": "",
                        "composite_score": "",
                        "feedback_score": "",
                        "feedback": "",
                    }
                )

        for group_name in ["shoulders", "elbows"]:
            for point in charts.get("stability", {}).get(group_name, []):
                rows.append(
                    {
                        "group": f"stability_{group_name}",
                        "metric": "angle_avg",
                        "label": point.get("label", ""),
                        "index": "",
                        "window_index": "",
                        "event_label": "",
                        "measured": point.get("measured_angle_avg", ""),
                        "expected_avg": point.get("expected_angle_avg", ""),
                        "expected_stdev": point.get("expected_angle_stdev", ""),
                        "order_score": "",
                        "composite_score": "",
                        "feedback_score": "",
                        "feedback": "",
                    }
                )

        for point in charts.get("window_scores", []):
            rows.append(
                {
                    "group": "window_score",
                    "metric": "score",
                    "label": f"W{point.get('window_index', '')}",
                    "index": point.get("index", ""),
                    "window_index": point.get("window_index", ""),
                    "event_label": "",
                    "measured": "",
                    "expected_avg": "",
                    "expected_stdev": "",
                    "order_score": point.get("order_score", ""),
                    "composite_score": point.get("composite_score", ""),
                    "feedback_score": point.get("feedback_score", ""),
                    "feedback": point.get("feedback", ""),
                }
            )
        return rows
