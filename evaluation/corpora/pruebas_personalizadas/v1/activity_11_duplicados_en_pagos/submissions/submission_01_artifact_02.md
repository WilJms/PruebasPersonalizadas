```python
def handle(job, delivery_id):
    key = f"charge:{job.order_id}:{job.attempt_id}:{delivery_id}"
    result = provider.charge(job.amount, idempotency_key=key)
    queue.ack(job)
    db.insert_payment(job.order_id, job.attempt_id, result.id)
```

```python
# Orden efectivo:
# 1. cargo externo
# 2. ack
# 3. insert local
```

El handler recibe el `delivery_id` desde el consumidor de la cola. La inserción final registra el id de cargo devuelto por el proveedor para la orden e intento correspondientes.
