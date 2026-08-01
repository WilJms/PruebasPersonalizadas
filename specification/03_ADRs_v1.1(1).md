# Anexo C - Architecture Decision Records

**Conjunto:** `adr-set/1.1`  
Estados: `Accepted`, `Proposed`, `Superseded`. Una decisión aceptada solo cambia mediante un ADR nuevo que la sustituya.

La v1.1 conserva las decisiones no sustituidas. ADR-030 a ADR-034 reemplazan explícitamente el diseño anterior de candidatos/slots, routing dinámico, cola experimental, guía/export y aprobación exclusivamente individual.

---

## ADR-001 - Constructo y prohibición de inferir autoría

**Estado:** Accepted  
**Decisión:** El sistema mide comprensión actual demostrable de evidencia localizada del propio entregable. No produce score, etiqueta o narrativa de probabilidad de uso de IA, autoría o fraude. Toda consecuencia académica es humana.

**Contexto:** El mismo patrón de respuestas puede corresponder a múltiples historias de producción. Confundir desempeño actual con autoría crea una inferencia inválida y un riesgo alto de daño.

**Alternativas:** detector de estilo/IA; entrevista generada con veredicto automático; mantener solo el entregable. Se rechazan las dos primeras por invalidez y riesgo; la tercera no resuelve la necesidad de evidencia adicional.

**Consecuencias:** UI, prompts, schemas, guías y contratos excluyen claims de autoría; se requiere política institucional y mecanismo de apelación. El producto se posiciona como verificación educativa, no investigación disciplinaria.

---

## ADR-002 - Dos pipelines con blueprint versionado

**Estado:** Accepted  
**Decisión:** Separar pipeline de actividad (una vez) y pipeline por estudiante (N veces). El blueprint aprobado es inmutable por lote.

**Contexto:** Generar cada evaluación directamente desde consigna/rúbrica/entrega produce decisiones inconsistentes, mayor costo y menor comparabilidad.

**Alternativas:** una mega-llamada por estudiante; plantilla fija igual para todos. La primera es opaca y cara; la segunda pierde especificidad.

**Consecuencias:** se agrega paso de aprobación docente y versionamiento; se reduce costo repetido y se habilita comparación mediante un catálogo común de dimensiones, variantes y oportunidades.

---

## ADR-003 - JSON estructurado como fuente de verdad

**Estado:** Accepted  
**Decisión:** Evidence, blueprint, oportunidades, plan, preguntas, reviews, guía y assessment son objetos JSON tipados. PDF/HTML/CSV son vistas derivadas.

**Contexto:** Un PDF final no conserva relaciones suficientes para auditar, regenerar o corregir una sola etapa.

**Alternativas:** almacenar solo documentos; almacenar transcript completo de modelos. La primera pierde lineage; la segunda añade PII/costo y no crea estructura confiable.

**Consecuencias:** schemas estrictos, migraciones y renderer independiente. Un fallo de render no obliga a repetir inferencia.

---

## ADR-004 - IR específica de formato y procedencia obligatoria

**Estado:** Accepted  
**Decisión:** Usar adaptadores deterministas por formato y una IR común que conserva localizadores. Docling/visión son complementos, no única fuente.

**Contexto:** Convertir todo a texto plano destruye tablas, código, fórmulas, figuras, orden y ubicaciones.

**Alternativas:** enviar archivos directamente a un modelo multimodal; extracción universal única. Ambas reducen control y reproducibilidad.

**Consecuencias:** más ingeniería de parsers, pero anclas reproducibles y fallos localizables. Toda unidad sin procedencia queda excluida.

---

## ADR-005 - Archivos y contenido estudiantil son no confiables

**Estado:** Accepted  
**Decisión:** Cuarentena, MIME real, AV, límites y parsing sandboxed sin red. Nunca ejecutar código, macros, notebooks, imports, builds ni links. Modelos sin herramientas.

**Contexto:** Los formatos aceptan payloads activos y el texto puede contener prompt injection indirecta.

**Alternativas:** confiar en extensión; ejecutar tests para “entender” código; pedir al prompt que ignore instrucciones. Son controles insuficientes.

**Consecuencias:** algunos entregables no pueden verificarse dinámicamente; se evalúa código/outputs presentados. Aumenta aislamiento y costo de workers, reduce blast radius.

