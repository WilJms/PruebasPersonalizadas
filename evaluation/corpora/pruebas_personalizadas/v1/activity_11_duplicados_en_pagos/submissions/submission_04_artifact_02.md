```python
def handle(job):
    key = f"charge:{job.order_id}:{job.attempt_id}"
    attempt = db.get_or_create_attempt(
        order_id=job.order_id,
        attempt_id=job.attempt_id,
        idempotency_key=key,
        state="pending",
    )  # unique(order_id, attempt_id)

    if attempt.state == "succeeded":
        queue.ack(job)
        return

    if attempt.is_older_than(hours=23):
        alerts.reconcile_required(attempt)
        return  # no ack; operator/reconciler owns recovery

    result = provider.charge(
        job.order_id,
        job.amount,
        idempotency_key=attempt.idempotency_key,
    )
    db.mark_succeeded(attempt, provider_charge_id=result.id)
    queue.ack(job)
```

```python
def reconcile(attempt):
    remote = provider.lookup(idempotency_key=attempt.idempotency_key)
    if remote.state == "succeeded":
        db.mark_succeeded(attempt, provider_charge_id=remote.id)
        return "recovered"
    if remote.state == "not_found" and attempt.is_younger_than(hours=23):
        return "retry_same_key"
    alerts.manual_review(attempt)
    return "blocked"
```

`lookup` representa la capacidad autorizada de consultar por la misma clave; no se asume una transacción distribuida. La ruta manual cubre respuestas desconocidas o cercanas al vencimiento.
