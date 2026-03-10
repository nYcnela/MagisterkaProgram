from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

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


class AnalysisFigureWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._analysis_data: dict[str, Any] | None = None
        self._message = QLabel()
        self._message.setObjectName("Hint")
        self._message.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._message)

        self.figure = Figure(figsize=(10, 11), facecolor="#071227") if MATPLOTLIB_AVAILABLE else None
        self.canvas = FigureCanvasQTAgg(self.figure) if MATPLOTLIB_AVAILABLE else None
        if self.canvas is not None:
            self.canvas.setMinimumHeight(560)
            layout.addWidget(self.canvas, 1)
            self.canvas.hide()

        if MATPLOTLIB_AVAILABLE:
            self.set_message("Wybierz run i kliknij Generuj wykresy.")
        else:
            self.set_message(
                "Brakuje matplotlib. Uruchom ponownie instalację RemoteGUI, aby włączyć wykresy.\n"
                f"Szczegóły: {MATPLOTLIB_IMPORT_ERROR}"
            )

    def has_data(self) -> bool:
        return self._analysis_data is not None and MATPLOTLIB_AVAILABLE

    def set_message(self, text: str) -> None:
        self._message.setText(text)
        self._message.show()
        if self.canvas is not None:
            self.canvas.hide()

    def render_analysis(self, payload: dict[str, Any]) -> None:
        self._analysis_data = payload
        if not MATPLOTLIB_AVAILABLE or self.figure is None or self.canvas is None:
            self.set_message(
                "Brakuje matplotlib. Uruchom ponownie instalację RemoteGUI, aby włączyć wykresy."
            )
            return

        event_metrics = dict(payload.get("charts", {}).get("event_metrics", {}))
        shoulders = list(payload.get("charts", {}).get("stability", {}).get("shoulders", []))
        elbows = list(payload.get("charts", {}).get("stability", {}).get("elbows", []))
        window_scores = list(payload.get("charts", {}).get("window_scores", []))

        plots: list[tuple[str, Any]] = []
        for key in [
            "step_length_normalized",
            "duration_seconds",
            "max_knee_angle",
            "max_arm_angle",
            "max_head_angle",
        ]:
            metric = event_metrics.get(key)
            if metric and metric.get("points"):
                plots.append(("metric", metric))
        if shoulders:
            plots.append(("stability_shoulders", shoulders))
        if elbows:
            plots.append(("stability_elbows", elbows))
        if window_scores:
            plots.append(("window_scores", window_scores))

        if not plots:
            self.set_message("Dla tego runu nie ma jeszcze danych do analizy.")
            return

        self._message.hide()
        self.canvas.show()

        self.figure.clear()
        axes = self.figure.subplots(len(plots), 1, squeeze=False)
        axes_list = [row[0] for row in axes]

        for ax in axes_list:
            ax.set_facecolor("#08142a")
            for spine in ax.spines.values():
                spine.set_color("#36506d")
            ax.tick_params(colors="#dbeafe", labelsize=8)
            ax.yaxis.label.set_color("#dbeafe")
            ax.xaxis.label.set_color("#dbeafe")
            ax.title.set_color("#f8fafc")
            ax.grid(color="#29425e", alpha=0.28, linestyle="--", linewidth=0.6)

        for ax, (kind, data) in zip(axes_list, plots):
            if kind == "metric":
                self._plot_metric(ax, data)
            elif kind == "stability_shoulders":
                self._plot_stability(ax, data, "Stabilność barków")
            elif kind == "stability_elbows":
                self._plot_stability(ax, data, "Stabilność łokci")
            else:
                self._plot_window_scores(ax, data)

        self.figure.tight_layout(h_pad=2.0)
        self.canvas.draw_idle()

    def export_png(self) -> bool:
        if not self.has_data() or self.figure is None:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz wykresy PNG", "analysis_report.png", "PNG (*.png)")
        if not path:
            return False
        self.figure.savefig(path, dpi=220, bbox_inches="tight", facecolor=self.figure.get_facecolor())
        return True

    def export_svg(self) -> bool:
        if not self.has_data() or self.figure is None:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz wykresy SVG", "analysis_report.svg", "SVG (*.svg)")
        if not path:
            return False
        self.figure.savefig(path, format="svg", bbox_inches="tight", facecolor=self.figure.get_facecolor())
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

    def _plot_metric(self, ax, metric: dict[str, Any]) -> None:
        points = list(metric.get("points", []))
        x = [point.get("index", idx + 1) for idx, point in enumerate(points)]
        labels = [str(point.get("x_label") or point.get("event_label") or idx + 1) for idx, point in enumerate(points)]
        measured = [float(point.get("measured", 0.0)) for point in points]
        expected = [float(point.get("expected_avg", 0.0)) for point in points]
        stdev = [float(point.get("expected_stdev", 0.0)) for point in points]
        lower = [exp - sd for exp, sd in zip(expected, stdev)]
        upper = [exp + sd for exp, sd in zip(expected, stdev)]

        ax.fill_between(x, lower, upper, color="#7dd3fc", alpha=0.14)
        ax.plot(x, expected, color="#7dd3fc", linewidth=2.0, linestyle="--", marker="o", markersize=3)
        ax.plot(x, measured, color="#0ea5e9", linewidth=2.3, marker="o", markersize=4)
        ax.set_title(metric.get("title", "Metryka"), loc="left", fontsize=11, fontweight="bold")
        unit = str(metric.get("unit") or "")
        ax.set_ylabel(unit)
        self._apply_xticks(ax, x, labels)
        ax.legend(["Wzorzec", "Osoba badana"], loc="upper right", frameon=False, labelcolor="#dbeafe", fontsize=8)

    def _plot_stability(self, ax, points: list[dict[str, Any]], title: str) -> None:
        labels = [str(point.get("label") or "") for point in points]
        x = list(range(len(points)))
        expected = [float(point.get("expected_angle_avg", 0.0)) for point in points]
        measured = [float(point.get("measured_angle_avg", 0.0)) for point in points]
        width = 0.36

        left_x = [value - width / 2 for value in x]
        right_x = [value + width / 2 for value in x]
        ax.bar(left_x, expected, width=width, color="#7dd3fc", alpha=0.75)
        ax.bar(right_x, measured, width=width, color="#0ea5e9", alpha=0.95)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
        ax.set_ylabel("deg")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=18, ha="right", color="#dbeafe")
        ax.legend(["Wzorzec", "Osoba badana"], loc="upper right", frameon=False, labelcolor="#dbeafe", fontsize=8)

    def _plot_window_scores(self, ax, points: list[dict[str, Any]]) -> None:
        x = [point.get("index", idx + 1) for idx, point in enumerate(points)]
        labels = [f"okno {point.get('window_index', idx)}" for idx, point in enumerate(points)]
        order_score = [float(point.get("order_score", 0.0)) for point in points]
        composite_score = [float(point.get("composite_score", 0.0)) for point in points]
        feedback_score = [point.get("feedback_score") for point in points]

        ax.plot(x, order_score, color="#7dd3fc", linewidth=2.0, marker="o", markersize=4)
        ax.plot(x, composite_score, color="#0ea5e9", linewidth=2.2, marker="o", markersize=4)

        feedback_points = [
            (xx, float(score))
            for xx, score in zip(x, feedback_score)
            if isinstance(score, (int, float))
        ]
        if feedback_points:
            ax.plot(
                [item[0] for item in feedback_points],
                [item[1] * 20.0 for item in feedback_points],
                color="#f59e0b",
                linewidth=1.8,
                marker="o",
                markersize=4,
            )

        ax.set_ylim(0, 105)
        ax.set_title("Kolejność i wynik zbiorczy", loc="left", fontsize=11, fontweight="bold")
        ax.set_ylabel("score")
        self._apply_xticks(ax, x, labels)
        legend_labels = ["Order score", "Composite score"]
        if feedback_points:
            legend_labels.append("Feedback score x20")
        ax.legend(legend_labels, loc="upper right", frameon=False, labelcolor="#dbeafe", fontsize=8)

    def _apply_xticks(self, ax, x_values: list[Any], labels: list[str]) -> None:
        if not x_values:
            return
        max_labels = 12
        step = max(1, len(labels) // max_labels)
        shown_x = [x_values[idx] for idx in range(0, len(labels), step)]
        shown_labels = [labels[idx] for idx in range(0, len(labels), step)]
        ax.set_xticks(shown_x)
        ax.set_xticklabels(shown_labels, rotation=28, ha="right", color="#dbeafe")

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
                    "label": f"okno {point.get('window_index', '')}",
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
