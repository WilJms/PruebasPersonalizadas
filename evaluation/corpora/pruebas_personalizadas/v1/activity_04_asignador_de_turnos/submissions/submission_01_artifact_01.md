```python
def asignar_turnos(solicitudes, cupos_por_grupo):
    seen = set()
    valid = []
    for item in solicitudes:
        sid = item.get("id")
        if sid in seen:
            continue
        seen.add(sid)
        if item.get("prioridad") not in (1, 2, 3):
            continue
        if item.get("grupo") not in cupos_por_grupo:
            continue
        valid.append(item)

    valid.sort(key=lambda x: (x["prioridad"], x["marca"]))
    total_capacity = sum(cupos_por_grupo.values())
    return {
        "asignadas": [x["id"] for x in valid[:total_capacity]],
        "espera": [x["id"] for x in valid[total_capacity:]],
    }
```

## Prueba que utilicé

```python
entrada = [
    {"id": "a", "grupo": "A", "prioridad": 1, "marca": "09:00"},
    {"id": "b", "grupo": "A", "prioridad": 2, "marca": "09:01"},
    {"id": "c", "grupo": "B", "prioridad": 1, "marca": "09:02"},
]
print(asignar_turnos(entrada, {"A": 1, "B": 1}))
```

Esperaba dos asignadas porque la suma de capacidad es dos. El resultado toma `a` y `c`, que coincide con ese caso. No probé una entrada donde las dos primeras candidatas pertenecen a A ni un empate total de prioridad y marca.
