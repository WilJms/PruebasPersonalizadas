from __future__ import annotations

from pypdf import PdfReader

from comprehension_verification.exports import render_views

from .factories import assessment_and_guide


def test_exports_are_separate_escaped_and_reproducible(tmp_path) -> None:
    assessment, guide = assessment_and_guide()
    first = render_views(assessment, guide, tmp_path / "first")
    second = render_views(assessment, guide, tmp_path / "second")

    assert first.hashes == second.hashes
    student_html = first.assessment_html.read_text(encoding="utf-8")
    guide_html = first.guide_html.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in student_html
    assert "<script>alert" not in student_html
    assert "Propósito reservado al evaluador" not in student_html
    assert "Razonamiento secreto del evaluador" not in student_html
    assert "Confunde causa y consecuencia" not in student_html
    assert "Propósito reservado al evaluador" in guide_html
    assert "alcance limitado" in guide_html
    assert "element_export" in guide_html
    assert assessment.questions[0].evidence_ids[0] in guide_html
    assert "Posibles errores conceptuales a observar (no confirmados)" in guide_html
    assert "Una formulación causal equivalente" in guide_html
    assert "No permite inferir un proceso histórico" in guide_html

    student_pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(first.assessment_pdf).pages
    )
    guide_pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(first.guide_pdf).pages
    )
    assert "Propósito reservado al evaluador" not in student_pdf_text
    assert "Razonamiento secreto del evaluador" not in student_pdf_text
    assert "Propósito reservado al evaluador" in guide_pdf_text
    assert "element_export" in guide_pdf_text
    assert assessment.questions[0].evidence_ids[0] in guide_pdf_text
    assert "Posibles errores conceptuales a observar" in guide_pdf_text
    assert "Una formulación causal equivalente" in guide_pdf_text
    assert "No permite inferir un proceso histórico" in guide_pdf_text
    assert first.assessment_pdf.read_bytes().startswith(b"%PDF-")
    assert first.guide_pdf.read_bytes().startswith(b"%PDF-")


def test_canonical_json_objects_remain_separate(tmp_path) -> None:
    assessment, guide = assessment_and_guide()
    exported = render_views(assessment, guide, tmp_path)
    assessment_json = exported.assessment_json.read_text(encoding="utf-8")
    guide_json = exported.guide_json.read_text(encoding="utf-8")
    assert '"assessment_id": "assessment_export"' in assessment_json
    assert '"guide_id"' not in assessment_json
    assert '"guide_id": "guide_export"' in guide_json
    assert '"questions"' not in guide_json
