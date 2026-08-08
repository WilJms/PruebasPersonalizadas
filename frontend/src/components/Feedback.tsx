import { useEffect, useRef } from "react";
import type { Diagnostic } from "../api/types";

export function ErrorNotice({ error }: { error: unknown }) {
  const noticeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (error) noticeRef.current?.focus();
  }, [error]);
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Ocurrió un error inesperado.";
  return (
    <div className="notice notice-error" ref={noticeRef} role="alert" tabIndex={-1}>
      <strong>No pudimos completar la acción.</strong>
      <span>{message}</span>
    </div>
  );
}

export function Diagnostics({ items = [] }: { items?: Diagnostic[] }) {
  if (!items.length) return null;
  return (
    <div className="diagnostic-list" aria-label="Diagnósticos">
      {items.map((item, index) => (
        <div className={`diagnostic diagnostic-${item.severity.toLowerCase()}`} key={`${item.code}-${index}`}>
          <div>
            <strong>{item.code}</strong>
            <span>{item.severity}</span>
          </div>
          <p>{item.message}</p>
        </div>
      ))}
    </div>
  );
}