---

## ADR-006 - Contexto cerrado por defecto

**Estado:** Accepted  
**Decisión:** Preguntas/guías usan consigna, rúbrica y entrega. Corpus de curso es opt-in, versionado, con licencias y citas. Internet abierto y grounding de proveedor quedan fuera de producción.

**Contexto:** Conocimiento paramétrico o web puede introducir material no enseñado, errores, copyright y retenciones incompatibles.

**Alternativas:** web/RAG abierto siempre; solo entrega sin consigna/rúbrica. La primera debilita equidad; la segunda pierde alineación.

**Consecuencias:** mayor answerability/auditoría; ciertos dominios necesitarán habilitar corpus controlado.

---

## ADR-007 - Candidatos, doble validación y selección global

**Estado:** Superseded por ADR-030  
**Decisión:** Generar varios candidatos por slot, ejecutar validación determinista y semántica, y seleccionar el conjunto con restricciones globales.

**Contexto:** Elegir la primera pregunta plausible no controla redundancia, tiempo ni cobertura. Más llamadas no garantizan verdad si no hay validadores distintos.

**Alternativas:** una pregunta por slot; modelo único que genera y elige; votación de muchos modelos. Las tres pueden amplificar errores correlacionados.

**Consecuencias:** mayor costo y complejidad, pero fallos observables. Grounding/fuente/seguridad son vetos; no se compensan con promedio.

---

## ADR-008 - Fail closed con diagnósticos

**Estado:** Accepted  
**Decisión:** Si no hay evidencia, procedencia u oportunidades suficientes para un plan factible de exactamente \(N\), no se rellena. Se emite estado, cobertura y códigos accionables.

**Contexto:** La presión por completar N preguntas favorece alucinaciones o ítems triviales.

**Alternativas:** reducir umbral hasta completar; pregunta genérica; ocultar fallo. Se rechazan por invalidar comparabilidad y confianza.

**Consecuencias:** habrá evaluaciones ausentes, nunca parciales. Producto y soporte deben explicar `INSUFFICIENT_RELEVANT_EVIDENCE`, `INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES`, `EVIDENCE_MAPPING_UNCERTAIN` o `ASSESSMENT_PLAN_INFEASIBLE`. La tasa fail-closed es métrica de calidad del sistema/actividad, no del estudiante.

---

## ADR-009 - Separar peso de rúbrica y prioridad de verificación

**Estado:** Accepted  
**Decisión:** Conservar `grading_weight`; calcular `verification_priority` desde relevancia, centralidad, evidencia, discriminación, auditabilidad y observabilidad, con edición pedagógica.

**Contexto:** Un criterio con gran peso puede ser difícil de verificar en minutos; uno pequeño puede revelar comprensión estructural.

**Alternativas:** preguntas proporcionales al peso; distribución uniforme. Ambas ignoran capacidad de observación y evidencia.

**Consecuencias:** la institución debe calibrar factores; reportes muestran ambas variables para evitar opacidad.

---

## ADR-010 - Ancla suficiente y fiel, no “fragmento completo”

**Estado:** Accepted  
**Decisión:** Incluir el mínimo contexto fiel/autosuficiente. Puede combinar varias unidades si pronombres, encabezados, símbolos o ejes son necesarios.

**Contexto:** Un fragmento completo puede ser enorme y revelar respuestas; uno mínimo literal puede ser ininteligible.

**Alternativas:** documento completo; oración/línea aislada; resumen del modelo sin original. Se rechazan por costo, ambigüedad o pérdida de fidelidad.

**Consecuencias:** anchor builder y viewer por modalidad; score de autosuficiencia y riesgo de fuga.

---

## ADR-011 - Guía observable con niveles, no “solucionario histórico”

**Estado:** Superseded por ADR-033  
**Decisión:** Escala 0-3 con elementos observables, alternativas y `cannot_infer`. No afirmar “la razón correcta que tuvo el estudiante”.

**Contexto:** El entregable rara vez contiene una única intención histórica; una respuesta modelo rígida penaliza explicaciones válidas.

**Alternativas:** respuesta textual única; scoring totalmente automático. Se rechazan para preguntas abiertas de comprensión.

