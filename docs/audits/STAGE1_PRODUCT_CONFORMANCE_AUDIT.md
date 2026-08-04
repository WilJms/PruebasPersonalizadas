# Auditoría de conformidad funcional, UX y arquitectura — Etapa 1

## Identificación de la auditoría

| Dato | Valor |
|---|---|
| Repositorio | `WilJms/PruebasPersonalizadas` |
| Remoto verificado | `https://github.com/WilJms/PruebasPersonalizadas.git` |
| Rama | `fix/stage1-external-readiness` |
| Commit auditado | `0167f14cbfe4a1192b26688a8443c5835da60bb4` |
| PR indicado por el encargo | `#1` (metadatos remotos no consultados; no eran necesarios para auditar el commit local exacto) |
| Fecha | 2026-08-04 |
| Modo | Solo lectura del producto; únicamente se crean los cuatro informes de `docs/audits/` |
| Datos usados | Fixtures y datos sintéticos no identificables |

## Resumen ejecutivo

El núcleo verificable de Etapas 0 y 1 es sustancialmente conforme: usa los modelos Pydantic canónicos sin redefinirlos, separa los pipelines de actividad y submission, conserva procedencia, valida estructura y contexto por separado, planifica exactamente `N` antes de generar, persiste Assessment y EvaluationGuide como JSON independientes, mantiene aprobaciones versionadas con ETag, diferencia job técnico de estado de dominio y deriva los exports sin nuevas llamadas al modelo. Los guardas cloud, PostgreSQL, R2, Cloud Run Jobs, P10 deshabilitado, mock obligatorio y propiedad de imagen por Terraform también están correctamente expresados y probados de forma estática.

La aplicación no está, sin embargo, alineada de extremo a extremo con su propia frontera contractual de revisión humana. El defecto funcional más visible es que una pregunta `CHOICE` válida se genera, persiste y exporta con tres alternativas, rationale del evaluador y misconception de cada distractor, pero la pantalla de revisión no muestra ninguna alternativa y aun así permite aprobar el Assessment. La misma pantalla omite formato, dificultad, minutos y obligación de justificación; la guía omite misconceptions y enlaces estructurales; y el blueprint oculta restricciones decisivas del catálogo que se está aprobando.

El segundo bloque P1 está en la frontera API: salvo el `PATCH` del blueprint, los cuerpos JSON mutables y las respuestas se publican en OpenAPI como objetos libres con `additionalProperties: true`. La validación runtime mitiga parte del riesgo, pero OpenAPI no importa los mismos roots Pydantic ni DTOs que los compongan y no existe el snapshot OpenAPI exigido por la estrategia contractual.

No se encontró una decisión genuina de producto pendiente. Las hipótesis sobre selección, justificación, respuesta abierta y dificultad tienen una interpretación única razonablemente defendible en las fuentes. Dos contradicciones documentales sobre el significado de “MVP” y la aprobación masiva se resuelven por la jerarquía: la Etapa 1 actual no incluye lote, retry/cancel, acciones por pregunta, aprobación masiva, DOCX completo, métricas/feedback, LMS, OCR, calificación ni detección de IA.

### Resultado cuantitativo

La unidad de conteo es cada uno de los 70 elementos de la matriz de esta auditoría. La severidad se asigna solamente a los 22 elementos con desviación.

| Clasificación | Cantidad |
|---|---:|
| `CONFORME` | 48 |
| `CONFORME_PERO_CONFUSO` | 4 |
| `AMBIGUO_EN_ESPECIFICACION` | 0 |
| `IMPLEMENTACION_INCOMPLETA` | 8 |
| `IMPLEMENTACION_INCORRECTA` | 5 |
| `CONTRADICCION_DOCUMENTAL` | 2 |
| `CONTROL_REDUNDANTE` | 0 |
| `CAPACIDAD_AUSENTE` | 3 |
| `CAPACIDAD_FUERA_DE_ETAPA` | 0 |
| `DECISION_DE_PRODUCTO_REQUERIDA` | 0 |
| **Total** | **70** |

