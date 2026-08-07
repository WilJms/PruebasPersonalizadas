# Estado de implementación y cierre de Etapa 1

Fecha de corte documental: 2026-08-07 (America/Santiago).

## Estado del gate

La implementación de Etapas 0 y 1 está en estado **CANDIDATE_STAGE1_VERIFIED**.
Los once hallazgos P1 están cerrados sobre el candidato funcional
6374e60ce74ebb2a1ee0ec80531eab218d1b9548. El supuesto cierre documental
f982ef89a57bdcc09084acd5b7f554a36618fe3e fue rechazado por la auditoría
independiente al encontrar dos defectos y no se presenta como final. La
decisión definitiva
READY_FOR_STAGE_2 se emite únicamente después de:

1. crear el último commit documental, denominado FINAL_STAGE1_SHA;
2. construir y desplegar ese SHA exacto;
3. generar el paquete de evidencia externo;
4. completar la auditoría independiente de solo lectura.

Un commit no puede contener de forma verificable su propio hash ni los
identificadores del build que se ejecuta después de publicarlo. Por eso esos
valores finales viven en el manifest externo y no se sustituyen posteriormente
en este archivo. No se harán commits después de FINAL_STAGE1_SHA.

## Identidad del candidato verificado

| Elemento | Valor |
|---|---|
| Repositorio | WilJms/PruebasPersonalizadas |
| Rama | fix/stage1-external-readiness |
| PR | #1, abierto y draft |
| Candidato funcional | 6374e60ce74ebb2a1ee0ec80531eab218d1b9548 |
| CI push | 31199864090, SUCCESS |
| CI pull request | 31199869015, SUCCESS |
| Cloud Build | b274ccc5-ef4d-42b1-b4fe-893d77d3b898, SUCCESS |
| Digest candidato | sha256:94e6b4e786c95f0c746f48703fdd8a4f3641c9627a9fe6766e6ffc25a845967c |
| Runtime candidato | cva-web generación 9 y cva-worker generación 9, Ready, mismo digest |
| Terraform candidato | imagen 0/2/0; rotación de referencias 0/2/0; dos planes finales exit 0 |

El build fue disparado por la conexión regional al repositorio autorizado,
registró source y OCI revision del candidato, produjo dos occurrences de
provenance verificada, SLSA nivel 3, análisis terminado sin vulnerabilidades y
SBOM SPDX 2.3 ligado al digest.
Terraform continúa siendo el único escritor del deployment.

## Gates implementados

| Boundary | Estado | Evidencia resumida |
|---|---|---|
| Contratos canónicos | PASS | Schema 1.1.0, 46 roots, 112 definiciones, 231 referencias y 8 fixtures. |
| PrincipalId | PASS | Principales externos aceptan UUID Supabase sin ampliar Id globalmente. |
| OpenAPI | PASS | DTOs tipados, responses validadas, snapshot determinista y consumer/provider tests. |
| Backend y Stage 0 | PASS | 163 pruebas locales verdes; 7 PostgreSQL-only ejecutadas aparte. |
| Review UX | PASS | Blueprint, SelectedQuestion, CHOICE y Guide proyectan la trazabilidad requerida. |
| Evidence-first | PASS | Receipt durable por fragmento; replay sin URL persistida y ligado a autorización vigente; aprobación server-side. |
| Frontend | PASS | Typecheck, 19 tests, build, audit sin vulnerabilidades y Playwright crítico. |
| PostgreSQL | PASS | PG16 y PG17: 24 tablas/RLS, 2 triggers y matriz repetida dos veces sin limpieza. |
| Logging | PASS | Access log deshabilitado; 650 eventos JSON por plantilla; scan de 2.881 entradas sin capability, credencial ni payload sintético. |
| GitHub a Cloud Build | PASS | Connection, repository y trigger regionales limitados al repo; build SA sin Run Admin. |
| Supply chain | PASS E1 | Bases por digest, locks con hashes, Actions por SHA, provenance, scan y SBOM ligados al digest. |
| Terraform | PASS | Scaling superior declarado; apply revisado; dos planes vivos consecutivos exit 0. |
| Cloud runtime | PASS candidato | Health/readiness 200, privado 401, mismo digest, secretos version 2, Service/Job Ready, 1/1/0 y mock/P10 off. |
| Supabase | PASS candidato | Proyecto correcto, PostgreSQL 17, Auth sintético y membresía TEACHER tenant-scoped. |
| Cloudflare R2 | PASS candidato | Bucket privado correcto, CORS/lifecycle exactos, r2.dev off y cero dominios. |
| Browser cloud | PASS candidato | Recorrido nuevo exacto, dos reaperturas durables, evidence-first, Guide, tres exports y delta de modelo 0. |

