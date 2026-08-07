# Ambigüedades y decisiones de producto

## Estado

| Concepto | Resultado |
|---|---:|
| Ambigüedades genuinas no resolubles por la jerarquía | 0 |
| Elementos clasificados `AMBIGUO_EN_ESPECIFICACION` | 0 |
| Elementos clasificados `DECISION_DE_PRODUCTO_REQUERIDA` | 0 |
| Decisiones solicitadas al propietario durante la ejecución | 0 |
| Respuestas del propietario durante la ejecución | 0 |
| Decisiones pendientes | 0 |
| Contradicciones documentales | 2 |

No se activó el protocolo `DECISIÓN REQUERIDA`. Cada cuestión material encontrada tuvo una interpretación única razonablemente defendible después de aplicar la jerarquía indicada por el encargo y `AGENTS.md`.

Este documento no repite cuestiones objetivamente resolubles. Por ello, `CHOICE` versus justificación, la intención de `OPEN_SHORT` y la dificultad derivada se explican en el informe de conformidad, pero no se presentan aquí como ambigüedades ni decisiones.

## Registro de decisiones solicitadas

No existen entradas. No se eligió silenciosamente entre alternativas de producto, pedagogía, UX, seguridad, privacidad, compatibilidad o arquitectura igualmente defendibles.

## Contradicciones documentales

### CD-001 / F-021 — Aprobación masiva llamada “MVP” y diferida a Etapa 2

**Clasificación:** `CONTRADICCION_DOCUMENTAL`

**Severidad:** P2

**Estado:** resuelta por jerarquía; no requiere decisión del propietario para el gate actual.

**Fuentes en tensión**

- `specification/04_Matrices_y_Costos_v1.1(1).xlsx`, hoja de componentes: incluye “Review and bulk approval” dentro de la superficie llamada MVP.
- `specification/06_MVP_Entorno_Experimental(1).md`, flujo, pantallas y endpoints: incluye selección y aprobación masiva.
- `specification/00_Especificacion_Arquitectura_v1.1(1).md`: define la semántica eventual de aprobación masiva.
- `specification/05_Plan_Implementacion_v1.1(1).md`, E2-14: asigna explícitamente la aprobación masiva a Etapa 2.
- `AGENTS.md`: prohíbe añadir aprobación masiva sin una instrucción humana que abra otro gate.

**Interpretación adoptada**

“MVP” en arquitectura, workbook y documento experimental describe una superficie objetivo multietapa. El alcance inmediato verificable de este commit es Etapa 1. La aprobación masiva es una capacidad futura ya contratada/diseñada, pero no debe estar activa en API, UI o workflow E1.

**Alternativas descartadas**

1. **Tratar bulk approval como requisito E1.** Se descarta porque contradice el story ID E2-14 y la instrucción explícita de alcance del repositorio.
2. **Eliminar sus roots y diseño de la especificación.** Se descarta porque son contratos de evolución legítimos y la arquitectura eventual sigue vigente.
3. **Clasificar la ausencia como defecto o capacidad ausente E1.** Se descarta porque confundiría backlog futuro con incumplimiento del gate actual.

**Impacto de la interpretación**

| Superficie | Impacto |
|---|---|
| Contratos | Los roots futuros pueden permanecer; no se invocan. |
| UX | No se agrega selección múltiple, confirmación masiva ni excepciones. |
| Código/API | No se habilita `/assessments:bulk-approve`. |
| Persistencia | No se crean records/exclusions operacionales en E1. |
| Infraestructura | Ninguno. |
| Migraciones | Ninguna para cerrar la contradicción documental. |
| Pruebas | Debe mantenerse una prueba negativa de ausencia de la acción en E1. |
| Documentación | Debe etiquetarse la capacidad como “objetivo E2”, evitando usar “MVP” sin etapa. |

### CD-002 / F-022 — El documento general de MVP mezcla pantallas/endpoints E1 y E2

**Clasificación:** `CONTRADICCION_DOCUMENTAL`

**Severidad:** P2

**Estado:** resuelta por jerarquía; no requiere decisión del propietario para el gate actual.

**Fuentes en tensión**

- `specification/06_MVP_Entorno_Experimental(1).md` §8–§9 incluye en una misma lista actividades, carga múltiple, retry/cancel, acciones por pregunta, regeneración, bulk approval, coverage, métricas y feedback.
- `specification/05_Plan_Implementacion_v1.1(1).md` separa el primer recorrido vertical E1 de lote, retries, acciones, coverage, métricas, feedback y aprobación masiva E2.
- `AGENTS.md` fija E0/E1 como alcance actual y enumera expresamente las historias que no pueden incorporarse.

**Interpretación adoptada**

La tabla de `06_MVP` es una arquitectura de producto experimental acumulativa, no el criterio de aceptación indivisible de Etapa 1. Para este commit se aplican E1-01 a E1-11. De la tabla general solo se exigen las partes necesarias para ese recorrido y las rutas read-only que no dependen de una historia E2; toda mutación batch, retry/cancel, granular, bulk, feedback o métrica de experimento queda diferida.

**Alternativas descartadas**

1. **Implementar toda la tabla como E1.** Se descarta por violar el plan y abrir varias historias E2.
2. **Ignorar por completo `06_MVP`.** Se descarta porque sigue siendo autoridad para pantallas y endpoints no contradichos por el plan, por ejemplo lista de actividades, edición y vista autorizada de oportunidades/plan.
3. **Considerar todos los endpoints no implementados como fuera de alcance.** Se descarta: algunos GET y flujos básicos son compatibles y necesarios para recuperar/revisar el recorrido E1.

**Impacto de la interpretación**

| Superficie | Impacto |
|---|---|
| Contratos | Se conservan roots multietapa, sin inferir activación. |
| UX | Se requieren recuperación/lista, edición básica y vistas read-only E1; no se añaden controles E2. |
| Código/API | Se pueden cerrar F-002, F-006 y F-011 sin batch ni acciones por pregunta. |
| Persistencia | Se reutilizan tablas/snapshots existentes; no se habilitan tablas E2. |
| Infraestructura | No cambia topología ni job semantics. |
| Migraciones | No son necesarias para resolver la contradicción. |
| Pruebas | Deben diferenciar explícitamente capacidades E1 requeridas y controles E2 ausentes. |
| Documentación | Cada pantalla, ruta y componente debe llevar columna/etiqueta de etapa. |

## Interpretaciones adoptadas fuera de este registro

Las siguientes cuestiones no son ambigüedades y por eso no tienen alternativas de decisión en este documento:

- `CHOICE` es un formato; la justificación estudiantil es una policy independiente.
- `evaluator_rationale` y `misconception` son información del evaluador, no prueba de que el estudiante deba justificar.
- `OPEN_SHORT` no impone por sí solo límite de caracteres ni baja dificultad.
- dificultad, profundidad, demanda cognitiva y operación son conceptos distintos; el sistema deriva dificultad y la UI debe mostrarla durante revisión, no pedirla como selector E1.
- el aviso fijo sobre autoría/IA corresponde a E2-15; su ausencia no es defecto E1.

Cada interpretación anterior está determinada directamente por `models_v1.1(1).py`, arquitectura y Plan; incluirla como decisión habría creado una falsa ambigüedad.

## Estado del protocolo interactivo

No hay trabajo detenido ni respuesta pendiente. La especificación de remediación puede ejecutarse en el orden P1 → P2 → P3 sin abrir un nuevo gate de producto, siempre que no se modifique semántica contractual ni se active una capacidad E2.
