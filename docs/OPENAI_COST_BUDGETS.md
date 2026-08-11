# Costos y presupuestos OpenAI

Política Standard short-context observada y revalidada el 2026-08-10 en la página
oficial vigente. El perfil activo usa únicamente Luna; Terra y Sol se
conservan como referencias de catálogo y no son rutas callable ni fallback.

| Modelo | Input / 1M | Cached input / 1M | Cache write / 1M | Output / 1M |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | USD 5.00 | USD 0.50 | USD 6.25 | USD 30.00 |
| `gpt-5.6-terra` | USD 2.00 | USD 0.20 | USD 2.50 | USD 12.00 |
| `gpt-5.6-luna` | USD 0.20 | USD 0.02 | USD 0.25 | USD 1.20 |

Frente a los precios anteriores, Terra bajó 20% desde
USD 2.50/0.25/15.00 y Luna bajó 80% desde USD 1.00/0.10/6.00; Sol permanece
en USD 5.00/0.50/30.00. Los snippets indexados que aún muestran los valores
anteriores no son autoridad: estas cifras proceden de las páginas cargadas el
2026-08-09. El gate usa Standard, `service_tier=default`, short context y no
Batch/Flex/Fast. Fuentes canónicas operativas:
[precios OpenAI](https://developers.openai.com/api/docs/pricing),
[Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) y
[Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

La fórmula por llamada es:

```text
ordinary_input * input_price
+ cache_hit_input * cached_price
+ cache_write_input * input_price * 1.25
+ output * output_price
```

Todo se divide por un millón. Con más de 272K tokens de input, la política
aplica 2× a input y 1.5× a output. Las rutas normales se limitan a 250K tokens
para quedar debajo de ese tier. Antes de llamar, el gateway calcula el peor
caso usando el máximo output del prompt; si supera el presupuesto restante, no
crea transporte.

## Presupuesto vigente del prompt pack 1.1.2

El cambio de instrucciones P01 invalida la reutilización de evidencia real
1.1.1. La calificación vigente vuelve a incluir los 18 casos `real_eligible`,
incluido P11 directo al final, y conserva una única reserva P11 estructural.
El cálculo observado por el dry-run es:

| Componente vigente | Sin cache | Todo input como cache-write |
|---|---:|---:|
| 18 primarias | USD 0.26801000 | USD 0.28101250 |
| Reserva máxima P11 | USD 0.02545780 | USD 0.02942225 |
| Ceiling agregado | **USD 0.29346780** | **USD 0.31043475** |

El cap humano admisible es exactamente **USD 0.32**; el harness bloquea antes
de credencial/transporte un cap menor al ceiling o mayor a USD 0.32. Conserva
máximo 19 requests como límite presupuestario defensivo, aunque P11 directo
está al final y cualquier reparación detiene la secuencia. No hay retries, P10,
Sol ni fallback.

El preflight también fija los hashes de `oa-p01-injection-md` y exige dos gates
independientes: aceptación de la remediación P01 1.1.2 y autorización billable.
Validar presupuesto o conceder uno de ellos nunca concede el otro; todos estos
controles se resuelven antes de leer la clave.

La recanary focal P01 1.1.2 tiene 10,712 tokens de input upper-bound, 8,000 de
output máximo, USD 0.01174240 sin cache y **USD 0.01227800** full-cache-write;
su cap separado sería USD 0.02. Ejecutarla por separado no sustituye la
calificación completa.

La consulta read-only de Platform del 2026-08-10 mostró USD 3.78/5.00 de
spend, USD 1.22 restantes, alerta al 80% (USD 4.00) y sólo
`gpt-5.6-luna` permitido. El ceiling podría cruzar la alerta aunque no el
límite; esa capacidad no es autorización. La clave existente debe rotarse
antes de cualquier request nueva, por lo que no existe una credencial vigente
autorizada para este gate.

Las cifras de las secciones siguientes corresponden a ejecuciones 1.1.1
históricas y no son el presupuesto de la frontera actual.

## Primer smoke ejecutado

| Campo | Techo |
|---|---:|
| Prompt | P11 sintético |
| Modelo/esfuerzo | Luna / low |
| Llamadas | 1 |
| Retries gateway/SDK | 0 / 0 |
| Input máximo preflight del fixture versionado | 8,027 tokens-equivalentes conservadores |
| Output máximo P11 | 8,000 tokens, incluido reasoning |
| Estimación conservadora | USD 0.0112054 |
| Presupuesto CLI autorizado | USD 0.06 |
| Costo calculado desde usage | USD 0.0006495 |

El preflight serializa instrucciones, envelope y schema estricto, cuenta un
token-equivalente por byte UTF-8 y suma 1,024 tokens de framing, deliberadamente
más conservador que `chars/4`. El valor 8,027 está fijado por una prueba de regresión y debe recalcularse si
cambia el prompt/schema. Un presupuesto mayor requiere aprobación nueva. El resultado registra
costo estimado y costo calculado desde usage; no afirma un cargo exacto de
facturación. Después del smoke y de los dos canaries, el costo acumulado
calculado es **USD 0.00538255**. Platform no ofreció granularidad suficiente
para equipararlo al cargo de facturación. Los USD 5.00 del spend limit no son
una autorización; cada bloque mantiene un techo humano independiente.

El runtime conserva además un techo agregado por job: antes de cada etapa resta
el mayor costo estimado/observado de todos los ledgers persistidos de ese job.
La autorización por llamada incluye el ceiling completo de retries técnicos;
P11 recibe solo el saldo restante. La calificación real posterior tiene
presupuesto total y approval propios; nunca hereda el saldo del smoke o los
canaries. Rate limits, hard limits y quota se traducen a fallos cerrados, no a
cambio de modelo.

## Canaries Luna medium/high ejecutados

Los dos dry-runs usan el adaptador Responses real contra el transporte fake
versionado. La cuenta de bytes corresponde exactamente a instrucciones,
mensajes, reasoning y `text.format` capturados; el upper bound añade 1,024
tokens de framing. No se asume cache, cada caso admite una sola request y los
retries efectivos de gateway/prompt/SDK son 0/0/0. P11 no tiene ruta dentro de
esta frontera canary.

| Campo | P01 `oa-p01-happy-txt` | P07 `oa-p07-open-short-txt` |
|---|---:|---:|
| Modelo / esfuerzo | Luna / medium | Luna / high |
| Bytes efectivos | 8,608 | 20,843 |
| Schema bytes | 3,111 | 13,671 |
| Formato estructurado bytes | 3,189 | 13,761 |
| Envelope bytes | 1,731 | 2,576 |
| Input upper bound | 9,632 tokens | 21,867 tokens |
| Max output, reasoning incluido | 8,000 tokens | 10,000 tokens |
| Worst-case Standard | USD 0.0115264 | USD 0.0163734 |
| Cap humano autorizado | USD 0.07 | USD 0.09 |
| Requests observadas | 1 | 1 |
| Costo calculado desde usage | USD 0.00145745 | USD 0.00327560 |

El worst-case combinado previo fue **USD 0.0278998** frente al cap humano
autorizado de USD 0.16. El costo calculado observado fue **USD 0.00473305** con
dos Responses requests. P10/P11/Sol/retries quedaron en cero. La investigación
posterior del fallo P07 fue offline, no leyó el secreto y añadió USD 0.00.

## Recanary P07 única

La recanary autorizada sobre
`97a6b2e8cd7cf852e9e3a6fefeb09c135793ac19` conservó el preflight P07 de
21,867 input / 10,000 output: USD 0.0163734 sin cache y USD 0.01746675 si todo
el input upper-bound se factura conservadoramente como cache-write. Ambos
quedaron bajo el cap humano independiente de USD 0.03.

La única request observó 3,839 input, 0 cached, 3,836 cache-write, 1,505 output
y 655 reasoning tokens. El estimado post-usage fue USD 0.01295960 y el costo
calculado desde usage USD 0.00276560. No hubo retries, P10, P11, Sol ni una
segunda request. El costo calculado acumulado del smoke, los dos canaries
originales y esta recanary es **USD 0.00814815** en cuatro Responses requests;
no se afirma equivalencia con el cargo final de facturación.

## Calificación sintética P01–P09/P11 preparada

La secuencia nueva no repite los fixtures P01/P07/P11 que ya tienen evidencia
real. Reserva 15 primarias para el resto del corpus `real_eligible` y un solo
P11 eventual; si P11 se usa, la ejecución se detiene. No hay retries, P10, Sol
ni fallback.

| Componente | Sin cache | Todo input como cache-write |
|---|---:|---:|
| 15 requests primarias | USD 0.22844420 | USD 0.23935525 |
| Reserva máxima P11 | USD 0.02545780 | USD 0.02942225 |
| Ceiling agregado | **USD 0.25390200** | **USD 0.26877750** |

La reserva P11 máxima corresponde al root `AssessmentBlueprint`: 79,289 tokens
upper-bound de input y 8,000 de output. Cada input upper-bound sigue contando
un token por byte más 1,024 de framing; cada output reserva el máximo completo,
incluido reasoning. El segundo ceiling trata todo el input como cache-write a
USD 0.25/M porque las ejecuciones previas reportaron casi todo su input bajo
esa categoría. Es el ceiling vinculante aunque el caso sin cache sea menor.

El presupuesto humano propuesto es **USD 0.30**. El harness bloquea antes de
leer la clave si el cap CLI es menor de USD 0.26877750 o mayor de USD 0.30. La
frontera recalcula además, antes de cada transporte, el ceiling full-cache-write
del request real y reserva su suma acumulada; un P11 dinámico que hiciera
superar USD 0.30 queda bloqueado antes de Responses aunque difiera de la
aproximación preflight. La
consulta read-only de Platform del 2026-08-09 mostró USD 1.22 de crédito, y el
proyecto `PruebasPersonalizadas` mostró USD 3.78/5.00 de spend y solo
`gpt-5.6-luna` permitido. Ambos saldos superan el cap propuesto; no se compró
crédito ni se modificaron límites, alerts o modelos. Esa capacidad externa no
es autorización y debe revalidarse antes de cualquier ejecución real.

El dry-run versionado fijó estos valores con 15 transportes fake y cero
Responses requests reales/facturables. Esta preparación añadió USD 0.00.

## Calificación sintética real detenida en P01

La única secuencia autorizada sobre `73d252b…` consumió una Responses request
y se detuvo en `oa-p01-injection-md` por fallo contextual. La primaria pasó
schema provider y Pydantic; no usó P11 ni intentó un segundo caso.

| Magnitud | USD | Proporción del cap USD 0.30 |
|---|---:|---:|
| Costo calculado desde usage | 0.00156270 | 0.52% |
| Charge conservador del harness | 0.01003110 | 3.34% |
| Reserva full-cache-write del transporte creado | 0.01201925 | 4.01% |
| Headroom frente al cap según costo calculado | 0.29843730 | 99.48% |

El request observó 1,725 input, 0 cached, 1,722 cache-write, 943 output y
516 reasoning tokens. La secuencia completa conservaba un ceiling previo de
USD 0.26877750, pero al detenerse solo reservó el primer transporte. No hubo
retries, P10, P11, Sol o fallback; no se realizó ni autorizó una repetición.

## Presupuesto de una eventual recanary P01 injection

La observación de cache-write del request histórico obliga a usar el mayor de
dos ceilings, no solo el cálculo sin cache:

| Frontera fijada | Valor |
|---|---:|
| Input upper-bound | 9,677 tokens |
| Output máximo, reasoning incluido | 8,000 tokens |
| Ceiling sin cache | USD 0.01153540 |
| Ceiling con todo input como cache-write | **USD 0.01201925** |
| Presupuesto humano propuesto | **USD 0.02** |
| Máximo de Responses requests | 1 |

El pricing oficial se revalidó el 2026-08-10 sin cambios. El pricing fijado es
Luna Standard short-context: USD 0.20/M input, 0.02/M
cached input, 0.25/M cache-write y 1.20/M output. El harness bloquea un cap
superior a USD 0.02, uno inferior al ceiling, drift de los hashes históricos o
la ausencia de la aprobación distinta antes de crear el adapter. P11, retries,
P10, Sol y fallback permanecen en cero. El dry-run versionado pasó con
transport fake; esta preparación consumió **USD 0.00** y no consultó saldo ni
secreto.

## Recanary P01 injection consumida

La recanary autorizada consumió una sola Responses request y se detuvo por el
fallo contextual `P01_ABSTENTION_SOURCED_FIELDS_PRESENT`.

| Magnitud | USD | Proporción del cap USD 0.02 |
|---|---:|---:|
| Costo calculado desde usage | 0.00147750 | 7.39% |
| Charge conservador del harness | 0.01003110 | 50.16% |
| Ceiling full-cache-write previamente autorizado | 0.01201925 | 60.10% |
| Headroom frente al cap según costo calculado | 0.01852250 | 92.61% |

El uso fue 1,725 input, 0 cached, 1,722 cache-write y 872 output tokens. No
hubo retries, P10, P11, Sol, fallback ni una segunda request. La lectura de
Secret Manager fue efímera y no modificó secreto, IAM, límites ni cloud.

## Qualification 1.1.2 consumida y detenida en P02

La rotación ya completa habilitó exactamente una qualification con cap USD
0.32. El gate ejecutó 11 casos y se detuvo en el primer fallo contextual P02;
no se reanudó ni se repitió.

| Magnitud | USD | Proporción del cap USD 0.32 |
|---|---:|---:|
| Costo calculado desde usage | 0.03258029 | 10.18% |
| Charge conservador acumulado | 0.12137549 | 37.93% |
| Reserva full-cache-write de transportes creados | 0.15922425 | 49.76% |
| Ceiling full-cache-write preflight completo | 0.31043475 | 97.01% |
| Headroom según costo calculado | 0.28741971 | 89.82% |

Las 11 llamadas fueron Luna Standard; P10/P11/Sol/fallback y retries quedaron
en cero. El P01 inicial pasó y el P02 final pasó schema provider/Pydantic antes
de fallar contexto. La ejecución añadida por este gate es únicamente USD
0.03258029 calculados; ceilings y charges conservadores no son costo observado.

## Recanary P02 1.1.3 y continuación consumidas

La instrucción P02 candidata aumenta su input upper-bound de 10,507 a 11,323
tokens. El schema, output máximo y ruta permanecen iguales.

| Frontera fijada | Valor |
|---|---:|
| Input upper-bound | 11,323 tokens |
| Output máximo, reasoning incluido | 8,000 tokens |
| Ceiling sin cache | USD 0.01186460 |
| Ceiling con todo input como cache-write | **USD 0.01243075** |
| Presupuesto humano autorizado | **USD 0.02** |
| Máximo de Responses requests | 1 |

El dry-run usó una llamada fake, cero red/billable y hashes exactos P02 1.1.3.
La autorización posterior se consumió en una sola Responses request:

| Magnitud observada | USD | Proporción del cap USD 0.02 |
|---|---:|---:|
| Costo calculado desde usage | 0.00123210 | 6.16% |
| Charge conservador | 0.01011210 | 50.56% |
| Ceiling full-cache-write | 0.01243075 | 62.15% |
| Headroom según costo calculado | 0.01876790 | 93.84% |

El uso fue 2,049 input, 0 cached, 2,046 cache-write, 600 output y 300 reasoning
tokens. No hubo retries, P10, P11, Sol, fallback ni segunda request.

La continuación evita volver a comprar los once casos con PASS real hash-bound
y reserva sólo los siete aún no observados más una reserva P11 global:

| Frontera de continuación | Valor |
|---|---:|
| Casos primarios nuevos | 7 |
| Evidencia real reutilizada | 11 casos |
| Máximo defensivo de Responses requests | 8 |
| Ceiling sin cache | USD 0.14256840 |
| Ceiling full-cache-write | **USD 0.15121050** |
| Cap humano propuesto | **USD 0.16** |

El cap USD 0.16 fue autorizado una sola vez. El proceso se detuvo en P05 tras
P03, P04, P05 y una única P11:

| Magnitud observada | USD | Proporción del cap USD 0.16 |
|---|---:|---:|
| Costo calculado desde usage | 0.02438310 | 15.24% |
| Charge conservador | 0.06006390 | 37.54% |
| Reserva full-cache-write creada | 0.07136750 | 44.60% |
| Ceiling preflight autorizado | 0.15121050 | 94.51% |
| Headroom según costo calculado | 0.13561690 | 84.76% |

Las cuatro requests usaron Luna Standard. P03/P04 pasaron; P05 falló Pydantic
y P11 no produjo un target válido. P10/Sol/fallback y retries quedaron en cero.
La autorización no se transfiere ni puede repetirse contra 1.1.4.

## Recanary P05 1.1.4 preparada, no autorizada

El prompt P05 candidato añade la tabla canónica de estado/recomendación. El
schema, output máximo y ruta permanecen iguales. Su frontera hash-bound es:

| Frontera fijada | Valor |
|---|---:|
| Input upper-bound | 13,311 tokens |
| Output máximo, reasoning incluido | 16,000 tokens |
| Ceiling sin cache | USD 0.02186220 |
| Ceiling con todo input como cache-write | **USD 0.02252775** |
| Cap humano propuesto | **USD 0.03** |
| Máximo de Responses requests | 1 |

El dry-run usa una llamada fake, cero red/billable y P11 cero. Si P05 vuelve a
ser inválido, `_SingleRequestAdapter` bloquea la reparación antes de un segundo
transporte. El cap USD 0.03 no está autorizado; requiere aceptación normativa
P05/P11 y approval facturable específicas.
