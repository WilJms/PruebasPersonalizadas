# Postmortem

La causa fue confirmar el mensaje antes del primer cargo. Por eso la cola lo entregó de nuevo. El proveedor nunca aprobó ch_501, aunque la traza dice 'aprobado'. No hubo segundo cargo; ch_502 es solo un retry id.

La corrección debe mantener una clave estable por orden e intento y hacer ack después de persistir el resultado.

## Cronología

La traza registra `ch_501 approved`, luego un timeout en la escritura local, luego la redelivery del mensaje y finalmente `ch_502 approved`. Ambos identificadores están asociados a `ord_431` y `pay_1`.

## Alcance

El caso documentado corresponde a una orden. No sabemos si hubo liquidación ni si se emitió un reembolso.

## Acciones

Añadir alerta sobre intentos con más de un provider id. Documentar el procedimiento de conciliación. Revisar el orden de ack en el resto de los handlers de la cola.