| Severidad de los 22 hallazgos | Cantidad |
|---|---:|
| P0 | 0 |
| P1 | 10 |
| P2 | 11 |
| P3 | 1 |

Conclusión: la remediación puede comenzar sin una decisión de producto adicional. Antes de declarar conformidad externa deben cerrarse los diez P1 y repetirse la validación cloud con los servicios reales.

## Producto y constructo auditados

El producto es un laboratorio privado para que una persona autorizada configure una actividad, cargue su consigna y rúbrica opcional, revise y apruebe un blueprint común, procese exactamente una submission, revise un Assessment anclado en evidencia y su guía, lo apruebe y descargue vistas derivadas.

El constructo es **comprensión actual, localizada y defendible**. No es detección de IA, autoría, fraude, plagio, calificación automática ni decisión disciplinaria. Una pregunta válida debe:

- provenir de una oportunidad permitida por el blueprint;
- usar evidencia autorizada y localizable de la submission;
- exigir la operación, foco y observable previstos;
- respetar formato, dificultad, tiempo y política de justificación;
- superar validación estructural y contextual, incluido veto crítico;
- conservar una guía que explicite observables y límites de inferencia;
- permanecer bajo aprobación académica humana.

## Autoridad y fuentes leídas

Se leyó por completo el contenido versionado de `specification/`, incluido:

- `models_v1.1(1).py`, fuente primaria de 112 definiciones y 46 roots;
- `contracts.schema_v1.1(1).json`, contrastado byte a byte contra una regeneración temporal;
- `00_Especificacion_Arquitectura_v1.1(1).md`;
- `01_Prompt_Pack_v1.1(1).md`;
- `02_Contratos_y_Esquemas_v1.1(1).md`;
- `03_ADRs_v1.1(1).md`, incluidos ADR-030 a ADR-034;
- las ocho hojas de `04_Matrices_y_Costos_v1.1(1).xlsx`, con render visual;
- `05_Plan_Implementacion_v1.1(1).md`;
- `06_MVP_Entorno_Experimental(1).md`;
- `MATRIZ_CONSISTENCIA_v1.1(1).md`;
- `VALIDACION_CONTRATOS(1).md`.

También se leyeron `AGENTS.md`, los cuatro documentos preexistentes de `docs/`, el frontend completo, backend, migración, configuración, Terraform/Cloud Build/CI, parsers, gateways, validadores, renderers, fixtures y pruebas.

Se aplicó esta jerarquía: modelos Pydantic; schema generado; ADR aceptados; Plan/MVP para alcance inmediato; arquitectura; Prompt Pack; explicaciones contractuales; documentos de implementación. Cuando el documento general de MVP mezcla capacidades de varias etapas, el plan explícito y `AGENTS.md` gobiernan el gate actual.

## Método y evidencia reproducible

1. Se confirmó rama, commit, remoto y worktree limpio.
2. Se inventarió toda la superficie de especificación, código, pruebas, infraestructura y UI.
3. Se trazó cada control desde la pantalla hasta tipo frontend, API, modelo, snapshot/tabla, workflow/prompt, validación y salida. La cadena completa está en [UI_CONTRACT_TRACEABILITY.md](UI_CONTRACT_TRACEABILITY.md).
4. Se inspeccionó OpenAPI generado: 28 paths, 31 operaciones y 21 schemas publicados.
5. Se ejecutaron los flujos con FastAPI y Vite locales, SQLite temporal y object store en memoria. Se creó una actividad sintética de una pregunta, solo `CHOICE`, tres minutos y `NOT_REQUIRED`; se aprobó blueprint, se cargó una submission, se ejecutó P06-P09, se abrió la fuente, se aprobó Assessment y se descargó JSON canónico.
6. Se inspeccionó el DOM, navegación por teclado, estados ARIA, consola, diseño desktop y viewport 390 × 844.
7. Se inspeccionaron un PDF sintético de entrada y los PDF de Assessment/guía renderizados desde un snapshot canónico representativo.
8. Se ejecutaron suites backend, frontend, contrato, secretos, despliegue y Terraform.

### Resultados de ejecución

