# Skill `confluence`

Lectura y escritura de páginas de Confluence Cloud desde un link, con
**conexión configurable por cuenta** (portable entre clientes y máquinas).

## Puesta en marcha (una vez por computadora)

Confluence usa **el mismo sitio y el mismo API token que Jira**, así que esta
skill **reutiliza los perfiles que ya tienes** en `~/.jira-profiles/`. No hay
token nuevo que crear.

1. Abre el perfil de la cuenta, p. ej. `~/.jira-profiles/blue-labs-medikairos.json`.
2. Agrégale el bloque `confluence` (opcional, pero cómodo):

   ```json
   "confluence": {
     "defaultSpaceKey": "Kairos",
     "defaultParentUrl": "https://bluestudio.atlassian.net/wiki/spaces/medikairos/pages/3485958173/00+Project+Home"
   }
   ```

3. Verifica pidiéndole a Claude: «valida mi conexión a Confluence con el perfil
   `blue-labs-medikairos`» (corre el comando `check` del script).

Si es una cuenta nueva, copia `confluence.profile.example.json` a
`~/.jira-profiles/<nombre>.json` y rellena `baseUrl` + `auth`.

> `baseUrl` va **sin** `/wiki`.
> Los perfiles contienen el API token: viven en el local de cada máquina,
> **nunca** en el repo.

## Uso desde Claude

Basta con pegarle un link y decirle qué hacer:

- «Lee esta página: https://…/wiki/spaces/medikairos/pages/3661234177/4.+API+Keys»
- «Resume el documento de arquitectura y compáralo con el despiece.»
- «Sube este .md a Confluence bajo la página 00 · Project Home.»
- «Actualiza esa página con la versión corregida.»
- «Busca en Confluence las páginas que mencionen OTP.»
- «Lista las páginas hijas del espacio MediKairos.»

Claude siempre corre las escrituras primero en `--dry-run` y pide confirmación
antes de tocar Confluence.

## Comandos

| Comando | Para qué |
|---|---|
| `check` | Valida conexión y espacio por defecto |
| `resolve` | Link → pageId, título, versión |
| `read` | Página → markdown (`--out` para guardarla en archivo) |
| `children` | Árbol de páginas hijas (`--depth`) |
| `search` | Búsqueda por texto o CQL |
| `create` | Página nueva desde markdown (idempotente por título) |
| `update` | Reemplaza el cuerpo de una página existente |

Detalle completo de flags y reglas de contenido: ver [SKILL.md](SKILL.md).

## Varias cuentas

Un archivo por cuenta en `~/.jira-profiles/`, y se elige con `--profile`
(`scripts/confluence_client.py` dentro de esta carpeta):

```bash
python3 scripts/confluence_client.py --profile blue-labs-medikairos read --url "<link>"
python3 scripts/confluence_client.py --profile cm-jira-lab          read --url "<link>"
```

El script no tiene nada hardcodeado: dominio, espacio y credenciales salen
siempre del perfil.

## Límites conocidos

- No descarga adjuntos ni imágenes (las imágenes se leen como
  `![alt](nombre-archivo.png)`).
- Los bloques ```` ```mermaid ```` se suben como imagen PNG adjunta. Requiere
  Node.js (`npx`) o `mmdc`; sin ellos quedan como bloque de código y la salida
  lo avisa en `mermaidWarnings`.
- No lee ni escribe comentarios de página.
- `update` reemplaza el **cuerpo completo**; para un cambio parcial:
  `read --out` → editar → `update --body-file`.
- Macros de Confluence sin equivalente en markdown se leen como
  `<!-- macro: nombre -->`. Al escribir se soportan `code`, listas de tareas y
  tablas nativas.
- Requiere `python3` en el PATH. Sin dependencias externas.
