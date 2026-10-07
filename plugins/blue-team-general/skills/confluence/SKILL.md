---
name: confluence
description: >-
  Lee y escribe páginas de Confluence Cloud desde un link. Úsala cuando el
  usuario pegue una URL de Confluence (".atlassian.net/wiki/..."), o pida
  "lee esta página de Confluence", "resume este documento de Confluence",
  "sube esto a Confluence", "crea una página en Confluence", "actualiza la
  página de Confluence", "busca en Confluence", "lista las páginas hijas".
  La conexión se configura con un perfil Atlassian portable por cuenta.
---

# confluence

## Objetivo

Dar a Claude acceso de **lectura y escritura** a Confluence Cloud a partir de
un **link** que pegue el humano, usando el **mismo perfil de cuenta** que ya
usan las skills de Jira (`despiece-to-jira`, `pe-to-jira`).

La skill traduce en ambos sentidos:

- **Confluence → markdown** al leer (encabezados, listas, tablas, código,
  paneles info/nota/aviso, listas de tareas, links).
- **markdown → storage format** al escribir (Confluence guarda XHTML, no
  markdown; el script hace la conversión para que **renderice de verdad**).

---

## Configuración de la conexión (LEER SIEMPRE ANTES DE EMPEZAR)

> ⚠️ **Si el usuario pide algo de Confluence sin un perfil válido, NO sigas.**
> Muéstrale el formato de abajo y cómo obtener cada dato. No inventes
> credenciales ni continúes sin el archivo.

Confluence vive en el **mismo sitio Atlassian que Jira** y usa **el mismo API
token**. Por eso esta skill **reutiliza los perfiles que ya existen** en
`~/.jira-profiles/` — no hay un token nuevo que crear ni un archivo nuevo que
mantener; solo se le agrega un bloque `confluence`.

**Dónde se coloca:** un archivo JSON por cuenta, en la carpeta local
`~/.jira-profiles/`, con el nombre del perfil:

```
~/.jira-profiles/blue-labs-medikairos.json
~/.jira-profiles/cm-jira-lab.json
```

> Los perfiles viven en el **local de cada computadora**, fuera de cualquier
> repo, porque contienen el API token. Al cambiar de máquina se recrean una vez.

**Formato** (ver también `confluence.profile.example.json` en esta carpeta):

```json
{
  "profileName": "blue-labs-medikairos",
  "baseUrl": "https://bluestudio.atlassian.net",
  "auth": {
    "email": "tu-correo@dominio.com",
    "apiToken": "ATATT3xFfGF0..."
  },

  "projectKey": "MDKRS",
  "boardId": 42,
  "projectStyle": "team-managed",

  "confluence": {
    "defaultSpaceKey": "Kairos",
    "defaultParentUrl": "https://bluestudio.atlassian.net/wiki/spaces/medikairos/pages/3485958173/00+Project+Home"
  }
}
```

Los campos de Jira (`projectKey`, `boardId`, `projectStyle`, `issueTypes`) y
los de Confluence **conviven en el mismo archivo**; cada skill lee solo los
suyos. Agregar el bloque `confluence` **no rompe** las skills de Jira.

**Cómo obtener cada dato:**

| Campo | Cómo conseguirlo |
|---|---|
| `baseUrl` | La URL de tu sitio **sin** `/wiki`, p. ej. `https://bluestudio.atlassian.net` |
| `auth.email` | El correo de tu cuenta Atlassian |
| `auth.apiToken` | El **mismo** que ya usas en Jira. Si no lo tienes: https://id.atlassian.com/manage-profile/security/api-tokens |
| `confluence.defaultSpaceKey` | *(opcional)* Espacio por defecto para crear/buscar. Acepta la key real o el slug que ves en la URL `/wiki/spaces/<esto>/` |
| `confluence.defaultParentUrl` | *(opcional)* Link de la página bajo la cual colgar las páginas nuevas por defecto |

> **Ojo con el espacio:** el slug de la URL se deriva del *nombre* del espacio
> y **no siempre es la key**. Ej.: nombre `MediKairos` → slug `medikairos` →
> key real `Kairos`. El script acepta cualquiera de los dos.