| Verificación | Resultado |
|---|---|
| Gate contractual | PASS: versión `1.1.0`, 46 roots, 112 `$defs`, 231 referencias, 8 fixtures y schema exacto |
| Backend | 138 passed, 7 skipped; los 7 corresponden a semántica PostgreSQL porque no se entregó `CVA_TEST_DATABASE_URL` |
| Frontend typecheck | PASS |
| Frontend tests | 4 archivos, 16 tests, PASS |
| Secret scan | PASS, 210 archivos versionables, sin secretos de alta confianza |
| Pruebas de despliegue | 8 passed |
| Terraform | `terraform validate` PASS |
| Consola navegador | 0 errores y 0 warnings de aplicación |
| Responsive | sin overflow horizontal en 390 × 844; jerarquía y acciones utilizables |
| PDF | PDFs A4 de una página, texto seleccionable, sin JavaScript, formularios ni cifrado; sin clipping visible en los ejemplos inspeccionados |

## Matriz completa de conformidad

La columna “Hallazgo” enlaza con la especificación exacta de remediación. `—` significa que no existe desviación que corregir.

| ID | Elemento auditado | Comportamiento observado frente a esperado | Clasificación | Sev. | Hallazgo |
|---|---|---|---|---|---|
| TC-001 | Login por invitación y sesión privada | Autorización local por allowlist y Supabase en cloud; rutas privadas protegidas. | `CONFORME` | — | — |
| TC-002 | Aviso experimental y privacidad en login | Se informa uso experimental, pero no el aviso de privacidad exigido por la pantalla canónica. | `IMPLEMENTACION_INCOMPLETA` | P2 | F-001 |
| TC-003 | Workspace y tenant scope | Actor, repositorio y objetos se resuelven por `workspace_id`/tenant. | `CONFORME` | — | — |
| TC-004 | Logout | Revoca la sesión y redirige a login. | `CONFORME` | — | — |
| TC-005 | Navegación y recuperación al reabrir | El backend lista actividades, pero la UI solo navega a “Nueva actividad”; no ofrece punto de recuperación. | `CAPACIDAD_AUSENTE` | P1 | F-002 |
| TC-006 | Título | `title`, 1–300 caracteres, llega a `ActivityConfig` y snapshot. | `CONFORME` | — | — |
| TC-007 | Idioma | `output_language` conserva el locale elegido. | `CONFORME` | — | — |
| TC-008 | Modalidad | `WRITTEN`/`ORAL`/`MIXED` se tipan y persisten correctamente. | `CONFORME` | — | — |
| TC-009 | Cantidad de preguntas | UI y contrato aplican 1–20; el planificador produce exactamente `N` o falla cerrado. | `CONFORME` | — | — |
| TC-010 | Tiempo objetivo | UI y contrato aplican 3–120 minutos; se proyecta a policy/plan. | `CONFORME` | — | — |
| TC-011 | Formatos de respuesta | Los cinco enums canónicos se desacoplan de operación cognitiva y justificación. | `CONFORME` | — | — |
| TC-012 | Etiqueta de `CHOICE` | “Selección · Con opciones justificadas” puede confundirse con justificación exigida al estudiante. | `CONFORME_PERO_CONFUSO` | P2 | F-003 |
| TC-013 | Etiqueta de `OPEN_SHORT` | Corresponde al enum, pero “Explicación concisa” puede entenderse como límite de longitud inexistente. | `CONFORME_PERO_CONFUSO` | P3 | F-004 |
| TC-014 | Política `NOT_REQUIRED`/`SELECTED`/`ALL` | Control separado, default `NOT_REQUIRED`, y policy derivada coherente. | `CONFORME` | — | — |
| TC-015 | Semántica visible de `SELECTED` | La selección determinista de templates funciona, pero la UI no explica quién selecciona ni qué preguntas quedan afectadas. | `CONFORME_PERO_CONFUSO` | P2 | F-005 |
| TC-016 | Ausencia de selector de dificultad | Correcta: dificultad/profundidad no pertenecen a `ActivityConfig`; se derivan en blueprint/oportunidad. | `CONFORME` | — | — |
| TC-017 | Formatos de artefacto | PDF digital, TXT y MD admitidos; DOCX/OCR y medios complejos no se activan. | `CONFORME` | — | — |
| TC-018 | Edición/reapertura de actividad | Existe GET/PATCH con ETag, pero no pantalla ni cliente para editar una actividad existente. | `CAPACIDAD_AUSENTE` | P2 | F-006 |
| TC-019 | Estimación previa visible | Límites/costos se registran en ledger, pero no hay estimación previa visible antes del job. | `IMPLEMENTACION_INCOMPLETA` | P2 | F-007 |
| TC-020 | Consigna obligatoria | La UI la exige y la almacena con rol `ASSIGNMENT_PROMPT`. | `CONFORME` | — | — |
| TC-021 | Rúbrica opcional | La UI y el contrato preservan su opcionalidad. | `CONFORME` | — | — |
| TC-022 | Upload privado e integridad | Capacidad corta, tamaño/MIME/hash y sellado content-addressed se verifican antes del uso. | `CONFORME` | — | — |
| TC-023 | Secreto de capacidad en logs locales | Uvicorn registra la URL completa de las rutas fake con el token firmado en el path. | `IMPLEMENTACION_INCORRECTA` | P1 | F-008 |
| TC-024 | Pipeline P01-P05 | Stages explícitos, gateway registrado, outputs canónicos y revisión P05. | `CONFORME` | — | — |
| TC-025 | Ambigüedades de actividad | Issues, evidencia, alternativas y decisión docente se muestran y persisten antes de reanudar. | `CONFORME` | — | — |
| TC-026 | Catálogo de blueprint | Dimensiones, variantes, operaciones, foco, observable y tiempo se muestran. | `CONFORME` | — | — |
| TC-027 | Restricciones completas del blueprint | La revisión oculta dificultad, formatos, obligación de justificar, anclas y requisitos de evidencia. | `IMPLEMENTACION_INCOMPLETA` | P1 | F-009 |
| TC-028 | Edición y versión de blueprint | PATCH usa el root canónico, If-Match y crea versión nueva. | `CONFORME` | — | — |
| TC-029 | Aprobación de blueprint | Revisión humana, ETag, actor/fecha, auditoría y snapshot inmutable. | `CONFORME` | — | — |
| TC-030 | Códigos visibles en blueprint/review | Se presentan enums/categorías inglesas sin capa consistente de etiquetas humanas. | `CONFORME_PERO_CONFUSO` | P2 | F-010 |
| TC-031 | Una submission por actividad | El servicio rechaza una segunda submission, conforme al gate E1. | `CONFORME` | — | — |
| TC-032 | Carga de submission | Crea, firma, completa y sella un único artefacto autorizado. | `CONFORME` | — | — |
| TC-033 | Pipeline P06-P09 | Parser → evidence → mapping/oportunidades → plan → pregunta/review → guía. | `CONFORME` | — | — |
| TC-034 | Estado técnico versus dominio | UI y backend muestran ambos conceptos por separado. | `CONFORME` | — | — |
| TC-035 | Job durable al cerrar navegador | La ejecución no depende del navegador; la arquitectura cloud usa Cloud Run Jobs. | `CONFORME` | — | — |
| TC-036 | Fail-closed | Estados de insuficiencia, incertidumbre, inviabilidad, fallo técnico y rechazo de seguridad no producen Assessment parcial. | `CONFORME` | — | — |
| TC-037 | Vista de matches/oportunidades/plan | Especificada por el MVP y ya persistida, pero no existe endpoint ni pantalla autorizada. | `CAPACIDAD_AUSENTE` | P2 | F-011 |
| TC-038 | Assessment y guía separados | Se persisten, aprueban y exportan como objetos JSON independientes. | `CONFORME` | — | — |
| TC-039 | Evidence-first mínimo E1-08 | Pregunta, ancla, localizador, dimensión, operación, scores y diagnostics son visibles. | `CONFORME` | — | — |
| TC-040 | Proyección completa de `SelectedQuestion` | UI omite formato, dificultad, minutos, justificación, score de plan y referencias contractuales. | `IMPLEMENTACION_INCOMPLETA` | P1 | F-012 |
| TC-041 | Pregunta `CHOICE` en revisión | El objeto contiene opciones válidas, pero tipos y componente no muestran ninguna; se puede aprobar igual. | `IMPLEMENTACION_INCORRECTA` | P1 | F-013 |
| TC-042 | URL temporal de fuente | Se firma el objeto sellado exacto, con corta expiración y `no-store`. | `CONFORME` | — | — |
| TC-043 | Comprobación de apertura/localizador | Un click marca la pregunta como revisada antes de confirmar carga; no cubre cada fragmento ni persiste receipt. | `IMPLEMENTACION_INCORRECTA` | P1 | F-014 |
| TC-044 | Aprobación completa del Assessment | Actor, fecha, ETag y snapshot inmutable; exports solo después de aprobar. | `CONFORME` | — | — |
| TC-045 | Ausencia de acciones por pregunta | Correcta para E1; aceptar/rechazar/editar/regenerar pertenece a E2. | `CONFORME` | — | — |
| TC-046 | Semántica de tabs | Hay `tablist`/`tab`, pero faltan ids, `aria-controls`, `tabpanel`, roving tabindex y flechas. | `IMPLEMENTACION_INCOMPLETA` | P2 | F-015 |
| TC-047 | Guía estructurada básica | Purpose, observables, alternativas, niveles y `cannot_infer` son consultables. | `CONFORME` | — | — |
| TC-048 | Trazabilidad completa de la guía | Se omiten misconceptions, `source_ids`, evidence IDs visibles y enlaces nivel→observable. | `IMPLEMENTACION_INCOMPLETA` | P1 | F-016 |
| TC-049 | Export JSON canónico | Snapshot aprobado descargable mediante URL temporal. | `CONFORME` | — | — |
| TC-050 | Export Assessment PDF | Vista derivada del snapshot; opciones `CHOICE` se incluyen en el PDF. | `CONFORME` | — | — |
| TC-051 | Export guía PDF | Vista derivada separada con propósito, observables, niveles y límites. | `CONFORME` | — | — |
| TC-052 | Export sin modelo | No repite P06-P09 ni llamadas al proveedor. | `CONFORME` | — | — |
| TC-053 | Escape de contenido hostil en renderer | Un fragmento con `<script>` se muestra como texto, sin ejecutarse. | `CONFORME` | — | — |
| TC-054 | Fuente Pydantic única | Backend carga `comprehension_verification.contracts.models`; no copia roots. | `CONFORME` | — | — |
| TC-055 | Schema generado y fixtures | Generación temporal coincide exactamente y los positivos/negativos pasan. | `CONFORME` | — | — |
| TC-056 | Requests OpenAPI | Todos los mutables salvo PATCH blueprint aparecen como `object` libre, no como root/DTO canónico. | `IMPLEMENTACION_INCORRECTA` | P1 | F-017 |
| TC-057 | Responses OpenAPI | La mayoría se publica como objeto libre o schema vacío, impidiendo contrato provider/consumer. | `IMPLEMENTACION_INCORRECTA` | P1 | F-018 |
| TC-058 | Snapshot OpenAPI | La política contractual lo exige, pero no hay test ni artefacto de snapshot. | `IMPLEMENTACION_INCOMPLETA` | P1 | F-019 |
| TC-059 | Validación runtime | Actividad y objetos de dominio se validan con modelos canónicos antes de workflow/persistencia. | `CONFORME` | — | — |
| TC-060 | Validación estructural/contextual | Se mantienen separadas y P11 no repara fallos críticos. | `CONFORME` | — | — |
| TC-061 | Planificador determinista | Selecciona exactamente `N`, reserva compatible y falla sin plan parcial. | `CONFORME` | — | — |
| TC-062 | Registry/gateway P01-P11 | Rutas explícitas, capacidades comprobadas y outputs estructurados; P10 no se ejecuta. | `CONFORME` | — | — |
| TC-063 | Modo E1 y fronteras de modelo | Mock obligatorio en cloud, sin tools/shell/red/memoria entre submissions. | `CONFORME` | — | — |
| TC-064 | Autorización y tenant isolation | Lecturas, mutaciones, jobs, evidence y exports se scopean al actor. | `CONFORME` | — | — |
| TC-065 | Health/readiness/PostgreSQL | Liveness independiente; readiness comprueba DB/migración; cloud exige `postgresql+psycopg://`. | `CONFORME` | — | — |
| TC-066 | Worker, retries e imagen cloud | Un job máximo por worker, Cloud Run `max_retries = 0`, imagen digest inmutable propiedad de Terraform. | `CONFORME` | — | — |
| TC-067 | Foco de teclado en controles custom | Inputs de 1 × 1 px y opacidad cero no trasladan un indicador `focus-visible` a la tarjeta. | `IMPLEMENTACION_INCOMPLETA` | P2 | F-020 |
| TC-068 | Aprobación masiva en documentos | Workbook/MVP la llaman MVP; Plan y `AGENTS.md` la ubican inequívocamente en E2. | `CONTRADICCION_DOCUMENTAL` | P2 | F-021 |
| TC-069 | Tabla general de pantallas/endpoints MVP | Mezcla lote, retry/cancel, acciones, métricas y feedback con el recorrido E1. | `CONTRADICCION_DOCUMENTAL` | P2 | F-022 |
| TC-070 | Capacidades E2 activas | No hay batch, retry/cancel UI, acción por pregunta, bulk approval, DOCX completo, OCR, LMS, grading ni detección de IA activos. | `CONFORME` | — | — |

