from __future__ import annotations

from pathlib import Path

from engine import PreviewImageResult, render_preview_image
from project_model import ProjectBundle
from PySide6.QtCore import QObject, QRunnable, Signal


class PreviewWorkerSignals(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str, str)


class PreviewRenderWorker(QRunnable):
    def __init__(
        self,
        *,
        job_id: int,
        bundle: ProjectBundle,
        max_edge: int,
        write_debug_masks_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.job_id = job_id
        self.bundle = bundle
        self.max_edge = max_edge
        self.write_debug_masks_dir = write_debug_masks_dir
        self.signals = PreviewWorkerSignals()

    def run(self) -> None:
        try:
            result: PreviewImageResult = render_preview_image(
                self.bundle,
                max_edge=self.max_edge,
                write_debug_masks_dir=self.write_debug_masks_dir,
                include_provenance=False,
                use_cached_sources=True,
            )
        except Exception as exc:  # pragma: no cover
            self.signals.failed.emit(self.job_id, str(exc), repr(exc))
            return
        self.signals.completed.emit(self.job_id, result)