**Consecuencias:** requiere capacitación/calibración de evaluadores y medición de concordancia.

---

## ADR-012 - Monolito modular asíncrono para MVP

**Estado:** Accepted  
**Decisión:** Un backend desplegable con módulos de dominio, PostgreSQL, object storage y workflows/workers separados. No microservicios por entidad.

**Contexto:** El equipo inicial necesita velocidad y consistencia transaccional; el procesamiento sí requiere asincronía y aislamiento.

**Alternativas:** microservicios/event mesh desde día 1; monolito sin jobs durables. La primera agrega operación; la segunda falla en cargas largas/reintentos.

**Consecuencias:** límites internos y outbox preparan extracción futura. Parsers pueden desplegarse como pools aislados sin convertir todo el dominio en servicios.

**Criterios de extracción:** equipo independiente, perfil de escala distinto >=10x, boundary de seguridad/residencia o despliegue/availability separado.

---

## ADR-013 - Workflows durables e idempotencia por etapa

**Estado:** Accepted  
**Decisión:** Temporal recomendado; Celery/SQS es fallback temporal detrás de interfaz. Cada etapa usa hash de inputs/política/versión.

**Contexto:** Lotes, rate limits, revisión humana y fallos parciales requieren reanudación y signals.

**Alternativas:** requests síncronos; cron y tablas ad hoc. No ofrecen historial/semántica de retry suficientemente clara.

**Consecuencias:** curva de aprendizaje y operación; simplifica reintento, timers, cancelación, aprobación y visibilidad.

---

## ADR-014 - Gateway propio pequeño y routing gobernado

**Estado:** Accepted  
**Decisión:** Adapter sobre SDKs oficiales con registry de prompts/schemas, model routes, ledger de tokens/costo y políticas de región/retención. No framework agentic.

**Contexto:** El flujo es predecible y sin herramientas; un framework de agentes agrega superficie, dependencia y opacidad.

**Alternativas:** SDK directo disperso; framework de agentes; proxy de terceros. Se rechazan por gobernanza o datos.

**Consecuencias:** código adicional acotado; permite cambiar proveedor sin prometer portabilidad perfecta. Cada modelo necesita eval propia.

---

## ADR-015 - Routing Luna/Terra/Sol, bake-off antes del lock-in

**Estado:** Superseded por ADR-031  
**Decisión default:** Luna para bajo riesgo, Terra para semántica/generación y Sol para <=20% de casos escalados. Benchmark ciego contra Gemini 3.5 Flash y Claude Sonnet 5/Opus 4.8.

**Contexto:** Los precios/benchmarks generales no predicen grounding pedagógico en datos propios. Un único modelo caro desperdicia presupuesto.

**Alternativas:** elegir el líder de benchmark; multi-proveedor activo desde MVP; fine-tuning. Se difieren por falta de eval, complejidad/privacidad y evolución de plataformas.

**Consecuencias:** la arquitectura puede implementarse antes, pero el proveedor de producción queda condicionado al gate. No usar Fable en ZDR por retención obligatoria.

---

## ADR-016 - Revisión docente obligatoria y no grade passback MVP

**Estado:** Superseded por ADR-034  
**Decisión:** Todas las evaluaciones pasan por revisión/aprobación humana. El MVP exporta; no escribe nota ni sanción al LMS.

**Contexto:** El producto aún no tiene validación, y errores pueden afectar derechos/nota.

**Alternativas:** autopublicar preguntas/nota; revisión por muestra. Se difieren hasta alcanzar gates y definir uso.

**Consecuencias:** costo humano mayor y menor throughput; proporciona datos de defectos y protege el piloto. Reducir revisión requerirá ADR nuevo.

---

## ADR-017 - Carga manual antes de LMS; LTI + APIs después

**Estado:** Accepted  
**Decisión:** MVP manual. V2 usa LTI 1.3 para launch/context y adaptadores de API para archivos/rúbricas; Canvas primero según piloto.

**Contexto:** LTI Advantage no garantiza que cada plataforma exponga todos los adjuntos/rúbricas. Integrar tres LMS antes de validar el producto es alto costo.

**Alternativas:** LTI-only; conectores de los tres LMS desde inicio; scraping. LTI-only es insuficiente, conectores tempranos distraen, scraping es frágil/prohibible.