## Hipótesis obligatorias resueltas

### Formato `CHOICE` y justificación

Los controles no son redundantes. `allowed_response_formats` gobierna el medio de respuesta; `structured_justification_mode` gobierna si el estudiante debe justificar. Una pregunta `CHOICE` puede ser válida con `NOT_REQUIRED`, hecho comprobado en el flujo renderizado. Cada `ChoiceOption` conserva siempre `evaluator_rationale`; cada distractor conserva una `misconception`; ninguno de esos campos implica que el estudiante deba justificar. La alternativa seleccionada por el estudiante ni siquiera se captura en E1, porque la aplicación al estudiante está fuera de etapa.

`SELECTED` requiere IDs de templates en `StructuredJustificationPolicy`. La implementación elige determinísticamente templates al construir la policy y P04 los conserva. El problema es comunicacional y de proyección: “Seleccionada” no identifica actor ni alcance, y el blueprint/review no muestra el flag resultante.

### `OPEN_SHORT`

La etiqueta corresponde exactamente al enum. “Breve” es un formato operacional de respuesta abierta acotada para una evaluación corta; no existe límite contractual de caracteres o palabras. Tiempo, dificultad y demanda cognitiva son dimensiones diferentes. Una respuesta abierta breve puede exigir alta demanda cognitiva sin convertirse automáticamente en ensayo largo. Mejorar etiqueta y ayuda no requiere contrato, nueva versión ni migración. Introducir un formato abierto largo o un límite semántico sí requeriría cambiar/versionar el contrato.

