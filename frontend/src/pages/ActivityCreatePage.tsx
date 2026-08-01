import { type FormEvent, useMemo, useState } from "react";
import { useLocation } from "wouter";
import {
  createActivity,
  generateBlueprint,
  uploadActivityArtifact,
} from "../api/client";
import type {
  ActivityCreateInput,
  AssessmentModality,
  ResponseFormat,
  StructuredJustificationMode,
} from "../api/types";
import { ErrorNotice } from "../components/Feedback";

const RESPONSE_FORMATS: Array<{ value: ResponseFormat; label: string; note: string }> = [
  { value: "OPEN_SHORT", label: "Respuesta abierta breve", note: "Explicación concisa" },
  { value: "STRUCTURED_BULLETS", label: "Bullets estructurados", note: "Ideas separadas" },
  { value: "CHOICE", label: "Selección", note: "Con opciones justificadas" },
  {
    value: "ANNOTATION_OR_DIAGRAM",
    label: "Anotación o diagrama",
    note: "Representación visual equivalente",
  },
  { value: "ORAL_EQUIVALENT", label: "Equivalente oral", note: "Alternativa accesible" },
];

const ARTIFACT_FORMATS = [
  { mediaType: "application/pdf", extension: "PDF", note: "PDF digital con texto seleccionable" },
  { mediaType: "text/plain", extension: "TXT", note: "Texto UTF-8" },
  { mediaType: "text/markdown", extension: "MD", note: "Markdown UTF-8" },
] as const;

const SOURCE_ACCEPT = ".pdf,.txt,.md,text/plain,text/markdown,application/pdf";

