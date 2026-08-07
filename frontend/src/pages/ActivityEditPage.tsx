import { type FormEvent, useEffect, useState } from "react";
import { useLocation, useParams } from "wouter";
import { getActivityWithEtag, updateActivity } from "../api/client";
import type {
  ActivityResource,
  AssessmentModality,
  ResponseFormat,
  StructuredJustificationMode,
} from "../api/types";
import { ErrorNotice } from "../components/Feedback";

const RESPONSE_FORMATS: ResponseFormat[] = [
  "OPEN_SHORT",
  "STRUCTURED_BULLETS",
  "CHOICE",
  "ANNOTATION_OR_DIAGRAM",
  "ORAL_EQUIVALENT",
];

export function ActivityEditPage() {
  const { activityId = "" } = useParams();
  const [, navigate] = useLocation();
  const [activity, setActivity] = useState<ActivityResource | null>(null);
  const [etag, setEtag] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    getActivityWithEtag(activityId)
      .then((result) => {
        if (!cancelled) {
          setActivity(result.activity);
          setEtag(result.etag);
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(caught);
      });
    return () => {
      cancelled = true;
    };
  }, [activityId]);

  const set = <Key extends keyof ActivityResource>(key: Key, value: ActivityResource[Key]) => {
    setActivity((current) => current ? { ...current, [key]: value } : current);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!activity || activity.status !== "DRAFT") return;
    setSaving(true);
    setError(null);
    try {
      await updateActivity(
        activity.activity_id,
        {
          title: activity.title,
          output_language: activity.output_language,
          assessment_modality: activity.assessment_modality,
          question_count: activity.question_count,
          target_total_minutes: activity.target_total_minutes,
          structured_justification_mode: activity.structured_justification_mode,
          priority_criterion_ids: activity.priority_criterion_ids ?? [],
          allowed_response_formats: activity.allowed_response_formats,
          allowed_artifact_media_types: activity.allowed_artifact_media_types,
          adaptation_policy_id: activity.adaptation_policy_id ?? null,
        },
        etag,
      );
      navigate("/activities", { replace: true });
    } catch (caught) {
      setError(caught);
    } finally {
      setSaving(false);
    }
  };

  if (!activity) {
    return <div className="content-stack"><p aria-live="polite">Cargando borrador…</p><ErrorNotice error={error} /></div>;
  }
  if (activity.status !== "DRAFT") {
    return (
      <div className="content-stack">
        <section className="error-notice" role="alert">
          <h1>Configuración congelada</h1>
          <p>La actividad dejó DRAFT; sus inputs ya no se pueden editar.</p>
        </section>
        <button className="button button-primary" onClick={() => navigate(activity.journey.continue_path)} type="button">Continuar recorrido</button>
      </div>
    );
  }

  return (
    <div className="content-stack narrow-content">
      <header className="page-heading">
        <div><span className="eyebrow">Borrador · ETag protegido</span><h1>Editar actividad</h1><p>Los cambios fallan si otra sesión actualizó esta versión.</p></div>
      </header>
      <form className="form-card" onSubmit={(event) => void submit(event)}>
        <label className="field"><span>Título</span><input maxLength={300} onChange={(event) => set("title", event.target.value)} required value={activity.title} /></label>
        <div className="form-grid form-grid-2">
          <label className="field"><span>Idioma</span><input onChange={(event) => set("output_language", event.target.value)} value={activity.output_language} /></label>
          <label className="field"><span>Modalidad</span><select onChange={(event) => set("assessment_modality", event.target.value as AssessmentModality)} value={activity.assessment_modality}><option value="WRITTEN">Escrita</option><option value="ORAL">Oral</option><option value="MIXED">Mixta</option></select></label>
          <label className="field"><span>Preguntas</span><input max={20} min={1} onChange={(event) => set("question_count", Number(event.target.value))} type="number" value={activity.question_count} /></label>
          <label className="field"><span>Minutos</span><input max={120} min={3} onChange={(event) => set("target_total_minutes", Number(event.target.value))} type="number" value={activity.target_total_minutes} /></label>
        </div>
        <fieldset className="inline-fieldset"><legend>Formatos de respuesta</legend><div className="option-grid">
          {RESPONSE_FORMATS.map((format) => <label className="check-card" key={format}><input checked={activity.allowed_response_formats.includes(format)} onChange={() => set("allowed_response_formats", activity.allowed_response_formats.includes(format) ? activity.allowed_response_formats.filter((item) => item !== format) : [...activity.allowed_response_formats, format])} type="checkbox" /><span>{format.replaceAll("_", " ")}</span></label>)}
        </div></fieldset>
        <label className="field"><span>Política de justificación</span><select onChange={(event) => set("structured_justification_mode", event.target.value as StructuredJustificationMode)} value={activity.structured_justification_mode}><option value="NOT_REQUIRED">No requerida</option><option value="SELECTED">Solo seleccionadas por el sistema</option><option value="ALL">Todas</option></select><small>La dificultad se deriva; no existe selector manual.</small></label>
        <ErrorNotice error={error} />
        <footer className="form-actions"><button className="button button-secondary" onClick={() => navigate("/activities")} type="button">Cancelar</button><button className="button button-primary" disabled={saving || activity.allowed_response_formats.length === 0} type="submit">{saving ? "Guardando…" : "Guardar borrador"}</button></footer>
      </form>
    </div>
  );
}