**Permisos:** el API token hereda los permisos de tu usuario. Si puedes leer o
editar la página en el navegador, la skill también; si no, la API responde 404
o 403 y la skill se detiene con el mensaje correspondiente.

---

## Proceso (pasos a seguir)

### Paso 0 — Elegir el perfil
Si el usuario no dice cuál, deduce el perfil por el dominio del link
(`bluestudio.atlassian.net` → el perfil cuyo `baseUrl` coincide). Si hay
varios candidatos o ninguno, **pregunta** antes de continuar.

### Paso 1 — Validar conexión
Ejecuta `check` (ver **Uso del script**). Si falla, muestra el error y la
sección **Configuración de la conexión**. No sigas.

Con perfil ya probado y una petición solo de lectura, puedes saltar el `check`
e ir directo a `read`: los errores de auth también se reportan ahí.

### Paso 2 — Leer
Ejecuta `read --url <link>`. La skill resuelve el `pageId` desde cualquier
forma de link (ver **Links soportados**).

- Para páginas largas usa `--out <archivo.md>` y luego lee el archivo: evita
  volcar miles de líneas en la conversación.
- Guarda el **número de versión** que devuelve `read`: lo necesitas si vas a
  escribir sobre esa misma página.

### Paso 3 — Escribir (PAUSA DE CONFIRMACIÓN — obligatoria)

Escribir en Confluence es una acción **visible para todo el equipo** y
`update` **reemplaza el cuerpo completo** de la página. Por eso:

1. Corre siempre primero con `--dry-run` y enséñale al humano **qué página**,
   **qué título** y **qué versión** se van a tocar.
2. Pide **confirmación explícita**.
3. Solo entonces ejecuta sin `--dry-run`.

Nunca escribas en una página que el humano no haya nombrado explícitamente.

**Actualizar sin pisar a nadie:** pasa `--expected-version <n>` con la versión
que devolvió `read`. Si alguien editó la página en medio, el script se detiene
en vez de sobrescribir el trabajo ajeno.

**Actualización parcial:** la API reemplaza el cuerpo entero. Para cambiar solo
una sección: `read --out` → editas el markdown → `update --body-file` con el
documento **completo**.

### Paso 4 — Reportar
Entrega el resultado: título, versión nueva y la **URL** de la página.

---

## Links soportados

`--url` acepta cualquiera de estas formas (y también un `pageId` suelto):

| Forma | Ejemplo |
|---|---|
| Página normal | `.../wiki/spaces/KEY/pages/123456789/Titulo` |
| Página sin título | `.../wiki/spaces/KEY/pages/123456789` |
| Modo edición | `.../wiki/spaces/KEY/pages/edit-v2/123456789` |
| Entrada de blog | `.../wiki/spaces/KEY/blog/2024/05/01/123456789/Retro` |
| Link legacy | `.../wiki/pages/viewpage.action?pageId=123456789` |
| Tiny link | `.../wiki/x/AbCdE` (se resuelve siguiendo la redirección) |
| Espacio | `.../wiki/spaces/KEY` (usa la **homepage** del espacio) |
| Id suelto | `123456789` |

Los parámetros extra (`?focusedCommentId=...`) se ignoran sin problema.

---

## Uso del script

El script usa solo la **librería estándar de Python 3** (no requiere
`pip install`). Todas las salidas son JSON por stdout.

**Ruta del script — úsala siempre así.** La skill se instala con el plugin, de
modo que esta ruta es válida desde **cualquier proyecto**, independientemente
del directorio de trabajo. Nunca la invoques con una ruta relativa
(`scripts/...`).