**Consecuencias:** operación manual al inicio; interfaz de conector y mappings se diseñan para no reescribir dominio.

---

## ADR-018 - Aislamiento multi-tenant y despliegue dedicado opcional

**Estado:** Accepted  
**Decisión:** `tenant_id` obligatorio, RLS, object prefixes, authz central y pruebas de aislamiento. Tenants de alto control pueden usar cuenta/proyecto/DB/keys dedicados.

**Contexto:** La mezcla de trabajos estudiantiles es un fallo crítico; no todos los clientes justifican infraestructura separada.

**Alternativas:** base por tenant siempre; aislamiento solo en aplicación. La primera eleva operación; la segunda es insuficiente.

**Consecuencias:** queries e índices incluyen tenant; migrations y analytics respetan límites; se ofrece tier dedicado.

---

## ADR-019 - Retención mínima, seudonimización y no entrenamiento

**Estado:** Accepted  
**Decisión:** Seudonimizar antes del model gateway, enviar paquetes mínimos, aplicar lifecycle y bloquear rutas incompatibles. No usar datos para entrenamiento/fine-tuning por defecto.

**Contexto:** Entregables y respuestas son registros educativos y pueden contener PII/secretos involuntarios.

**Alternativas:** conservar todo para mejorar el modelo; confiar solo en política del proveedor. Se rechazan por finalidad y riesgo.

**Consecuencias:** menor dataset espontáneo; evals requieren autorización/desidentificación. Batch/cache/File API dependen de política.

---

## ADR-020 - Cambios probabilísticos gobernados por evals

**Estado:** Accepted  
**Decisión:** Modelo, prompt, schema y política se versionan; golden suite, shadow/canary y rollback son obligatorios para promover.

**Contexto:** Los proveedores actualizan alias y comportamiento; una salida válida puede degradarse semánticamente.

**Alternativas:** usar alias “latest” sin evaluación; tests manuales ocasionales. Se rechazan por irreproducibilidad.

**Consecuencias:** costo permanente de evals y snapshots; reduce regresiones silenciosas y lock-in.

---

## ADR-021 - No almacenar chain-of-thought

**Estado:** Accepted  
**Decisión:** Solicitar justificaciones breves referidas a evidencia, no razonamiento interno extenso. Ledger conserva hashes, métricas y decisiones.

**Contexto:** Chain-of-thought no es una explicación garantizada, puede contener datos sensibles y aumenta retención/costo.

**Alternativas:** almacenar transcript completo para auditoría; no registrar nada. La primera sobreexpone; la segunda impide lineage.

**Consecuencias:** auditoría se basa en evidencia, contratos, checks y decisiones observables, no en narrativas internas del modelo.

---

## ADR-022 - Accesibilidad como constraint del blueprint

**Estado:** Accepted  
**Decisión:** WCAG 2.2 AA para producto; alternativas de respuesta se modelan explícitamente y preservan el constructo.

**Contexto:** Un único medio puede medir barreras de acceso en vez de comprensión.

**Alternativas:** adaptar manualmente al final; permitir cualquier modalidad sin equivalencia. Ambas generan inconsistencia.

**Consecuencias:** más metadatos/reglas y pruebas con usuarios; mejor equidad y comparabilidad.

---

## ADR-023 - Embeddings son índice, no evidencia

**Estado:** Accepted  
**Decisión:** Búsqueda híbrida puede usar embeddings, pero toda selección se resuelve al texto/estructura y localizador fuente antes de generar/validar.

**Contexto:** Similitud vectorial no prueba relación pedagógica ni fidelidad; embeddings también tienen costo/privacidad.

**Alternativas:** vector DB como fuente; no usar recuperación. La primera es opaca, la segunda puede ser ineficiente en entregas largas.

**Consecuencias:** índice reconstruible, filtrado por tenant/versión y pruebas de recall; un fallo vectorial puede degradar a búsqueda estructural.

---

## ADR-024 - Batch solo bajo política compatible

**Estado:** Accepted  
**Decisión:** Batch/Flex es optimización opt-in para trabajos no urgentes; se bloquea si retención/ZDR/latencia lo impiden.

**Contexto:** Ahorra aproximadamente 50% en precios publicados, pero puede conservar estado y tardar hasta horas.

