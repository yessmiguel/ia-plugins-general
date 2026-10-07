---
name: jira-redact
description: Redacta una o varias tareas de desarrollo con el formato del equipo (clave entre brackets en el título), listas para copiar en Jira. No se conecta a Jira ni crea issues.
argument-hint: "<descripción de la tarea>"
---

Redacta una tarea de desarrollo siguiendo el formato profesional del equipo, lista para copiar en Jira. No se conecta a ningún MCP ni crea issues.

## Tu flujo de trabajo

1. Transforma el input del usuario al formato estándar del equipo (ver abajo)
2. Muestra la tarea formateada, lista para copiar
3. Si el input contiene varias tareas separadas por saltos de línea, numeración o bloques, procésalas todas y muéstralas una tras otra

## Formato de salida

---

**Título:** `[<Clave si tiene>] <Descripción corta y clara>`

> Si la tarea trae una clave (ej. `HU-04`, `PE-HU-01`, `TASK-MOB-08-1`), anteponerla al título siempre entre brackets: `[HU-04] <Descripción corta y clara>`. Si no trae clave, el título es solo `<Descripción corta y clara>`.

> Si es un bug, el título debe comenzar con `BUG:` tras la clave: `[<Clave si tiene>] BUG: <Descripción corta del problema>`

**Descripción:**
Explicación clara de qué se debe lograr, enfocada en el entendimiento funcional. Sin detalles técnicos de implementación innecesarios.

> Si hay links (Figma, documentos, etc.), incluirlos con etiqueta clara. Ej: `🔗 Figma: <url>`

**Criterios de aceptación**

- Condición concreta y verificable
- ...

---

## Reglas de redacción

- Lenguaje claro, profesional y directo
- Sin redundancias ni explicaciones demasiado largas
- Backend: incluir criterios de aceptación orientados al resultado observable (ej. datos correctos, comportamiento esperado del servicio, accesos funcionando)
- Frontend: incluir criterios de aceptación con foco en UI, validaciones y flujos de usuario
- Los criterios de aceptación deben escribirse siempre como bullets simples: `- Criterio` (nunca usar `- [ ]` ya que Jira lo interpreta como checklist)
- Considerar buenas prácticas: manejo de estados de carga/error, validaciones, UX
- Si el input trae varias tareas, numerarlas en el output: **Tarea 1**, **Tarea 2**, etc.

## Input del usuario

$ARGUMENTS
