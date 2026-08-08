import { useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import { listActivities } from "../api/client";
import type { ActivityResource } from "../api/types";
import { ErrorNotice } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";

const ACTION_LABELS: Record<ActivityResource["journey"]["next_action"], string> = {
  EDIT_ACTIVITY: "Editar borrador",
  REVIEW_BLUEPRINT: "Revisar blueprint",
  UPLOAD_SUBMISSION: "Cargar entrega",
  RUN_SUBMISSION: "Estimar e iniciar",
  VIEW_PROGRESS: "Ver progreso",
  REVIEW_ASSESSMENT: "Revisar Assessment",
};

export function ActivitiesPage() {
  const [, navigate] = useLocation();
  const [items, setItems] = useState<ActivityResource[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    listActivities()
      .then((next) => {
        if (!cancelled) {
          setItems(next);
          setError(null);
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(caught);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="content-stack">
      <header className="page-heading page-heading-actions">
        <div>
          <span className="eyebrow">Recuperación durable</span>
          <h1>Actividades</h1>
          <p>Continúa cada recorrido desde el último estado confirmado por el servidor.</p>
        </div>
        <Link className="button button-primary" to="/activities/new">Nueva actividad</Link>
      </header>

      <ErrorNotice error={error} />
      {items === null ? (
        <section className="processing-card" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Consultando estado fresco…</p>
        </section>
      ) : items.length === 0 ? (
        <section className="empty-state">
          <h2>Aún no hay actividades</h2>
          <p>Crea la primera actividad privada del entorno experimental.</p>
          <Link className="button button-primary" to="/activities/new">Crear actividad</Link>
        </section>
      ) : (
        <div className="activity-list">
          {items.map((activity) => (
            <article className="activity-card" key={activity.activity_id}>
              <header>
                <div>
                  <span className="eyebrow">Actualizada {new Date(activity.updated_at).toLocaleString()}</span>
                  <h2>{activity.title}</h2>
                </div>
                <StatusBadge status={activity.status} />
              </header>
              <dl className="activity-summary">
                <div><dt>Preguntas</dt><dd>{activity.question_count}</dd></div>
                <div><dt>Tiempo</dt><dd>{activity.target_total_minutes} min</dd></div>
                <div><dt>Blueprint</dt><dd>{activity.journey.blueprint?.status ?? "Pendiente"}</dd></div>
                <div><dt>Entrega</dt><dd>{activity.journey.submission?.status ?? "Pendiente"}</dd></div>
                <div><dt>Job técnico</dt><dd>{activity.journey.job?.status ?? "Sin job"}</dd></div>
                <div><dt>Assessment</dt><dd>{activity.journey.assessment?.status ?? "Pendiente"}</dd></div>
              </dl>
              <footer>
                {activity.status === "DRAFT" && (
                  <Link className="button button-secondary" to={`/activities/${activity.activity_id}/edit`}>
                    Editar configuración
                  </Link>
                )}
                <Link className="button button-secondary" to={`/activities/${activity.activity_id}/submissions`}>
                  Abrir lote E2
                </Link>
                <button
                  className="button button-primary"
                  onClick={() => navigate(activity.journey.continue_path)}
                  type="button"
                >
                  {ACTION_LABELS[activity.journey.next_action]}
                </button>
              </footer>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