**Alternativas:** siempre batch; nunca batch. Ninguna refleja diferencias de tenant/carga.

**Consecuencias:** cost model y router incluyen batch share; la UI muestra plazo y política.

---

## ADR-025 - Cola simple y frontera de workflows en el entorno experimental

**Estado:** Superseded por ADR-032  
**Decisión:** Para Etapas 0-2 se usa una cola simple con workers y estado durable en PostgreSQL/Redis administrado. El dominio depende de una interfaz `JobRunner`, claves idempotentes y `stage_runs`; Temporal no es requisito de arranque. Temporal o un motor equivalente se evalúa en preparación de producto cuando existan señales reales de workflows largos, signals humanos, volumen o recuperación compleja.

**Contexto:** ADR-013 identifica correctamente la necesidad institucional de durabilidad, pero operar Temporal desde el primer recorrido vertical puede consumir una fracción desproporcionada del trabajo de dos desarrolladores.

**Alternativas:** Temporal desde el primer sprint; requests síncronos; cron ad hoc. La primera se difiere; las otras dos no ofrecen progreso/retry adecuados.

**Consecuencias:** el prototipo implementa `JobStatus`, `SubmissionProcessingState`, retry por clase, cancelación básica y stage keys. La interfaz evita acoplar dominio a Celery/RQ/Arq. Este ADR estrecha ADR-013 para el experimento, no lo invalida como arquitectura objetivo.

---

## ADR-026 - Autenticación y tenancy mínimos con seams futuros

**Estado:** Accepted  
**Decisión:** El experimento usa autenticación administrada simple y roles `OWNER`, `TEACHER`, `ASSISTANT` dentro de uno o pocos workspaces controlados. `tenant_id` permanece en contratos y tablas, pero SAML, SCIM, RLS multiinstitucional exhaustiva, branding, cuentas dedicadas y administración jerárquica quedan fuera.

**Contexto:** ADR-018 sigue siendo correcto para un SaaS institucional, pero su implementación completa no valida calidad pedagógica ni utilidad del pipeline.

**Alternativas:** eliminar tenant de los datos; construir aislamiento institucional completo. La primera crea una migración peligrosa; la segunda sobredimensiona el MVP experimental.

**Consecuencias:** controles de autorización y pruebas de acceso siguen siendo obligatorios. La preparación de producto decide el nivel real de aislamiento a partir del piloto y requisitos contractuales.

---

## ADR-027 - Formatos por anillos de validación

**Estado:** Accepted  
**Decisión:** El primer prototipo soporta PDF digital, DOCX, TXT y Markdown. La ampliación posterior del entorno experimental prioriza PDF escaneado/OCR, PPTX, CSV/XLSX y código de texto/ZIP seguro según corpus. IPYNB, imágenes complejas, audio/video, CAD y binarios permanecen en la arquitectura futura.

**Contexto:** La hipótesis central puede probarse con documentos frecuentes y parsers de estructura controlable. Soportar correctamente todos los adaptadores de ADR-004 antes del vertical slice eleva costo, seguridad y superficie de pruebas.

**Alternativas:** solo texto plano; todos los formatos de v1.0 desde sprint uno. La primera reduce demasiado el valor de prueba; la segunda posterga la evaluación pedagógica.

**Consecuencias:** `allowed_artifact_media_types` y la IR no se restringen a estos formatos. Cada formato nuevo exige corpus golden, localizadores, límites de seguridad, viewer y criterio de salida antes de habilitarse.

---

## ADR-028 - Pydantic como fuente primaria única de contratos

**Estado:** Accepted  
**Decisión:** `models_v1.1.py` es la fuente primaria. `contracts.schema_v1.1.json` se genera de `CONTRACT_MODELS`; documentación, fixtures y OpenAPI consumen los mismos nombres. Está prohibido editar manualmente el bundle generado.

**Contexto:** La v1.0 mantenía Pydantic y JSON Schema sincronizados, pero prompts referían roots ausentes y campos divergentes. Dos fuentes manuales no detectan ese borde.

**Alternativas:** JSON Schema primario; dos fuentes con revisión humana. Ambas son válidas en abstracto, pero cambian el stack actual o permiten drift.