### Dificultad

No pertenece a `ActivityConfig`, por lo que la ausencia de selector es correcta. El sistema la deriva en `QuestionOpportunityTemplate`, oportunidad concreta, candidato, review semántica y `SelectedQuestion`, considerando blueprint, operación, evidencia y tiempo sin reducirla a ninguno de ellos. No hay autoridad para que el docente configure una distribución en E1. Sí debe mostrarse, sin convertirla en selector libre, cuando se aprueba el catálogo y el Assessment; esa proyección falta.

## Hallazgos por pantalla

### Login y shell

- F-001: el copy informa entorno experimental, pero no privacidad.
- F-002: el shell carece de lista de actividades y recuperación de estado aunque el backend ya ofrece `GET /activities`.

### Crear actividad

- F-003 y F-004: labels fieles al enum, pero semánticamente insuficientes.
- F-005: `SELECTED` no explica que el sistema materializa templates concretos.
- F-006: no existe edición/reapertura, pese al PATCH con ETag.
- F-007: falta estimación previa visible.
- La ausencia de dificultad, profundidad y operación como selectores es conforme.

### Blueprint

- F-009: el catálogo aprobado no expone todas las restricciones que luego gobiernan la pregunta.
- F-010: códigos internos ingleses disminuyen legibilidad, aunque no alteran datos.
- Dimensión, variante, operación, edición, review P05, versión, ETag y aprobación funcionan.

