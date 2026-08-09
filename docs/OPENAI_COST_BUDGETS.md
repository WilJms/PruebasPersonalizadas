# Costos y presupuestos OpenAI

Política estándar short-context observada el 2026-08-08 en las páginas
oficiales vigentes. El perfil activo usa únicamente Luna; Sol se conserva como
referencia histórica de una comparación futura no autorizada.

| Modelo | Input / 1M | Cached input / 1M | Output / 1M |
|---|---:|---:|---:|
| `gpt-5.6-sol` | USD 5.00 | USD 0.50 | USD 30.00 |
| `gpt-5.6-luna` | USD 0.20 | USD 0.02 | USD 1.20 |

La página actual también publica cache write Luna a USD 0.25 y Batch
short-context a USD 0.10/0.01/0.125/0.60; el gate usa Standard, `service_tier`
default y no Batch. Fuente canónica operativa:
[precios OpenAI](https://developers.openai.com/api/docs/pricing) y
[modelo Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

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

## Primer smoke propuesto

| Campo | Techo |
|---|---:|
| Prompt | P11 sintético |
| Modelo/esfuerzo | Luna / low |
| Llamadas | 1 |
| Retries gateway/SDK | 0 / 0 |
| Input máximo preflight del fixture versionado | 8,027 tokens-equivalentes conservadores |
| Output máximo P11 | 8,000 tokens, incluido reasoning |
| Estimación conservadora | USD 0.0112054 |
| Presupuesto CLI propuesto | USD 0.06 |

El preflight serializa instrucciones, envelope y schema estricto, cuenta un
token-equivalente por byte UTF-8 y suma 1,024 tokens de framing, deliberadamente
más conservador que `chars/4`. El valor 8,027 está fijado por una prueba de regresión y debe recalcularse si
cambia el prompt/schema. Un presupuesto mayor requiere aprobación nueva. El resultado registra
costo estimado y costo calculado desde usage; no afirma un cargo exacto de
facturación. Costo acumulado real al cierre de este documento: **USD 0.00**,
porque no se ejecutó ninguna llamada. Los USD 5.00 disponibles son saldo, no un
presupuesto autorizado; cada bloque mantiene un techo humano independiente.

El runtime conserva además un techo agregado por job: antes de cada etapa resta
el mayor costo estimado/observado de todos los ledgers persistidos de ese job.
La autorización por llamada incluye el ceiling completo de retries técnicos;
P11 recibe solo el saldo restante. El golden set real posterior tiene
presupuesto total independiente. Nunca
hereda el saldo del smoke y exige `--allow-billable`, monto positivo, clave y
la frase de aprobación exacta. Rate limits, hard limits y quota se traducen a
fallos cerrados, no a cambio de modelo.
