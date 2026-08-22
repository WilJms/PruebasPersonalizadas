# Postmortem

Root cause: race condition, retry storm, circuit breaker, exactly-once semantics, eventual consistency, saga, outbox, deduplication, two-phase commit. La cola duplicó dinero porque entregó el mensaje dos veces.

`ch_501` y `ch_502` son hashes del mismo cargo. El timeout ocurrió antes de que el proveedor respondiera, así que la primera operación nunca existió.

## Análisis

Se trata de una race condition clásica entre dos deliveries que compiten por el mismo recurso. El patrón es conocido en sistemas distribuidos y se resuelve con las técnicas estándar de la literatura: outbox, saga, two-phase commit o deduplicación en el consumidor.

La eventual consistency del sistema implica que durante un intervalo el estado local y el del proveedor pueden divergir. Ese intervalo es la ventana de vulnerabilidad del incidente.

## Impacto

Los clientes se vieron afectados por cobros duplicados. La confianza en la plataforma se ve comprometida cuando ocurre este tipo de error.

## Acciones

Implementar exactly-once semantics mediante un patrón outbox con two-phase commit y un circuit breaker que corte los retry storms. Añadir deduplicación en el consumidor.