### Submission y progreso

- F-011: no existe la vista read-only de matches/oportunidades/plan.
- Estados técnico/dominio, continuidad del job y fail-closed funcionan.

### Revisión y guía

- F-012: la tarjeta no proyecta metadatos esenciales de la pregunta.
- F-013: una pregunta `CHOICE` se vuelve incompleta en UI al perder todas sus alternativas.
- F-014: la aprobación confía en un click local, no en carga/resolución verificadas de cada fragmento.
- F-015: patrón tabs incompleto.
- F-016: la guía visible pierde parte de su trazabilidad canónica.

### Accesibilidad transversal

- F-020: los controles de formatos, justificación y medios no muestran foco de teclado.
- El viewport móvil no presenta overflow ni contenido inaccesible por geometría en el recorrido probado.

## Hallazgos por contrato y arquitectura

- F-008 contradice la regla de que logs no contienen secretos/capacidades, aunque la exposición observada se limita a las rutas fake del modo local.
- F-017 y F-018 rompen la correspondencia OpenAPI ↔ Pydantic/DTO: el runtime valida mejor de lo que documenta.
- F-019 deja esa divergencia sin un gate de regresión.
- No se detectaron copias de los modelos Pydantic, edición manual del schema, mezcla de tenant, tools en modelos, P10 activo, SQLite cloud, retry funcional general ni ownership de imagen fuera de Terraform.

