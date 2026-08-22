# Impacto conocido

La orden `ord_431`, intento `pay_1`, recibió dos aprobaciones (`ch_501` y `ch_502`). El dossier no confirma conciliación, reembolso ni otras órdenes afectadas.

# Cadena causal

`d1` llamó al proveedor sin clave idempotente. El proveedor aprobó `ch_501`; después, el insert local agotó tiempo antes de guardar el resultado y el worker no confirmó `job_88`. La redelivery `d2` ejecutó el handler completo. Como no existía estado durable ni clave reconocible por el proveedor, produjo `ch_502`. La entrega al menos una vez explica el reintento, pero el defecto es que nuestro efecto externo no era idempotente.

Factores contribuyentes: llamada externa antes de registrar estado del intento, ausencia de constraint usada como guardia, y falta de reconciliación para el caso 'proveedor aprobó / base no registró'. No afirmo que la cola fallara.

## Línea temporal reconstruida

En `d1`, el worker inicia `job_88` para `ord_431/pay_1` y llama al proveedor. `ch_501` queda aprobado. El intento de insertar el pago local expira, por lo que el handler no puede demostrar durabilidad y tampoco confirma el mensaje. La cola vuelve a entregar el mismo job como `d2`. El proceso no encuentra una fila exitosa y vuelve a ejecutar el efecto externo; el proveedor aprueba `ch_502`.

La incertidumbre está después de esas aprobaciones. El dossier no muestra liquidación, disputa o reembolso, de modo que describo dos aprobaciones y un posible cargo lógico duplicado, no una pérdida financiera definitiva. Tampoco extrapolo a toda la base: solo se documenta una orden.

## Detección y aprendizaje

El sistema detectó el problema al comparar dos ids del proveedor asociados al mismo `order_id` y `attempt_id`. Faltaba una alerta para múltiples aprobaciones por intento y un proceso que conciliara estados `pending` antiguos. El timeout fue el disparador visible, pero un timeout es esperable; el diseño debía conservar una identidad estable a través de la redelivery. La acción correctiva se divide entre prevención con idempotency key, estado durable y detección mediante reconciliación.
