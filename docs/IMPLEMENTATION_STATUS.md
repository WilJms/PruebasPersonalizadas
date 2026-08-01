# Estado de implementación

## Etapa actual

Etapa 1 — primer recorrido vertical. La Etapa 0 permanece como núcleo de
regresión aprobado. No se ha iniciado ninguna historia de Etapa 2.

La implementación alcanzó el boundary verificable sin cuentas externas: web,
API, pipelines, persistencia, adapters cloud, contenedor, IaC y pruebas con
mocks/fakes. El proveedor de IA permanece en `mock` por defecto y P10 está
deshabilitado.

## Historias de Etapa 1

| Historia | Estado de implementación | Evidencia principal |
|---|---|---|
| E1-01 | Implementada; cloud real pendiente | shell React privado, sesión local fake, adapter Supabase/JWKS, membresía invite-only, cookies HttpOnly + CSRF |
| E1-02 | Implementada | configuración canónica CLOSED, solo campos permitidos, ETag/CAS y congelación al iniciar pipeline |
| E1-03 | Implementada; R2 real pendiente | upload firmado temporal, HEAD/lectura acotada, MIME/tamaño/hash, sellado inmutable y parsers PDF digital/TXT/MD |
| E1-04 | Implementada | P01-P05 explícitos, P03 con decisiones docentes durables, validación fail-closed y blueprint review |
| E1-05 | Implementada | vista de dimensiones/variantes/operaciones/oportunidades, edición versionada, If-Match y aprobación congelada |
| E1-06 | Implementada; Cloud Run Job real pendiente | parser → P06 → plan exacto N → P07/P08 → P09 → guía/assessment; job ligado a blueprint aprobado exacto |
| E1-07 | Implementada | estados técnicos y de dominio separados, polling recuperable desde una nueva sesión de navegador |
| E1-08 | Implementada | ancla, localizador, fuente firmada, dimensión, variante, operación, scores y diagnostics antes de aprobación |
| E1-09 | Implementada | guía separada, PDFs assessment/guide y JSON canónico derivados sin nuevas llamadas al modelo |
| E1-10 | Implementada | ruta de ledger por job con route/provider/snapshot/model/effort/temperature/reason codes/tokens/latencia/costo/intento/resultado |
| E1-11 | Código e IaC implementados; verificación cloud real pendiente | imagen única React+FastAPI, worker Cloud Run Job, migración Supabase, adapter R2, Terraform y Cloud Build |

## Fronteras y garantías implementadas

- autorización por workspace y rol; un usuario Supabase válido sin membresía
  persistida no obtiene sesión de aplicación;
- mutaciones de dominio con CSRF e idempotencia atómica; los replays nunca
  persisten ni reutilizan una URL firmada como dato durable;
- inputs congelados al encolar y blueprints aprobados inmutables;
- fila de job durable antes del dispatch y worker independiente del navegador;
- artefactos sellados content-addressed y revalidados antes de generar
  evidencia, ejecutar pipelines o aprobar;
- P01-P09 detienen el recorrido cuando el output no es utilizable; no se
  persisten Assessment/Guide parciales como éxito;
- exports solo desde Assessment + EvaluationGuide aprobados y auditados;
- logs/ledger conservan IDs, hashes y métricas, no texto de estudiante,
  nombres, anclas ni secretos.

## Límites explícitos

- no se ha realizado un despliegue en GCP/Supabase/Cloudflare porque no hay
  cuentas, facturación, recursos ni secretos autorizados en este entorno;
- Supabase, R2 y Cloud Run se verifican localmente mediante adapters con fakes
  contractuales; eso no sustituye una prueba real de permisos, CORS, cuotas,
  red ni lifecycle;
- no se ha llamado a un proveedor de IA real ni se afirma calidad semántica a
  partir del mock;
- no hay lote, OCR, DOCX estructural, retry/cancel general, edición o
  regeneración por pregunta, aprobación masiva, LMS, feedback ni otras
  capacidades de Etapa 2.

Las acciones externas pendientes y el procedimiento exacto están en
`docs/EXTERNAL_SETUP.md`; los comandos realmente ejecutados se registran en
`docs/TEST_RESULTS.md`.