## Hallazgos por severidad

### P0 — 0

No se observó un defecto que, con la evidencia disponible, invalide por sí solo grounding, fail-closed, aislamiento tenant o constructo en el núcleo persistido. Los P1 de revisión impiden declarar conformidad del producto, pero los objetos canónicos y exports conservan la información.

### P1 — 10

F-002, F-008, F-009, F-012, F-013, F-014, F-016, F-017, F-018 y F-019.

### P2 — 11

F-001, F-003, F-005, F-006, F-007, F-010, F-011, F-015, F-020, F-021 y F-022.

### P3 — 1

F-004.

## Verificaciones no completadas

- No se accedió a GitHub para validar metadatos o checks actuales del PR `#1`; el commit y remoto locales sí coinciden con el encargo.
- No se accedió a GCP, Supabase ni Cloudflare, por lo que no se ejecutó un recorrido sobre el despliegue real ni se verificaron IAM, secretos, URLs R2 o continuidad real de Cloud Run Jobs. Se verificaron configuración, guardas y tests estáticos.
- Los siete tests PostgreSQL quedaron skipped por ausencia de `CVA_TEST_DATABASE_URL`; no se introdujeron credenciales porque la auditoría podía avanzar con evidencia local.
- El renderer productivo WeasyPrint no pudo ejecutarse en el host por faltar `libgobject-2.0-0`; el contenedor instala las dependencias y sus pruebas estáticas pasan. Se inspeccionó el fallback ReportLab representativo y el fixture PDF.
- No se hizo una auditoría WCAG completa con lector de pantalla ni axe; se inspeccionó DOM, teclado, foco, tabs, responsive y PDFs manualmente.

Estas limitaciones no bloquean la especificación de remediación, pero deben cerrarse antes de una declaración de readiness externa.

## Conclusión

El proyecto tiene una arquitectura E0/E1 coherente y verificable, y no necesita abrir contratos de Etapa 2 para corregir los hallazgos. La prioridad debe ser restaurar en la revisión humana toda la semántica ya presente en los objetos canónicos, convertir OpenAPI en una proyección real de Pydantic/DTO y hacer que la comprobación evidence-first sea verificable y durable. Después pueden cerrarse recuperación, accesibilidad, copy y deuda documental.

La solución exacta, cambios de versión, migraciones y criterios de cierre se detallan en [PRODUCT_ALIGNMENT_REMEDIATION_SPEC.md](PRODUCT_ALIGNMENT_REMEDIATION_SPEC.md). No hay decisiones pendientes que impidan comenzar.
