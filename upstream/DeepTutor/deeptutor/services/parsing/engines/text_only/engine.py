"""Text-only parser adapter implementing the ``Parser`` protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from deeptutor.runtime.isolated_worker import IsolatedWorkerError, run_in_isolated_process_sync
from deeptutor.utils.document_extractor import SUPPORTED_DOC_EXTENSIONS
from deeptutor.utils.document_validator import DocumentValidator

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError


class TextOnlyParser:
    """Built-in PDF/Office/EPUB/text-file extraction with no external engine."""

    name = "text_only"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    def resolve_config(self) -> dict[str, Any]:
        return {}

    def supported_formats(self) -> frozenset[str]:
        from integration.shared_document_extraction import SUPPORTED_FORMATS

        return SUPPORTED_DOC_EXTENSIONS | SUPPORTED_FORMATS

    def signature(self, _config: dict[str, Any]) -> ParserSignature:
        from integration.shared_document_extraction import reader_signature

        return ParserSignature.build("text_only", "deepsteam-shared-local-v2", {"reader": reader_signature()})

    def is_ready(self, _config: dict[str, Any]) -> ReadinessReport:
        from integration.shared_document_extraction import runtime_ready

        if runtime_ready():
            return ReadinessReport(ready=True)
        return ReadinessReport(
            ready=False, reason="local_reader_missing",
            message="The bundled document reader is incomplete. Repair the DeepSteam installation; no parsing API is required.",
        )

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: dict[str, Any],
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        del config
        # DeepSteam integration: the bundled local reader supplies OCR, located
        # Office text, formulas/tables and source images to every native ingest.
        from integration.shared_document_extraction import (
            SUPPORTED_FORMATS, SharedDocumentError, extract_document, write_parser_artifacts,
        )

        if Path(source_path).suffix.lower() in SUPPORTED_FORMATS:
            try:
                result = extract_document(source_path, on_output=on_output)
                write_parser_artifacts(result, workdir, Path(source_path).stem)
            except (SharedDocumentError, OSError) as exc:
                raise ParserError(str(exc)) from exc
            return
        if on_output:
            on_output(f"Extracting plain text from {Path(source_path).name}...")

        stem = Path(source_path).stem
        output_path = workdir / f"{stem}.md"
        try:
            run_in_isolated_process_sync(
                "deeptutor.runtime.worker_tasks:extract_document_to_markdown",
                str(source_path),
                str(output_path),
                kwargs={
                    "max_bytes": DocumentValidator.MAX_FILE_SIZE,
                    "max_chars": None,
                },
            )
        except (IsolatedWorkerError, OSError) as exc:
            raise ParserError(
                f"text-only extraction failed for {Path(source_path).name}: {exc}"
            ) from exc


__all__ = ["TextOnlyParser"]
