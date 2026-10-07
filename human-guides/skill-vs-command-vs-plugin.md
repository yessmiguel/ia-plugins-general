# Skill vs. comando vs. plugin

Los tres son formas de darle instrucciones reutilizables a Claude. Cambian en tamaño y en cómo se
distribuyen.

| | Qué es | Forma en disco | Cómo se activa |
|---|---|---|---|
| **Comando** | Un prompt guardado | Un archivo `.md` en `commands/` | Lo escribes tú: `/jira-task …` |
| **Skill** | Instrucciones para una tarea, con archivos de apoyo si hacen falta | Una carpeta con `SKILL.md` más scripts o plantillas | La escribes con `/nombre`, o Claude la elige sola por su descripción |
| **Plugin** | El paquete que distribuye lo anterior | Una carpeta con `plugin.json` que contiene skills, comandos, agentes, hooks o conectores | No se invoca: se instala, y lo que trae queda disponible con su prefijo |

## En corto

- **Comando vs. skill:** el comando es un único archivo de texto. La skill puede traer archivos
  propios (un script, una plantilla) y Claude puede usarla sin que la nombres. La skill es el
  formato recomendado.
- **Skill vs. plugin:** la skill es el contenido; el plugin es la caja con nombre y versión para
  instalarlo, actualizarlo y compartirlo.
- **Marketplace:** el catálogo (un repo) desde donde se instalan los plugins.

## Ejemplo con este repo

`jira-task` es una **skill**, `blue-team-general` es el **plugin** que la contiene, e `ia-plugins`
es el **marketplace** desde donde se instala. Se invoca como `/blue-team-general:jira-task`.
