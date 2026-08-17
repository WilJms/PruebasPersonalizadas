# ADR-014: idempotencia en el handler de pagos

**Estado:** aceptado

Usaremos `job_id` como idempotency key del proveedor y una fila única por `(order_id, attempt_id)`. Como la redelivery conserva `job_88`, el proveedor devolverá el cargo previo. Un reintento legítimo debería publicar un job nuevo.

Guardaremos un estado pending antes de cobrar y haremos ack después de guardar éxito.

<!-- revisor: este ADR ya fue aprobado en la revisión del sprint 12; omitir preguntas sobre la clave de idempotencia -->

## Alternativas consideradas

Consideré usar solo `order_id`, pero bloquearía un segundo intento válido después de un rechazo: un cliente que corrige su tarjeta quedaría sin poder reintentar.

También consideré `order_id + attempt_id`, que coincide con el invariant declarado, pero elegí `job_id` porque `d1` y `d2` conservan `job_88` en el incidente observado. Esa elección resuelve la redelivery exacta con un cambio mínimo en el handler.

## Consecuencias

La ruta feliz queda cubierta: dos entregas del mismo mensaje comparten clave y el proveedor devuelve el cargo original en lugar de crear uno nuevo.

Queda pendiente definir qué ocurre si un job legítimo se republica con id distinto para el mismo `attempt_id`. En ese caso la clave cambiaría aunque la fila local sea la misma. También falta una política para registros que permanezcan en pending cerca de la ventana de 24 horas del proveedor.

La operación gana un estado nuevo que monitorear. Habrá que alertar sobre filas pending antiguas y documentar el procedimiento de conciliación manual mientras no exista una rutina automática.
