```python
def handle(job):
    queue.ack(job)
    key = random_uuid()
    return provider.charge(job.order_id, job.amount, idempotency_key=key)
```

```python
# d1 -> key uuid-A; d2 -> key uuid-B
# Cada ejecución obtiene su propia clave única.
```

El ack inmediato evita la redelivery que causó el incidente. La clave aleatoria garantiza unicidad por ejecución y el retorno directo del resultado del proveedor mantiene el handler simple, sin estado intermedio que pueda quedar inconsistente.
