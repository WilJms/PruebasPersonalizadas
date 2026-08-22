```python
def handle(job):
    row = db.get_or_create(job.order_id, job.attempt_id, state="pending")
    if row.state == "done":
        return queue.ack(job)
    charge = provider.charge(job.amount, idempotency_key=job.id)
    db.complete(row, charge.id)
    queue.ack(job)
```

```python
# Caso observado: d1 y d2 comparten job.id == "job_88".
# Caso abierto: una republicación con otro job.id produciría otra key.
def key_for(job):
    return job.id
```

El retorno temprano para `done` evita repetir un éxito local. Si `pending` corresponde a una aprobación remota no persistida, el handler vuelve a llamar; depende del proveedor y de que `job.id` siga estable para recuperar el mismo cargo.