**Consecuencias:** CI regenera y compara, valida ejemplos, resuelve `$refs` y falla ante un root usado por prompts que no esté exportado. `BlueprintReview`, `AssessmentPlan`, `EvaluationGuide`, requests, policies, envelope y reparación se vuelven contratos explícitos.

---

## ADR-029 - El entregable inmediato es un laboratorio, no el SaaS institucional

**Estado:** Accepted  
**Decisión:** El alcance de implementación v1.1 es una aplicación web experimental para carga manual, configuración, blueprint, ejecución, inspección, revisión, regeneración localizada, exportación y métricas. No incluye LMS, LTI, grade passback, facturación, SAML/SCIM, Kubernetes, microservicios, HA institucional ni calificación automática.

**Contexto:** El riesgo principal todavía es demostrar calidad, aceptación docente y validez del flujo; las capacidades institucionales no reducen esa incertidumbre.

**Alternativas:** demo por scripts sin interfaz; producto SaaS completo. La primera dificulta observar uso docente real; la segunda mezcla validación con escalamiento/comercialización.

**Consecuencias:** el monolito conserva límites de dominio y contratos que permiten evolucionar. Toda capacidad institucional requiere un gate del piloto y, cuando cambie riesgo o constructo, un ADR nuevo.

---

## ADR-030 - Catálogo de oportunidades y plan atómico antes de generar

**Estado:** Accepted; sustituye ADR-007 y precisa ADR-002/ADR-008  
**Decisión:** El blueprint es un catálogo independiente de `question_count`: dimensiones evaluables, variantes de evidencia, operaciones soportadas y oportunidades template. Para cada submission se mapea `dimensión -> variante -> evidence_ids`, se instancian oportunidades y un planificador determinista selecciona exactamente \(N\) primarias de alta calidad y una reserva pequeña antes de generar. La función combina prioridad de actividad, ajuste a evidencia y calidad, con penalizaciones de reutilización/redundancia. Prefiere diversidad, pero nunca obliga a escoger una oportunidad peor.

**Contexto:** Crear varios candidatos por slot acopla el blueprint a \(N\), gasta llamadas antes de resolver cobertura y puede producir conjuntos parciales o redundantes. La evidencia real de cada submission debe determinar qué oportunidades son viables.

**Alternativas:** slots fijos con sustituciones; 3-5 candidatos por slot y selector posterior; una llamada que genera el examen completo. Se rechazan por rigidez, costo u opacidad.

**Consecuencias:** desaparecen `candidate_multiplier`, los rangos de candidatos y `READY_WITH_GAPS`. Si no existe un plan de exactamente \(N\), no se genera ninguna pregunta y se usa uno de cuatro diagnósticos específicos. P07 genera una pregunta por oportunidad; una falla usa una reserva localizada y nunca amplía una operación no soportada.

---

## ADR-031 - Resolvedor determinista de rutas y matriz P01-P11

**Estado:** Accepted; sustituye ADR-015 y precisa ADR-014  
**Decisión:** El router no elige dinámicamente el “mejor modelo”. Resuelve una configuración aprobada `provider + snapshot + model + reasoning_effort + temperature + output_limits`, después de comprobar capacidades/modalidades, privacidad, región, retención, presupuesto, disponibilidad y fallback autorizado. La matriz inicial es: P01/P02 Sol-medium; P03 Luna-high; P04/P05 Sol-high; P06-P09 Luna-high; P10 bake-off abierto; P11 Luna-minimal, temperatura 0.

**Contexto:** Un router heurístico por “dificultad” es difícil de reproducir y puede cruzar proveedor o región sin autorización. Imágenes aisladas tampoco justifican cambiar de proveedor: Sol/Terra/Luna aceptan entrada visual por API.

**Alternativas:** chooser LLM; fallback automático por latencia/error; Terra como default semántico. Se rechazan por opacidad, riesgo de datos y falta de evidencia.

**Consecuencias:** Terra solo se habilita si demuestra ventaja medida frente a Luna-high. OpenAI-first no significa OpenAI-only: Claude Sonnet y Gemini 3.6 Flash son comparadores principales. Gemini puede aprobarse para PDF/audio/video nativos o ventaja en bake-off, nunca como fallback genérico. Sin modalidad/ruta aprobada se devuelve `NEEDS_REVIEW` o `BLOCKED`. Cada resolución conserva reason codes estables para reproducción, auditoría y costo.

