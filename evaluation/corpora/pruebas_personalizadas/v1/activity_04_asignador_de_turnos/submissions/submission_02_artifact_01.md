```python
def asignar_turnos(solicitudes, cupos_por_grupo):
    # Return assigned and waitlisted ids without mutating the inputs.
    vistos = set()
    validas = []

    for posicion, solicitud in enumerate(solicitudes):
        try:
            sid = solicitud["id"]
            grupo = solicitud["grupo"]
            prioridad = solicitud["prioridad"]
            marca = solicitud["marca"]
        except (KeyError, TypeError):
            continue

        if prioridad not in (1, 2, 3) or grupo not in cupos_por_grupo:
            continue
        if sid in vistos:
            continue

        vistos.add(sid)  # only the first valid occurrence claims the id
        validas.append((prioridad, marca, sid, grupo, posicion))

    validas.sort(key=lambda fila: (fila[0], fila[1], fila[2]))
    usados = {grupo: 0 for grupo in cupos_por_grupo}
    asignadas, espera = [], []

    for _, _, sid, grupo, _ in validas:
        if usados[grupo] < cupos_por_grupo[grupo]:
            asignadas.append(sid)
            usados[grupo] += 1
        else:
            espera.append(sid)

    return {"asignadas": asignadas, "espera": espera}
```

## Ejemplo de uso razonado

```python
solicitudes = [
    {"id": "m7", "grupo": "A", "marca": "09:02", "prioridad": 4},
    {"id": "m7", "grupo": "A", "marca": "09:03", "prioridad": 1},
    {"id": "c2", "grupo": "B", "marca": "09:03", "prioridad": 1},
    {"id": "a9", "grupo": "A", "marca": "09:03", "prioridad": 1},
    {"id": "z1", "grupo": "A", "marca": "09:04", "prioridad": 2},
]
cupos = {"A": 1, "B": 0}
```

Con esos datos, la primera fila de `m7` no reclama el id porque su prioridad es inválida. Las candidatas se ordenan como `a9`, `c2`, `m7`, `z1`: prioridad y marca empatan en las tres primeras y entonces decide el id. `a9` ocupa el único cupo de A; `c2`, `m7` y `z1` quedan en espera. Las dos estructuras de entrada conservan su contenido después de la llamada.
