import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ErrorNotice } from "../components/Feedback";

export function LoginPage() {
  const { session, loading, login } = useAuth();
  const [email, setEmail] = useState("docente@example.edu");
  const [error, setError] = useState<unknown>(null);
  const [linkSent, setLinkSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  if (!loading && session) return <Navigate to="/activities/new" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await login(email.trim());
      if (result === "LINK_SENT") {
        setLinkSent(true);
        return;
      }
      const state = location.state as { from?: string } | null;
      navigate(state?.from ?? "/activities/new", { replace: true });
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-story" aria-label="Presentación del laboratorio">
        <div className="brand-lockup brand-lockup-light">
          <span className="brand-mark" aria-hidden="true">E</span>
          <div>
            <strong>Evidencia</strong>
            <span>Laboratorio docente</span>
          </div>
        </div>
        <div className="story-copy">
          <span className="eyebrow">Verificación de comprensión</span>
          <h1>Preguntas trazables, revisión humana al mando.</h1>
          <p>
            Convierte una actividad y una entrega en una evaluación breve, anclada en evidencia exacta del trabajo.
          </p>
        </div>
        <ul className="story-points">
          <li><span>01</span> Blueprint común y versionado</li>
          <li><span>02</span> Evidencia antes que preguntas</li>
          <li><span>03</span> Ninguna publicación automática</li>
        </ul>
      </section>

      <section className="login-panel">
        <form className="login-card" onSubmit={(event) => void submit(event)}>
          <span className="eyebrow">Acceso por invitación</span>
          <h2>Entrar al workspace</h2>
          <p>Usa el correo autorizado para este entorno experimental.</p>
          {linkSent && (
            <div className="notice notice-success" role="status">
              <strong>Revisa tu correo.</strong>
              <span>Enviamos un enlace de acceso. Solo funcionan usuarios previamente invitados.</span>
            </div>
          )}
          <label>
            Correo institucional
            <input
              autoComplete="email"
              name="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <ErrorNotice error={error} />
          <button className="button button-primary button-full" disabled={submitting || linkSent} type="submit">
            {submitting ? "Iniciando sesión…" : "Continuar"}
          </button>
          <small>
            El acceso local existe solo para desarrollo. En cloud la sesión es administrada por Supabase Auth.
          </small>
        </form>
      </section>
    </main>
  );
}