---

## ADR-032 - MVP cloud sobre Cloud Run, Supabase y R2

**Estado:** Accepted; sustituye ADR-025 y precisa ADR-026  
**Decisión:** El MVP operativo es completamente cloud. React/TypeScript/Vite se sirve inicialmente desde el mismo contenedor que FastAPI en Cloud Run Service. El trabajo largo corre en Cloud Run Jobs y su estado vive en PostgreSQL, sin Redis inicial. Supabase Free provee PostgreSQL/Auth; Cloudflare R2 privado guarda archivos y objetos grandes mediante URLs firmadas. El parsing usa contenedor con PyMuPDF, `python-docx`, `libmagic` y ClamAV cuando sea viable. CI/CD usa GitHub con Cloud Build o GitHub Actions hacia Cloud Run.

**Contexto:** El usuario puede cerrar el navegador y el job debe continuar. Un stack local/Compose no prueba esta propiedad y Redis añade un servicio que todavía no es necesario.

**Alternativas:** Redis/RQ administrado; PaaS genérico; Vercel como frontend obligatorio; procesamiento en request. Se difieren o rechazan por costo, dependencia o falta de durabilidad.

**Consecuencias:** local queda limitado a desarrollo, pruebas y fixtures. Registros estructurados viven en PostgreSQL; raw, JSON grandes y exports en R2. Mocks cubren tests y las llamadas pagadas a modelos son reales solo en ejecuciones explícitas. Jinja2 + WeasyPrint producen exportaciones. Dentro de cuotas gratuitas esperadas, infraestructura fija puede acercarse a USD 0 más APIs; Vercel Pro opcional o overages serían costos posteriores. Vercel Hobby no se usa comercialmente.

---

## ADR-033 - Guía estructurada en plataforma, justificación configurable y aviso fijo

**Estado:** Accepted; sustituye ADR-011  
**Decisión:** `EvaluationGuide` se persiste asociado a evaluación y submission y es consultable en plataforma por docentes/ayudantes autorizados; PDF/HTML es opcional. Para respuestas estructuradas, la justificación del estudiante se configura como `NOT_REQUIRED`, `SELECTED` o `ALL`. Aunque no se solicite, el evaluador conserva respuesta defendible, evidencia y razón de cada distractor. Si no es `ALL`, el reporte declara alcance limitado de evidencia.

**Contexto:** Exigir siempre justificación aumenta fricción en verificaciones breves/formativas. A la vez, omitir la racionalidad interna de opciones debilita la corrección. Un PDF no es la mejor interfaz primaria para aplicar la guía.

**Alternativas:** justificación siempre obligatoria; nunca solicitarla; guía solo exportada. Se rechazan por inflexibilidad o pérdida de soporte evaluativo.

**Consecuencias:** P09 no genera avisos generales de autoría/IA/proceso histórico. Ese mensaje es un footer/callout fijo y visible de la UI, no aparece en documentos generados por el modelo. La guía mantiene niveles observables y alternativas, sin “solucionario histórico”.

---

## ADR-034 - Aprobación masiva explícita con exclusiones

**Estado:** Accepted; sustituye ADR-016 respecto de la mecánica de aprobación  
**Decisión:** La revisión humana sigue siendo obligatoria, pero un docente o evaluador expresamente autorizado puede aprobar en una acción todas las evaluaciones seleccionadas elegibles. La operación exige confirmación explícita y registra actor, fecha, alcance y versiones. Cualquier excepción se excluye y requiere revisión individual.

**Contexto:** Aprobar una por una evaluaciones ya revisadas produce trabajo mecánico sin añadir control. Una acción masiva silenciosa, en cambio, ocultaría alcance y conflictos.

**Alternativas:** aprobación exclusivamente individual; “aprobar todo” sin selección/confirmación; aprobación automática. Se rechazan por ineficiencia o falta de control.

**Consecuencias:** el contrato divide targets aprobados y excluidos, sin solapamiento ni omisiones. Versiones obsoletas, preguntas rechazadas, diagnósticos pendientes o conflictos de concurrencia nunca se fuerzan. No cambia la prohibición de grade passback o sanción automática.
