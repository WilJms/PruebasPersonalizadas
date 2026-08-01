"""Build the deterministic synthetic PDF used by the Stage 0 corpus.

The source text is fixed and synthetic.  ReportLab runs in invariant mode so
timestamps and document identifiers cannot make fixture bytes drift between
runs.  The PDF contains native text only: no actions, links, attachments,
forms, JavaScript, images, or other active content.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .canonical import sha256_bytes


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STAGE0_ROOT = REPOSITORY_ROOT / "fixtures" / "stage0"
DEFAULT_PDF_PATH = (
    DEFAULT_STAGE0_ROOT
    / "activity_03_holdout_pdf"
    / "submission_sufficient.pdf"
)

_PDF_TITLE = "Informe sintetico: flujo de limpieza de sensores"
_PDF_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Resumen",
        (
            "El flujo recibe mediciones con un identificador de sensor y una marca temporal.",
            "Primero elimina duplicados exactos y despues calcula estadisticas por ventana.",
        ),
    ),
    (
        "Orden de transformaciones",
        (
            "La deduplicacion ocurre antes del promedio para impedir que una retransmision pese dos veces.",
            "Luego se marca como atipico un valor que excede tres desviaciones de su ventana local.",
            "El valor atipico se conserva con una bandera; no se reemplaza ni se borra silenciosamente.",
        ),
    ),
    (
        "Trazabilidad",
        (
            "Cada fila procesada conserva el identificador de origen y el codigo de transformacion aplicado.",
            "Un conteo por etapa permite reconciliar entradas, duplicados y observaciones finales.",
        ),
    ),
    (
        "Limite declarado",
        (
            "Una lectura extrema puede ser una falla o un evento real; la bandera no distingue su causa.",
            "Sin una referencia externa autorizada, el informe solo defiende que el valor requiere revision.",
        ),
    ),
)


def generate_digital_pdf(output_path: Path = DEFAULT_PDF_PATH) -> Path:
    """Generate a byte-deterministic, selectable single-page PDF fixture."""

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = A4
    canvas = Canvas(
        str(output_path),
        pagesize=A4,
        bottomup=1,
        pageCompression=0,
        invariant=1,
    )
    canvas.setTitle(_PDF_TITLE)
    canvas.setAuthor("Stage 0 synthetic fixture")
    canvas.setCreator("comprehension_verification.fixture_builder")
    canvas.setSubject("Synthetic selectable-text fixture for parser tests")

    margin = 56
    canvas.setFillColor(HexColor("#17324D"))
    canvas.rect(0, height - 96, width, 96, fill=1, stroke=0)
    canvas.setFillColor(HexColor("#FFFFFF"))
    canvas.setFont("Helvetica-Bold", 17)
    canvas.drawString(margin, height - 52, "Informe sintetico")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(margin, height - 72, "Flujo reproducible de limpieza de sensores")

    y = height - 128
    for heading, lines in _PDF_SECTIONS:
        canvas.setFillColor(HexColor("#17324D"))
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(margin, y, heading)
        y -= 19
        canvas.setFillColor(HexColor("#202A33"))
        canvas.setFont("Helvetica", 10)
        for line in lines:
            canvas.drawString(margin + 10, y, line)
            y -= 15
        y -= 11

    canvas.setStrokeColor(HexColor("#B7C4CF"))
    canvas.line(margin, 48, width - margin, 48)
    canvas.setFillColor(HexColor("#526574"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(margin, 34, "Fixture sintetico - sin datos personales - pagina 1 de 1")
    canvas.save()
    return output_path


def build_stage0_fixtures(stage0_root: Path = DEFAULT_STAGE0_ROOT) -> tuple[Path, ...]:
    """Build all generated Stage 0 fixture artifacts under ``stage0_root``."""

    pdf_path = (
        stage0_root.resolve()
        / "activity_03_holdout_pdf"
        / "submission_sufficient.pdf"
    )
    return (generate_digital_pdf(pdf_path),)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Stage 0 fixtures")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_STAGE0_ROOT,
        help="Stage 0 fixture root",
    )
    args = parser.parse_args(argv)
    for artifact in build_stage0_fixtures(args.root):
        print(f"{artifact}: {sha256_bytes(artifact.read_bytes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
