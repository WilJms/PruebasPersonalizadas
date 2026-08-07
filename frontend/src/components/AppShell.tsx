import { type PropsWithChildren } from "react";
import { Link, useLocation } from "wouter";
import { useAuth } from "../auth/AuthContext";

export function AppShell({ children }: PropsWithChildren) {
  const { session, logout } = useAuth();
  const [, navigate] = useLocation();

  const signOut = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            E
          </span>
          <div>
            <strong>Evidencia</strong>
            <span>Laboratorio docente</span>
          </div>
        </div>

        <nav aria-label="Navegación principal">
          <Link to="/activities" className={(isActive) => (isActive ? "active" : "")}>
            <span className="nav-glyph" aria-hidden="true">◫</span>
            Actividades
          </Link>
          <Link to="/activities/new" className={(isActive) => (isActive ? "active" : "")}>
            <span className="nav-glyph" aria-hidden="true">＋</span>
            Nueva actividad
          </Link>
        </nav>

        <div className="stage-card">
          <span className="eyebrow">Etapa 1</span>
          <strong>Primer recorrido vertical</strong>
          <p>Una actividad, una entrega y revisión humana obligatoria.</p>
        </div>
      </aside>

      <div className="app-column">
        <header className="topbar">
          <div>
            <span className="eyebrow">Workspace experimental</span>
            <strong>{session?.workspace_name ?? "Workspace"}</strong>
          </div>
          <div className="account-menu">
            <span className="avatar" aria-hidden="true">
              {(session?.email ?? "U").slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{session?.email}</strong>
              <span>{session?.roles?.[0] ?? "Usuario autorizado"}</span>
            </div>
            <button className="button button-quiet" onClick={() => void signOut()} type="button">
              Cerrar sesión
            </button>
          </div>
        </header>
        <main className="page-area">
          {children}
        </main>
      </div>
    </div>
  );
}
