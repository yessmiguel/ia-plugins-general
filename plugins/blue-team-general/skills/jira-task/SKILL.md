---
name: jira-task
description: Redacta una tarea de desarrollo con el formato del equipo y la crea directamente en Jira mediante el conector de Atlassian.
argument-hint: "<descripción de la tarea>"
---

Redacta una tarea de desarrollo siguiendo el formato profesional y créala directamente en Jira.

## Tu flujo de trabajo

1. Transforma el input del usuario al formato estándar del equipo (ver abajo)
2. Muestra la tarea formateada al usuario
3. Usa las herramientas de Atlassian para listar los proyectos Jira disponibles
4. Pregunta al usuario en qué proyecto desea crear la tarea (muestra la lista con clave y nombre)
5. Antes de crear el issue, resuelve el `assignee_account_id` de quien ejecuta la skill: obtén su cuenta con la herramienta de información de usuario de Atlassian; si no está disponible, pregúntale su email y usa `lookupJiraAccountId`
6. Crea el issue en Jira con el título como `summary`, la descripción + criterios de aceptación como `description`, y el `assignee_account_id` obtenido en el paso anterior
   - Usa siempre `contentFormat: "adf"` para la descripción. Construye el campo `description` como un objeto ADF (Atlassian Document Format) JSON válido — NUNCA uses `contentFormat: "markdown"` ni strings con `\n`, ya que se renderizan como texto literal en Jira
   - Si el tipo de tarea es un **BUG**: intenta primero con `issueTypeName: "Bug"`; si falla con error de tipo inválido, reintenta automáticamente con `issueTypeName: "Error"` sin preguntar al usuario
7. Confirma al usuario con el link directo al issue creado

## Formato de salida

**Título:** `<Nombre de la app o sistema> | <Descripción corta y clara>`

> Si es un bug, el título debe comenzar con: `BUG: <Nombre de la app> | <Descripción corta del problema>`

**Descripción:**
Explicación clara de qué se debe lograr, enfocada en el entendimiento funcional. Sin detalles técnicos de implementación innecesarios.

> Si hay links (Figma, documentos, etc.), incluirlos con etiqueta clara. Ej: `🔗 Figma: <url>`

**Criterios de aceptación**

- Condición concreta y verificable
- ...

## Reglas de redacción

- Lenguaje claro, profesional y directo
- Sin redundancias ni explicaciones demasiado largas
- Backend: incluir criterios de aceptación orientados al resultado observable (ej. datos correctos, comportamiento esperado del servicio, accesos funcionando)
- Frontend: incluir criterios de aceptación con foco en UI, validaciones y flujos de usuario
- Los criterios de aceptación deben escribirse siempre como bullets simples: `- Criterio` (nunca usar `- [ ]` ya que Jira lo interpreta como checklist)
- Consistencia en nombres: AppAgente, AppEnVoz, Backend, Animo, etc.
- Considerar buenas prácticas: manejo de estados de carga/error, validaciones, UX

## Formato ADF para la descripción

La descripción debe pasarse como un objeto JSON ADF. Ejemplo de estructura:

```json
{
  "version": 1,
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [{ "type": "text", "text": "Texto de la descripción." }]
    },
    {
      "type": "heading",
      "attrs": { "level": 3 },
      "content": [{ "type": "text", "text": "Criterios de aceptación" }]
    },
    {
      "type": "bulletList",
      "content": [
        {
          "type": "listItem",
          "content": [
            { "type": "paragraph", "content": [{ "type": "text", "text": "Criterio 1" }] }
          ]
        }
      ]
    }
  ]
}
```

## Manejo de errores

- Si el MCP de Atlassian no está autenticado, informa al usuario que ejecute `/mcp` y seleccione "claude.ai Atlassian"
- Si la creación del issue falla por tipo inválido y el tipo era "Bug", reintenta automáticamente con "Error" (y viceversa) antes de reportar error
- Si la creación del issue falla por otra razón, muestra el error y ofrece reintentar o copiar el contenido al portapapeles
- Si `lookupJiraAccountId` no encuentra el email del asignado, crea el issue sin asignar e informa al usuario

## Input del usuario

$ARGUMENTS