export function ActivityCreatePage() {
  const [, navigate] = useLocation();
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("es-CL");
  const [modality, setModality] = useState<AssessmentModality>("WRITTEN");
  const [questionCount, setQuestionCount] = useState(5);
  const [minutes, setMinutes] = useState(15);
  const [responseFormats, setResponseFormats] = useState<ResponseFormat[]>([
    "OPEN_SHORT",
    "STRUCTURED_BULLETS",
  ]);
  const [artifactFormats, setArtifactFormats] = useState<string[]>([
    "application/pdf",
    "text/plain",
    "text/markdown",
  ]);
  const [justification, setJustification] =
    useState<StructuredJustificationMode>("NOT_REQUIRED");
  const [assignment, setAssignment] = useState<File | null>(null);
  const [rubric, setRubric] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [step, setStep] = useState("Configuración");

  const canSubmit = useMemo(
    () =>
      title.trim().length > 0 &&
      responseFormats.length > 0 &&
      artifactFormats.length > 0 &&
      assignment !== null,
    [title, responseFormats, artifactFormats, assignment],
  );

  const toggleResponseFormat = (format: ResponseFormat) => {
    setResponseFormats((current) =>
      current.includes(format)
        ? current.filter((item) => item !== format)
        : [...current, format],
    );
  };

  const toggleArtifactFormat = (format: string) => {
    setArtifactFormats((current) =>
      current.includes(format)
        ? current.filter((item) => item !== format)
        : [...current, format],
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit || !assignment) return;
    setSubmitting(true);
    setError(null);
    try {
      const payload: ActivityCreateInput = {
        title: title.trim(),
        output_language: language,
        assessment_modality: modality,
        question_count: questionCount,
        target_total_minutes: minutes,
        allowed_response_formats: responseFormats,
        allowed_artifact_media_types: artifactFormats,
        structured_justification_mode: justification,
        context_mode: "CLOSED",
      };
      setStep("Creando actividad");
      const activity = await createActivity(payload);
      setStep("Guardando consigna");
      await uploadActivityArtifact(activity.activity_id, "ASSIGNMENT_PROMPT", assignment);
      if (rubric) {
        setStep("Guardando rúbrica");
        await uploadActivityArtifact(activity.activity_id, "RUBRIC", rubric);
      }
      setStep("Iniciando blueprint");
      const operation = await generateBlueprint(activity.activity_id);
      navigate(`/activities/${activity.activity_id}/blueprint`, {
        state: { jobId: operation.job_id },
      });
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
      setStep("Configuración");
    }
  };

  return (
    <div className="content-stack">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Nueva actividad</span>
          <h1>Configura el recorrido de verificación</h1>
          <p>
            Define las restricciones comunes. El sistema derivará la profundidad y las operaciones desde la evidencia disponible.
          </p>
        </div>
        <span className="step-pill">1 de 3 · Actividad</span>
      </header>

      <form className="activity-form" onSubmit={(event) => void submit(event)}>
        <section className="form-card">
          <div className="section-heading">
            <span className="section-number">01</span>
            <div>
              <h2>Identidad y ritmo</h2>
              <p>Parámetros confiables que comparten todas las preguntas.</p>
            </div>
          </div>

          <div className="form-grid form-grid-2">
            <label className="field field-wide">
              <span>Título</span>
              <input
                maxLength={300}
                name="title"
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Ej. Análisis de decisiones de diseño"
                required
                value={title}
              />
            </label>
            <label className="field">
              <span>Idioma de salida</span>
              <select name="output_language" onChange={(event) => setLanguage(event.target.value)} value={language}>
                <option value="es-CL">Español (Chile)</option>
                <option value="es">Español</option>
                <option value="en">English</option>
              </select>
            </label>
            <label className="field">
              <span>Modalidad</span>
              <select
                name="assessment_modality"
                onChange={(event) => setModality(event.target.value as AssessmentModality)}
                value={modality}
              >
                <option value="WRITTEN">Escrita</option>
                <option value="ORAL">Oral</option>
                <option value="MIXED">Mixta</option>
              </select>
            </label>
            <label className="field">
              <span>Número de preguntas</span>
              <input
                max={20}
                min={1}
                name="question_count"
                onChange={(event) => setQuestionCount(Number(event.target.value))}
                type="number"
                value={questionCount}
              />
            </label>
            <label className="field">
              <span>Tiempo objetivo</span>
              <div className="input-suffix">
                <input
                  max={120}
                  min={3}
                  name="target_total_minutes"
                  onChange={(event) => setMinutes(Number(event.target.value))}
                  type="number"
                  value={minutes}
                />
                <span>min</span>
              </div>
            </label>
          </div>
        </section>

        <section className="form-card">
          <div className="section-heading">
            <span className="section-number">02</span>
            <div>
              <h2>Formatos de respuesta</h2>
              <p>Elige medios equivalentes; las operaciones cognitivas no se configuran manualmente.</p>
            </div>
          </div>
          <div className="option-grid">
            {RESPONSE_FORMATS.map((format) => (
              <label className="check-card" key={format.value}>
                <input
                  checked={responseFormats.includes(format.value)}
                  name="allowed_response_formats"
                  onChange={() => toggleResponseFormat(format.value)}
                  type="checkbox"
                  value={format.value}
                />
                <span className="check-indicator" aria-hidden="true">✓</span>
                <span>
                  <strong>{format.label}</strong>
                  <small>{format.note}</small>
                </span>
              </label>
            ))}
          </div>

          <fieldset className="inline-fieldset">
            <legend>Política de justificación</legend>
            <div className="segmented-control">
              {[
                ["NOT_REQUIRED", "No requerida"],
                ["SELECTED", "Seleccionada"],
                ["ALL", "En todas"],
              ].map(([value, label]) => (
                <label key={value}>
                  <input
                    checked={justification === value}
                    name="structured_justification_mode"
                    onChange={() => setJustification(value as StructuredJustificationMode)}
                    type="radio"
                    value={value}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </section>

        <section className="form-card">
          <div className="section-heading">
            <span className="section-number">03</span>
            <div>
              <h2>Fuentes y formatos admitidos</h2>
              <p>La consigna es obligatoria. La rúbrica puede omitirse.</p>
            </div>
          </div>

          <fieldset className="inline-fieldset">
            <legend>Formatos de entrega</legend>
            <div className="format-row">
              {ARTIFACT_FORMATS.map((format) => (
                <label className="format-card" key={format.mediaType}>
                  <input
                    checked={artifactFormats.includes(format.mediaType)}
                    name="allowed_artifact_media_types"
                    onChange={() => toggleArtifactFormat(format.mediaType)}
                    type="checkbox"
                    value={format.mediaType}
                  />
                  <strong>{format.extension}</strong>
                  <span>{format.note}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="upload-grid">
            <label className={`drop-field ${assignment ? "has-file" : ""}`}>
              <span className="drop-icon" aria-hidden="true">↑</span>
              <strong>Consigna</strong>
              <span>{assignment?.name ?? "PDF digital, TXT o MD"}</span>
              <input
                accept={SOURCE_ACCEPT}
                name="assignment_prompt"
                onChange={(event) => setAssignment(event.target.files?.[0] ?? null)}
                required
                type="file"
              />
            </label>
            <label className={`drop-field ${rubric ? "has-file" : ""}`}>
              <span className="drop-icon" aria-hidden="true">↑</span>
              <strong>Rúbrica <em>opcional</em></strong>
              <span>{rubric?.name ?? "PDF digital, TXT o MD"}</span>
              <input
                accept={SOURCE_ACCEPT}
                name="rubric"
                onChange={(event) => setRubric(event.target.files?.[0] ?? null)}
                type="file"
              />
            </label>
          </div>
        </section>

        <ErrorNotice error={error} />
        <footer className="form-actions">
          <p>
            <strong>Contexto cerrado.</strong> No se usará internet ni conocimiento de curso externo.
          </p>
          <button className="button button-primary" disabled={!canSubmit || submitting} type="submit">
            {submitting ? step : "Crear y generar blueprint"}
          </button>
        </footer>
      </form>
    </div>
  );
}