```bash
S="${CLAUDE_SKILL_DIR}/scripts/confluence_client.py"
P=blue-labs-medikairos      # nombre del perfil o path completo

# Validar conexión (y el espacio por defecto)
python3 "$S" --profile $P check
python3 "$S" --profile $P check --space medikairos

# Link -> pageId / título / versión (sin traer el cuerpo)
python3 "$S" --profile $P resolve --url "<link>"

# Leer una página como markdown
python3 "$S" --profile $P read --url "<link>"
python3 "$S" --profile $P read --url "<link>" --out /tmp/pagina.md
python3 "$S" --profile $P read --url "<link>" --format storage   # XHTML crudo

# Árbol de páginas hijas
python3 "$S" --profile $P children --url "<link>" --depth 2

# Buscar
python3 "$S" --profile $P search --text "onboarding" --limit 10
python3 "$S" --profile $P search --text "otp" --all-spaces
python3 "$S" --profile $P search --cql 'space="Kairos" AND title ~ "API*"'

# Crear una página (simulacro y real)
python3 "$S" --profile $P create --space Kairos --title "Mi página" \
  --body-file doc.md --parent "<link-del-padre>" --dry-run
python3 "$S" --profile $P create --space Kairos --title "Mi página" \
  --body-file doc.md --parent "<link-del-padre>"

# Actualizar una página existente
python3 "$S" --profile $P update --url "<link>" --body-file doc.md --dry-run
python3 "$S" --profile $P update --url "<link>" --body-file doc.md \
  --expected-version 7 --version-message "Actualiza contratos de API"
```

`--profile` acepta el path completo o, si pasas solo el nombre, se resuelve a
`~/.jira-profiles/<nombre>.json`.

**Notas de comandos:**

- `create` es **idempotente por título** dentro del espacio: si ya existe una
  página con ese título, la **omite** y te da su link. Con
  `--update-if-exists` la actualiza en lugar de omitirla.
- `--body` permite pasar el markdown inline en vez de un archivo; para
  documentos largos usa siempre `--body-file`.
- `search` restringe al `defaultSpaceKey` del perfil salvo que pases
  `--space <KEY>` o `--all-spaces`.

---

## Reglas de contenido

### Al leer
- Devuelve el contenido **como markdown**, sin reescribirlo ni resumirlo salvo
  que te lo pidan.
- Los elementos que markdown no representa se anotan como comentario
  (`<!-- macro: toc -->`) en vez de perderse en silencio.
- **Limitación:** no se descargan adjuntos ni imágenes. Una imagen aparece
  como `![alt](nombre-archivo.png)` con el nombre del adjunto, no su
  contenido. Los comentarios de la página tampoco se leen.

### Al escribir
El markdown soportado (todo lo demás se preserva como párrafo, nunca se
pierde texto):

| Markdown | Resultado en Confluence |
|---|---|
| `# … ######` | Encabezados h1–h6 |
| `**negrita**`, `_cursiva_`, `~~tachado~~`, `` `código` `` | Formato inline |
| `[texto](url)` | Link |
| `* item` / `1. item` | Listas, **con anidamiento por indentación** |
| `- [ ]` / `- [x]` | Lista de tareas nativa de Confluence |
| `> cita` | Blockquote |
| `\| a \| b \|` + separador | Tabla nativa |
| ```` ```lang ```` | Macro **code** con resaltado de sintaxis |
| `---` | Línea horizontal |

**Reglas de formato — críticas:**

- **Nunca** escribas la secuencia literal `\n` dentro del contenido. Usa
  **saltos de línea reales**.
- Deja una **línea en blanco** entre un encabezado y su primer bullet, y entre
  bloques distintos.
- Una tabla necesita su fila separadora (`| --- | --- |`) o se interpretará
  como texto.
- No escribas XHTML/storage a mano en el markdown: se escapará como texto
  literal. Si necesitas una macro que la skill no cubre, dilo en vez de
  improvisar.

---

## Instalación y alcance

La skill se distribuye dentro del plugin `blue-team-general`. Al instalar el
plugin queda disponible en **todos los proyectos**; se actualiza con
`/plugin update` o `/reload-plugins`.

## Notas

- Requiere `python3` en el PATH (macOS ya lo trae).
- La auth es **Basic** con `email:apiToken` — el mismo mecanismo y el mismo
  token que las skills de Jira.
- **Portabilidad:** para trabajar con otra cuenta u otro cliente, solo se crea
  otro archivo en `~/.jira-profiles/` y se pasa `--profile <ese-nombre>`. El
  script no tiene nada hardcodeado.
- Los tokens **nunca** se imprimen en las salidas ni se commitean: viven solo
  en `~/.jira-profiles/`, fuera del repo.
