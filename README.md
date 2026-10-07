# ia-plugins

Marketplace de plugins y skills de Claude Code compartidos con el equipo.

## Plugins

| Plugin | Skills | Para qué |
|---|---|---|
| [`blue-team-general`](plugins/blue-team-general/) | `jira-redact`, `jira-write`, `jira-task`, `confluence` | Redactar y crear tareas en Jira; leer y escribir páginas de Confluence Cloud |

## Instalación

En Claude Code:

```
/plugin marketplace add <owner>/<repo>
/plugin install blue-team-general@ia-plugins
```

`<owner>/<repo>` es el repositorio de GitHub donde vive este marketplace (también acepta la URL
de git o una ruta local). Elige el scope **user** para tener las skills en todos tus proyectos.

Las skills quedan con el prefijo del plugin, p. ej. `/blue-team-general:jira-task`.

## Requisitos por skill

| Skill | Requiere |
|---|---|
| `jira-redact`, `jira-write` | Nada: solo redactan |
| `jira-task` | El conector de Atlassian autenticado en Claude |
| `confluence` | `python3` y un perfil en `~/.jira-profiles/<nombre>.json` — ver [su README](plugins/blue-team-general/skills/confluence/README.md) |

Los perfiles llevan el API token de Atlassian: viven en la máquina de cada persona, **nunca** en
este repo.

## Agregar un plugin

1. Crear `plugins/<nombre>/.claude-plugin/plugin.json` y sus `skills/<skill>/SKILL.md`.
2. Añadir la entrada en [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json).
3. Validar con `claude plugin validate .`
