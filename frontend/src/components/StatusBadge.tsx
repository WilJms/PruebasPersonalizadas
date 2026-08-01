interface StatusBadgeProps {
  status: string;
  label?: string;
}

const FRIENDLY_STATUS: Record<string, string> = {
  QUEUED: "En cola",
  RUNNING: "En ejecución",
  SUCCEEDED: "Completado",
  FAILED: "Falló",
  NEEDS_REVIEW: "Requiere revisión",
  UPLOADED: "Cargado",
  VALIDATING: "Validando",
  PARSING: "Extrayendo evidencia",
  EVIDENCE_READY: "Evidencia lista",
  MAPPING_OPPORTUNITIES: "Mapeando oportunidades",
  PLANNING: "Planificando",
  GENERATING: "Generando preguntas",
  VALIDATING_QUESTIONS: "Validando preguntas",
  GUIDE_READY: "Guía lista",
  APPROVED: "Aprobado",
  READY: "Listo",
  INSUFFICIENT_RELEVANT_EVIDENCE: "Evidencia pertinente insuficiente",
  INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES: "Oportunidades distintas insuficientes",
  EVIDENCE_MAPPING_UNCERTAIN: "Mapeo de evidencia incierto",
  ASSESSMENT_PLAN_INFEASIBLE: "Plan inviable",
  TECHNICAL_FAILURE: "Fallo técnico",
  REJECTED_SECURITY: "Rechazado por seguridad",
  CANCELLED: "Cancelado",
};

function toneFor(status: string): string {
  if (["APPROVED", "READY", "SUCCEEDED", "GUIDE_READY"].includes(status)) return "success";
  if (["FAILED", "TECHNICAL_FAILURE", "REJECTED_SECURITY"].includes(status)) return "danger";
  if (status.includes("INSUFFICIENT") || status.includes("INFEASIBLE")) return "danger";
  if (["NEEDS_REVIEW", "EVIDENCE_MAPPING_UNCERTAIN"].includes(status)) return "warning";
  if (["RUNNING", "PARSING", "PLANNING", "GENERATING", "VALIDATING", "VALIDATING_QUESTIONS"].includes(status)) return "active";
  return "neutral";
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-${toneFor(status)}`} data-status={status}>
      <span className="status-dot" aria-hidden="true" />
      {label ?? FRIENDLY_STATUS[status] ?? status.replaceAll("_", " ")}
    </span>
  );
}