## Correcciones principales

- lista autenticada de actividades y acciones de continuación derivadas desde
  estado durable del servidor;
- edición de actividad draft con ETag/If-Match y preflight de costo;
- blueprint y assessment review completos, dificultad derivada de solo lectura
  y separación explícita entre contenido estudiantil y datos del evaluador;
- alternativas CHOICE visibles, exactamente una mejor respuesta y
  misconceptions/rationales reservados al evaluador;
- receipt evidence-first durable por fragmento antes de aprobar;
- replay idempotente ligado a principal, rol y permiso actuales; los
  descriptores de upload, export y evidence verify no contienen capabilities;
- EvaluationGuide visible con observables, evidencia, fuentes, niveles,
  alternativas, misconceptions y cannot_infer;
- frontera OpenAPI tipada desde DTOs que componen contratos canónicos; las
  rutas con response_model retornan DTOs y no objetos Response que omitan la
  validación runtime;
- PrincipalId aplicado solo a actores/principales externos;
- logs HTTP estructurados por plantilla de ruta, sin URL, query, payload ni
  capability;
- worker separado de settings web y sin secreto de sesión;
- CI PostgreSQL 16/17, navegador E2E, dependencias fijadas y build verificable;
- Terraform convergente y trigger GitHub a Cloud Build de mínimo privilegio;
- documentos SPA no-store, assets hashados inmutables y epoch de shell que
  purga solo la caché HTTP de clientes anteriores sin borrar su sesión.

Durante la verificación del candidato, una invocación fallida de un cliente
PostgreSQL incluyó una credencial en su diagnóstico. Esa salida se invalidó y
se excluye de evidencia: la contraseña Supabase fue rotada mediante la API
oficial, la credencial anterior quedó denegada, Secret Manager recibió la
versión 2 y Terraform actualizó únicamente las referencias de secretos de
Service/Job. No se conserva ni reproduce el valor.

## Estado de Etapa 0 y Etapa 1

- E0-01 a E0-08: PASS.
- E1-01 a E1-11: PASS en implementación y candidato cloud.
- P0: 0.
- P1: 0 abiertos.
- P2/P3 residuales: solo deuda no bloqueante descrita en
  [STAGE1_FINAL_REMEDIATION_BACKLOG.md](audits/STAGE1_FINAL_REMEDIATION_BACKLOG.md).

La matriz detallada está en
[STAGE1_FINAL_ACCEPTANCE_MATRIX.md](audits/STAGE1_FINAL_ACCEPTANCE_MATRIX.md).

## Frontera preservada

La revisión humana académica del producto se conserva para blueprint y
Assessment. La verificación de ingeniería se realiza mediante pruebas,
evidencia y agentes de IA; no existe un gate humano de revisión de código.

No se implementó batch, retry/cancel general, acciones o regeneración por
pregunta, aprobación masiva, feedback/métricas E2, DOCX completo, OCR, LMS,
calificación, detección de IA, múltiples submissions ni proveedor IA real.
El modo cloud permanece mock y P10 permanece deshabilitado.

No se hizo merge ni tag. El PR debe permanecer draft hasta que el propietario
dé una instrucción posterior.
