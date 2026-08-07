"""Canonical JSON/HTML views with cloud WeasyPrint and local deterministic PDF."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .canonical import pretty_json, sha256_bytes
from .contracts import models as m


RENDERER_VERSION = "stage1-renderer/2.1.0"


class _InvariantCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 1
        super().__init__(*args, **kwargs)
        self.setAuthor("Comprehension Verification")
        self.setCreator(RENDERER_VERSION)
        self.setTitle("Reproducible assessment export")


@dataclass(frozen=True)
class ExportedViews:
    assessment_json: Path
    guide_json: Path
    assessment_html: Path
    guide_html: Path
    assessment_pdf: Path
    guide_pdf: Path
    manifest: Path
    hashes: dict[str, str]


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _safe_paragraph(value: str) -> str:
    return escape(value).replace("\n", "<br/>")


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Stage0Title",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceAfter=12,
            textColor="#172033",
        ),
        "heading": ParagraphStyle(
            "Stage0Heading",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            spaceBefore=10,
            spaceAfter=6,
            textColor="#2457A6",
        ),
        "body": ParagraphStyle(
            "Stage0Body",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=7,
        ),
        "anchor": ParagraphStyle(
            "Stage0Anchor",
            parent=sample["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=13,
            leftIndent=9,
            borderColor="#AEB8CC",
            borderWidth=0.5,
            borderPadding=6,
            backColor="#F5F7FB",
            spaceAfter=8,
        ),
        "notice": ParagraphStyle(
            "Stage0Notice",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            borderColor="#D8B84E",
            borderWidth=0.5,
            borderPadding=6,
            backColor="#FFF7DB",
            spaceAfter=10,
        ),
    }


def _build_assessment_pdf(assessment: m.Assessment, path: Path) -> None:
    styles = _styles()
    story: list[Any] = [
        Paragraph("Verificación de comprensión", styles["title"]),
        Paragraph(
            _safe_paragraph(
                f"ID {assessment.assessment_id} · actividad {assessment.activity_id} · referencia {assessment.subject_ref}"
            ),
            styles["body"],
        ),
        Spacer(1, 4 * mm),
    ]
    for index, question in enumerate(assessment.questions, start=1):
        story.append(Paragraph(f"Pregunta {index}", styles["heading"]))
        for fragment in question.anchor.fragments:
            story.append(
                Paragraph(
                    _safe_paragraph(fragment.display_text or "[Vista no textual]"),
                    styles["anchor"],
                )
            )
        story.append(Paragraph(_safe_paragraph(question.question_text), styles["body"]))
        for option_index, option in enumerate(question.choices, start=1):
            label = chr(64 + option_index)
            story.append(Paragraph(f"{label}. {_safe_paragraph(option.text)}", styles["body"]))
        if question.student_justification_required:
            story.append(
                Paragraph(
                    "Incluye una justificación breve referida al fragmento.", styles["body"]
                )
            )
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Assessment {assessment.assessment_id}",
        author="Comprehension Verification Stage 0",
    )
    document.build(story, canvasmaker=_InvariantCanvas)


def _build_guide_pdf(assessment: m.Assessment, guide: m.EvaluationGuide, path: Path) -> None:
    styles = _styles()
    story: list[Any] = [
        Paragraph("Guía de evaluación", styles["title"]),
        Paragraph(
            _safe_paragraph(
                f"Guía {guide.guide_id} · Assessment {guide.assessment_id} · submission {guide.submission_id}"
            ),
            styles["body"],
        ),
    ]
    if assessment.structured_justification.limited_evidence_notice_required:
        story.append(
            Paragraph(
                "La justificación no se exige en todas las preguntas; la evidencia observable tiene alcance limitado.",
                styles["notice"],
            )
        )
    for index, item in enumerate(guide.items, start=1):
        story.append(Paragraph(f"Pregunta {index} · {escape(item.question_id)}", styles["heading"]))
        story.append(
            Paragraph(f"<b>Propósito:</b> {_safe_paragraph(item.guide.purpose)}", styles["body"])
        )
        for element in item.guide.observable_elements:
            source_trace = (
                " · Fuentes: "
                + ", ".join(_safe_paragraph(value) for value in element.source_ids)
                if element.source_ids
                else " · Sin fuentes de curso (contexto CLOSED)"
            )
            story.append(
                Paragraph(
                    f"• <b>{_safe_paragraph(element.element_id)}</b> · "
                    f"{_safe_paragraph(element.description)}",
                    styles["body"],
                )
            )
            story.append(
                Paragraph(
                    "Evidencia: "
                    + ", ".join(_safe_paragraph(value) for value in element.evidence_ids)
                    + source_trace
                    + " · Requerido para nivel 2: "
                    + ("sí" if element.required_for_level_2 else "no"),
                    styles["body"],
                )
            )
        for level in item.guide.levels:
            story.append(
                Paragraph(
                    f"<b>Nivel {level.level} · {_safe_paragraph(level.label)}:</b> {_safe_paragraph(level.descriptor)}",
                    styles["body"],
                )
            )
            story.append(
                Paragraph(
                    "Observables: "
                    + (
                        ", ".join(
                            _safe_paragraph(value)
                            for value in level.observable_element_ids
                        )
                        or "ninguno"
                    ),
                    styles["body"],
                )
            )
        if item.guide.acceptable_alternatives:
            story.append(
                Paragraph(
                    "<b>Alternativas aceptables:</b> "
                    + "; ".join(
                        _safe_paragraph(value)
                        for value in item.guide.acceptable_alternatives
                    ),
                    styles["body"],
                )
            )
        if item.guide.misconceptions:
            story.append(
                Paragraph(
                    "<b>Posibles errores conceptuales a observar (no confirmados):</b> "
                    + "; ".join(
                        _safe_paragraph(value)
                        for value in item.guide.misconceptions
                    ),
                    styles["body"],
                )
            )
        if item.guide.cannot_infer:
            story.append(
                Paragraph(
                    "<b>No permite inferir:</b> "
                    + "; ".join(_safe_paragraph(value) for value in item.guide.cannot_infer),
                    styles["body"],
                )
            )
    if guide.diagnostics:
        story.append(Paragraph("Diagnósticos de la guía", styles["heading"]))
        for item in guide.diagnostics:
            story.append(
                Paragraph(
                    f"<b>{_safe_paragraph(item.code)}</b> · "
                    f"{_safe_paragraph(item.severity.value)} · "
                    f"{_safe_paragraph(item.message)}",
                    styles["body"],
                )
            )
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"EvaluationGuide {guide.guide_id}",
        author="Comprehension Verification Stage 0",
    )
    document.build(story, canvasmaker=_InvariantCanvas)


def _build_weasyprint_pdf(html_path: Path, pdf_path: Path) -> None:
    """Render the already escaped Jinja view using the ADR-032 cloud engine.

    Import stays inside the cloud-only boundary because WeasyPrint relies on
    native Pango/GLib libraries.  Local E0 regression remains runnable on
    machines without those libraries through the invariant ReportLab adapter.
    """

    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "CVA_RENDERER_MODE=weasyprint requires the container native libraries"
        ) from exc
    HTML(filename=str(html_path), base_url=str(html_path.parent)).write_pdf(
        str(pdf_path),
        pdf_identifier=sha256_bytes(html_path.read_bytes()).encode("ascii"),
    )


def render_views(
    assessment: m.Assessment,
    guide: m.EvaluationGuide,
    output_dir: Path,
) -> ExportedViews:
    """Render strictly from validated canonical objects; never invokes a model."""

    output_dir.mkdir(parents=True, exist_ok=True)
    assessment_json = output_dir / "assessment.json"
    guide_json = output_dir / "evaluation_guide.json"
    assessment_html = output_dir / "assessment.html"
    guide_html = output_dir / "evaluation_guide.html"
    assessment_pdf = output_dir / "assessment.pdf"
    guide_pdf = output_dir / "evaluation_guide.pdf"
    manifest_path = output_dir / "export_manifest.json"

    _atomic_write_text(assessment_json, pretty_json(assessment))
    _atomic_write_text(guide_json, pretty_json(guide))

    environment = Environment(
        loader=PackageLoader("comprehension_verification", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
        undefined=StrictUndefined,
    )
    assessment_rendered = environment.get_template("assessment.html").render(
        assessment=assessment
    )
    guide_rendered = environment.get_template("guide.html").render(
        guide=guide,
        assessment=assessment,
        limited_evidence_notice=assessment.structured_justification.limited_evidence_notice_required,
    )
    _atomic_write_text(assessment_html, assessment_rendered + "\n")
    _atomic_write_text(guide_html, guide_rendered + "\n")
    renderer_mode = os.environ.get("CVA_RENDERER_MODE", "reportlab").lower()
    if renderer_mode == "weasyprint":
        _build_weasyprint_pdf(assessment_html, assessment_pdf)
        _build_weasyprint_pdf(guide_html, guide_pdf)
    elif renderer_mode == "reportlab":
        _build_assessment_pdf(assessment, assessment_pdf)
        _build_guide_pdf(assessment, guide, guide_pdf)
    else:
        raise RuntimeError("CVA_RENDERER_MODE must be weasyprint or reportlab")

    output_paths = {
        "assessment_json": assessment_json,
        "guide_json": guide_json,
        "assessment_html": assessment_html,
        "guide_html": guide_html,
        "assessment_pdf": assessment_pdf,
        "guide_pdf": guide_pdf,
    }
    hashes = {name: sha256_bytes(path.read_bytes()) for name, path in output_paths.items()}
    manifest = {
        "schema_version": assessment.schema_version,
        "renderer_version": RENDERER_VERSION,
        "assessment_id": assessment.assessment_id,
        "guide_id": guide.guide_id,
        "submission_id": assessment.submission_id,
        "artifacts": {
            name: {"filename": path.name, "sha256": hashes[name]}
            for name, path in output_paths.items()
        },
    }
    _atomic_write_text(manifest_path, pretty_json(manifest))
    return ExportedViews(
        assessment_json=assessment_json,
        guide_json=guide_json,
        assessment_html=assessment_html,
        guide_html=guide_html,
        assessment_pdf=assessment_pdf,
        guide_pdf=guide_pdf,
        manifest=manifest_path,
        hashes=hashes,
    )
