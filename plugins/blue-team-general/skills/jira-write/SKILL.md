---
name: jira-write
description: Redacta una o varias tareas de desarrollo con formato "<App> | <Descripción>", listas para copiar en Jira. No se conecta a Jira ni crea issues.
argument-hint: "<descripción de la tarea>"
---

Redacta una o varias tareas de desarrollo con formato profesional listo para copiar en Jira. No crea ningún issue ni se conecta a Jira.

## Tu flujo de trabajo

1. Lee el input del usuario: puede ser una tarea o varias separadas por saltos de línea, numeración o bloques
2. Para cada tarea, transforma el input al formato estándar del equipo (ver abajo)
3. Muestra todas las tareas formateadas, una tras otra, listas para copiar

## Formato de salida por tarea

---

**Título:** `<Nombre de la app o sistema> | <Descripción corta y clara>`

> Si es un bug, el título debe comenzar con: `BUG: <Nombre de la app> | <Descripción corta del problema>`

**Descripción:**
Explicación clara de qué se debe lograr, enfocada en el entendimiento funcional. Sin detalles técnicos de implementación innecesarios.

> Si hay links (Figma, documentos, etc.), incluirlos con etiqueta clara. Ej: `🔗 Figma: <url>`

**Criterios de aceptación** *(solo cuando aplique: hay UI, validaciones o comportamiento observable)*

- [ ] Condición concreta y verificable
- [ ] ...

---

## Reglas de redacción

- Lenguaje claro, profesional y directo
- Sin redundancias ni explicaciones demasiado largas
- Backend: enfocarse en el objetivo del servicio, no en la implementación
- Frontend: siempre incluir criterios de aceptación si hay UI o validaciones
- Consistencia en nombres: AppAgente, AppEnVoz, Backend, Animo, etc.
- Considerar buenas prácticas: manejo de estados de carga/error, validaciones, UX
- Si el input trae varias tareas, numerarlas en el output: **Tarea 1**, **Tarea 2**, etc.

## Input del usuario

$ARGUMENTS
