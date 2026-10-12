#!/usr/bin/env python3
"""Cliente Confluence Cloud para la skill confluence.

Solo usa la librería estándar de Python 3 (sin pip install).
Reutiliza el mismo perfil de ~/.jira-profiles/<nombre>.json que las skills de
Jira: la auth Basic (email + apiToken) es la misma para todo el sitio Atlassian.

Subcomandos:
  check     -> valida conexión y (si aplica) el espacio por defecto
  resolve   -> traduce un link de Confluence a pageId / espacio / título
  read      -> lee una página y la devuelve en markdown
  children  -> lista el árbol de páginas bajo una página o espacio
  search    -> busca páginas por texto o CQL
  create    -> crea una página desde markdown (idempotente por título)
  update    -> actualiza una página existente desde markdown

Al escribir, cada bloque ```mermaid se sube como macro de la app Mermaid de
Confluence (`confluence-mermaid-macro`), que lo renderiza en la página. Con
`--mermaid image` se renderiza a PNG y se adjunta (para sitios sin la app).

Todas las salidas relevantes se imprimen como JSON por stdout.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser


# --------------------------------------------------------------------------- #
# Perfil / HTTP                                                                #
# --------------------------------------------------------------------------- #

def resolve_profile_path(value):
    """Acepta path completo o nombre de perfil (-> ~/.jira-profiles/<n>.json)."""
    if os.path.sep in value or value.endswith(".json"):
        return os.path.expanduser(value)
    return os.path.expanduser(os.path.join("~", ".jira-profiles", value + ".json"))


def load_profile(value):
    """Carga el perfil Atlassian unificado.

    Solo exige lo que Confluence necesita (baseUrl + auth); los campos de Jira
    (projectKey, boardId...) se ignoran si están presentes.
    """
    path = resolve_profile_path(value)
    if not os.path.exists(path):
        die("No se encontró el perfil Atlassian en: %s\n"
            "Crea el archivo siguiendo confluence.profile.example.json y "
            "colócalo en ~/.jira-profiles/<nombre>.json" % path)
    with open(path, "r", encoding="utf-8") as fh:
        try:
            prof = json.load(fh)
        except json.JSONDecodeError as exc:
            die("El perfil %s no es JSON válido: %s" % (path, exc))
    missing = []
    if not prof.get("baseUrl"):
        missing.append("baseUrl")
    if not prof.get("auth", {}).get("email") or not prof.get("auth", {}).get("apiToken"):
        missing.append("auth.email/auth.apiToken")
    if missing:
        die("Al perfil %s le faltan campos: %s" % (path, ", ".join(missing)))
    prof.setdefault("confluence", {})
    prof["baseUrl"] = prof["baseUrl"].rstrip("/")
    prof["_path"] = path
    return prof


def auth_header(profile):
    raw = "%s:%s" % (profile["auth"]["email"], profile["auth"]["apiToken"])
    token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return "Basic " + token


def _build_request(profile, method, path, body=None, query=None):
    url = path if path.startswith("http") else profile["baseUrl"] + path
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", auth_header(profile))
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    return req


def request(profile, method, path, body=None, query=None):
    """Devuelve (status_code, parsed_json_or_text)."""
    req = _build_request(profile, method, path, body, query)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, _parse(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _parse(exc.read())
    except urllib.error.URLError as exc:
        die("No se pudo conectar a %s: %s" % (profile["baseUrl"], exc.reason))


def request_final_url(profile, path):
    """GET siguiendo redirecciones; devuelve la URL final (para tiny links)."""
    req = _build_request(profile, "GET", path)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.geturl()
    except urllib.error.HTTPError as exc:
        return exc.url if getattr(exc, "url", None) else None
    except urllib.error.URLError as exc:
        die("No se pudo conectar a %s: %s" % (profile["baseUrl"], exc.reason))


def _parse(raw):
    if not raw:
        return None
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def die(msg, payload=None):
    out = {"ok": False, "error": msg}
    if payload is not None:
        out["detail"] = payload
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(1)


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# Resolución de links -> pageId                                                #
# --------------------------------------------------------------------------- #

_RE_PAGES = re.compile(r"/pages/(?:edit-v2/|viewpage\.action)?(\d+)")
_RE_BLOG = re.compile(r"/blog/\d{4}/\d{1,2}/\d{1,2}/(\d+)")
_RE_SPACE = re.compile(r"/(?:wiki/)?spaces/([^/?#]+)")
_RE_TINY = re.compile(r"/wiki/x/([A-Za-z0-9_\-]+)")


def _slug(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def find_space(profile, key):
    """Busca un espacio por su key, o por el slug que aparece en la URL.

    El slug de `/wiki/spaces/<slug>/` se deriva del *nombre* del espacio y no
    siempre coincide con su key (p. ej. nombre "MediKairos" -> slug
    "medikairos", key "Kairos"). Por eso, si el filtro directo no encuentra
    nada, se recorre la lista de espacios comparando key y nombre.
    """
    status, data = request(profile, "GET", "/wiki/api/v2/spaces",
                           query={"keys": key, "limit": 5})
    if status == 200 and isinstance(data, dict):
        results = data.get("results") or []
        if results:
            return results[0]

    wanted = _slug(key)
    path = "/wiki/api/v2/spaces?limit=250"
    while path:
        status, data = request(profile, "GET", path)
        if status != 200 or not isinstance(data, dict):
            return None
        for space in data.get("results") or []:
            if _slug(space.get("key")) == wanted or _slug(space.get("name")) == wanted:
                return space
        path = (data.get("_links") or {}).get("next")
    return None


def resolve_target(profile, value):
    """Traduce un link (o un id suelto) de Confluence a un pageId.

    Soporta:
      - .../wiki/spaces/KEY/pages/123456789/Titulo
      - .../wiki/spaces/KEY/pages/edit-v2/123456789
      - .../wiki/spaces/KEY/blog/2024/05/01/123456789/Titulo
      - .../wiki/pages/viewpage.action?pageId=123456789
      - .../wiki/x/AbCdE            (tiny link, se resuelve por redirección)
      - .../wiki/spaces/KEY         (usa la homepage del espacio)
      - un pageId numérico suelto
    """
    value = (value or "").strip()
    if not value:
        die("Falta el link o el pageId de la página.")

    if value.isdigit():
        return {"pageId": value, "via": "id"}

    parsed = urllib.parse.urlparse(value)
    qs = urllib.parse.parse_qs(parsed.query or "")
    if "pageId" in qs and qs["pageId"]:
        return {"pageId": qs["pageId"][0], "via": "query"}

    m = _RE_PAGES.search(parsed.path or value)
    if m:
        return {"pageId": m.group(1), "via": "url"}

    m = _RE_BLOG.search(parsed.path or value)
    if m:
        return {"pageId": m.group(1), "via": "blog"}

    m = _RE_TINY.search(parsed.path or value)
    if m:
        final = request_final_url(profile, parsed.path)
        if final:
            m2 = _RE_PAGES.search(final) or _RE_BLOG.search(final)
            if m2:
                return {"pageId": m2.group(1), "via": "tiny"}
            qs2 = urllib.parse.parse_qs(urllib.parse.urlparse(final).query or "")
            if qs2.get("pageId"):
                return {"pageId": qs2["pageId"][0], "via": "tiny"}
        die("No se pudo resolver el tiny link %s. Abre el link en el navegador "
            "y pásame la URL larga (la que incluye /pages/<id>/)." % value)

    m = _RE_SPACE.search(parsed.path or value)
    if m:
        key = urllib.parse.unquote(m.group(1))
        space = find_space(profile, key)
        if not space:
            die("El espacio '%s' no existe o no tienes acceso en %s."
                % (key, profile["baseUrl"]))
        home = space.get("homepageId")
        if not home:
            die("El espacio '%s' no tiene homepage; pásame el link de una "
                "página concreta." % key)
        return {"pageId": str(home), "spaceKey": key, "via": "space-homepage"}

    die("No reconozco '%s' como link de Confluence ni como pageId." % value)


def page_url(profile, page):
    """URL navegable de una página a partir de la respuesta de la API v2."""
    links = page.get("_links") or {}
    webui = links.get("webui")
    if webui:
        return profile["baseUrl"] + "/wiki" + webui
    return "%s/wiki/pages/viewpage.action?pageId=%s" % (profile["baseUrl"], page.get("id"))


def get_page(profile, page_id, body_format="storage"):
    query = {"body-format": body_format} if body_format else None
    status, data = request(profile, "GET", "/wiki/api/v2/pages/%s" % page_id,
                           query=query)
    if status == 404:
        die("No existe la página %s (o tu cuenta no tiene acceso)." % page_id)
    if status != 200 or not isinstance(data, dict):
        die("Error leyendo la página %s (HTTP %s)." % (page_id, status), data)
    return data


def space_key_by_id(profile, space_id, cache={}):
    if not space_id:
        return None
    space_id = str(space_id)
    if space_id in cache:
        return cache[space_id]
    status, data = request(profile, "GET", "/wiki/api/v2/spaces/%s" % space_id)
    key = data.get("key") if status == 200 and isinstance(data, dict) else None
    cache[space_id] = key
    return key


# --------------------------------------------------------------------------- #
# storage (XHTML) -> markdown                                                  #
# --------------------------------------------------------------------------- #

VOID_TAGS = {"br", "hr", "img", "col", "input", "meta", "link",
             "ri:page", "ri:attachment", "ri:url", "ri:user", "ri:space",
             "ri:blog-post", "ri:card-appearance"}

BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5",
              "h6", "ul", "ol", "li", "hr", "table", "thead", "tbody", "tr",
              "blockquote", "pre", "ac:structured-macro", "ac:layout",
              "ac:layout-section", "ac:layout-cell", "ac:task-list", "ac:task",
              "ac:rich-text-body", "ac:plain-text-body"}

TRANSPARENT_TAGS = {"div", "section", "article", "ac:layout", "ac:layout-section",
                    "ac:layout-cell", "ac:rich-text-body", "body", "html"}


class _Node(object):
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children = []


class _StorageParser(HTMLParser):
    """Construye un árbol simple a partir del storage format (XHTML)."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = _Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag:
                del self.stack[idx:]
                return
        # Cierre huérfano: se ignora.

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)

    def unknown_decl(self, data):
        # <![CDATA[ ... ]]> dentro de ac:plain-text-body
        if data.startswith("CDATA["):
            self.stack[-1].children.append(data[6:])


def _attr(node, name):
    return node.attrs.get(name) or ""


def _macro_param(node, name):
    for child in node.children:
        if isinstance(child, _Node) and child.tag == "ac:parameter" \
                and _attr(child, "ac:name") == name:
            return _plain_text(child.children).strip()
    return ""


def _macro_child(node, tag):
    for child in node.children:
        if isinstance(child, _Node) and child.tag == tag:
            return child
    return None


def _plain_text(nodes):
    parts = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(node)
        else:
            parts.append(_plain_text(node.children))
    return "".join(parts)


def _clean_inline(text):
    """Colapsa espacios manteniendo los saltos duros marcados con \\n."""
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(lines)


def _render_inline(nodes):
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(node.replace(" ", " "))
            continue
        tag = node.tag
        inner = _render_inline(node.children)
        if tag in ("strong", "b"):
            out.append("**%s**" % inner.strip() if inner.strip() else "")
        elif tag in ("em", "i"):
            out.append("_%s_" % inner.strip() if inner.strip() else "")
        elif tag in ("del", "s", "strike"):
            out.append("~~%s~~" % inner.strip() if inner.strip() else "")
        elif tag == "code":
            out.append("`%s`" % inner.strip() if inner.strip() else "")
        elif tag == "br":
            out.append("\n")
        elif tag == "a":
            href = _attr(node, "href")
            text = inner.strip() or href
            out.append("[%s](%s)" % (text, href) if href else text)
        elif tag == "ac:link":
            out.append(_render_ac_link(node, inner))
        elif tag == "ac:image":
            out.append(_render_ac_image(node))
        elif tag == "time":
            out.append(_attr(node, "datetime") or inner)
        elif tag == "ac:structured-macro":
            out.append(_render_inline_macro(node))
        elif tag in ("ri:page", "ri:attachment", "ri:url", "ri:user"):
            out.append("")
        else:
            out.append(inner)
    return "".join(out)


def _render_ac_link(node, inner):
    """Link interno de Confluence: se conserva el título de la página."""
    body = ""
    for child in node.children:
        if isinstance(child, _Node) and child.tag in ("ac:link-body",
                                                      "ac:plain-text-link-body"):
            body = _render_inline(child.children).strip()
            break
    target = ""
    anchor = _attr(node, "ac:anchor")
    for child in node.children:
        if isinstance(child, _Node) and child.tag == "ri:page":
            target = _attr(child, "ri:content-title")
        elif isinstance(child, _Node) and child.tag == "ri:attachment":
            target = _attr(child, "ri:filename")
    text = body or target or anchor or inner.strip()
    if target and body and body != target:
        return "%s (→ %s)" % (body, target)
    return text


def _render_ac_image(node):
    for child in node.children:
        if isinstance(child, _Node) and child.tag == "ri:attachment":
            return "![%s](%s)" % (_attr(node, "ac:alt"), _attr(child, "ri:filename"))
        if isinstance(child, _Node) and child.tag == "ri:url":
            return "![%s](%s)" % (_attr(node, "ac:alt"), _attr(child, "ri:value"))
    return "![imagen]()"


def _render_inline_macro(node):
    name = _attr(node, "ac:name")
    if name == "status":
        return "`%s`" % (_macro_param(node, "title") or "status")
    if name in ("jira", "jira-issues"):
        key = _macro_param(node, "key")
        return "`%s`" % key if key else "`[jira]`"
    return ""


def _render_blocks(nodes, indent=""):
    """Devuelve una lista de bloques markdown ya indentados."""
    blocks = []
    buffer_nodes = []

    def flush():
        if not buffer_nodes:
            return
        text = _clean_inline(_render_inline(buffer_nodes)).strip()
        del buffer_nodes[:]
        if text:
            blocks.append(_indent_block(text, indent))

    for node in nodes:
        if isinstance(node, str):
            if node.strip() or buffer_nodes:
                buffer_nodes.append(node)
            continue
        if node.tag in BLOCK_TAGS:
            flush()
            blocks.extend(_render_block(node, indent))
        else:
            buffer_nodes.append(node)
    flush()
    return [b for b in blocks if b.strip()]


def _indent_block(text, indent):
    if not indent:
        return text
    return "\n".join(indent + ln if ln else ln for ln in text.split("\n"))


def _render_block(node, indent):
    tag = node.tag

    if tag in TRANSPARENT_TAGS:
        return _render_blocks(node.children, indent)

    if tag == "hr":
        return [indent + "---"]

    if re.match(r"^h[1-6]$", tag):
        level = int(tag[1])
        text = _clean_inline(_render_inline(node.children)).strip().replace("\n", " ")
        return [indent + "#" * level + " " + text] if text else []

    if tag == "p":
        text = _clean_inline(_render_inline(node.children)).strip()
        return [_indent_block(text, indent)] if text else []

    if tag in ("ul", "ol"):
        return _render_list(node, indent)

    if tag == "ac:task-list":
        return _render_task_list(node, indent)

    if tag == "blockquote":
        inner = _render_blocks(node.children, "")
        body = "\n\n".join(inner)
        quoted = "\n".join(indent + "> " + ln if ln else indent + ">"
                           for ln in body.split("\n"))
        return [quoted] if body.strip() else []

    if tag == "pre":
        code = _plain_text(node.children).strip("\n")
        return [_indent_block("```\n%s\n```" % code, indent)]

    if tag == "table":
        return _render_table(node, indent)

    if tag == "ac:structured-macro":
        return _render_macro_block(node, indent)

    if tag in ("ac:rich-text-body", "ac:plain-text-body"):
        return _render_blocks(node.children, indent)

    if tag in ("thead", "tbody", "tr", "li", "ac:task"):
        return _render_blocks(node.children, indent)

    return _render_blocks(node.children, indent)


def _render_list(node, indent):
    ordered = node.tag == "ol"
    blocks = []
    counter = 0
    for child in node.children:
        if not isinstance(child, _Node) or child.tag != "li":
            continue
        counter += 1
        marker = ("%d. " % counter) if ordered else "* "
        inner = _render_blocks(child.children, "")
        if not inner:
            continue
        first = inner[0]
        rest = inner[1:]
        pad = " " * len(marker)
        first_lines = first.split("\n")
        item = indent + marker + first_lines[0]
        for ln in first_lines[1:]:
            item += "\n" + indent + pad + ln
        for extra in rest:
            item += "\n" + "\n".join(indent + pad + ln if ln else ln
                                     for ln in extra.split("\n"))
        blocks.append(item)
    if not blocks:
        return []
    return ["\n".join(blocks)]


def _render_task_list(node, indent):
    lines = []
    for child in node.children:
        if not isinstance(child, _Node) or child.tag != "ac:task":
            continue
        status = ""
        body = None
        for sub in child.children:
            if isinstance(sub, _Node) and sub.tag == "ac:task-status":
                status = _plain_text(sub.children).strip()
            elif isinstance(sub, _Node) and sub.tag == "ac:task-body":
                body = sub
        text = ""
        if body is not None:
            text = _clean_inline(_render_inline(body.children)).strip().replace("\n", " ")
        mark = "x" if status == "complete" else " "
        lines.append("%s- [%s] %s" % (indent, mark, text))
    return ["\n".join(lines)] if lines else []


def _cell_text(cell):
    text = _clean_inline(_render_inline(cell.children)).strip()
    return text.replace("\n", " ").replace("|", "\\|")


def _render_table(node, indent):
    rows = []
    header_flags = []

    def walk(container):
        for child in container.children:
            if not isinstance(child, _Node):
                continue
            if child.tag == "tr":
                cells = []
                is_header = False
                for cell in child.children:
                    if isinstance(cell, _Node) and cell.tag in ("th", "td"):
                        cells.append(_cell_text(cell))
                        if cell.tag == "th":
                            is_header = True
                if cells:
                    rows.append(cells)
                    header_flags.append(is_header)
            elif child.tag in ("thead", "tbody", "tfoot"):
                walk(child)

    walk(node)
    if not rows:
        return []

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    if header_flags and header_flags[0]:
        header, body = rows[0], rows[1:]
    else:
        header, body = rows[0], rows[1:]

    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join([" --- "] * width) + "|"]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return [_indent_block("\n".join(lines), indent)]


ADMONITIONS = {"info": "INFO", "note": "NOTA", "warning": "ATENCIÓN",
               "tip": "TIP", "panel": "PANEL", "expand": "DETALLE"}


MERMAID_MACRO = "confluence-mermaid-macro"


def _mermaid_macro_code(raw):
    """Extrae el código del cuerpo de la macro: JSON `[{"body": ..., "date": ...}]`
    con el historial de versiones del diagrama; la vigente es la última."""
    try:
        versions = json.loads(raw)
        return versions[-1]["body"]
    except (ValueError, LookupError, TypeError):
        return raw


def _render_macro_block(node, indent):
    name = _attr(node, "ac:name")

    if name == "code":
        lang = _macro_param(node, "language")
        body = _macro_child(node, "ac:plain-text-body")
        code = _plain_text(body.children).strip("\n") if body is not None else ""
        return [_indent_block("```%s\n%s\n```" % (lang, code), indent)]

    if name == MERMAID_MACRO:
        body = _macro_child(node, "ac:plain-text-body")
        code = _mermaid_macro_code(
            _plain_text(body.children) if body is not None else "")
        return [_indent_block("```mermaid\n%s\n```" % code.strip("\n"), indent)]

    if name in ADMONITIONS:
        label = ADMONITIONS[name]
        title = _macro_param(node, "title")
        body = _macro_child(node, "ac:rich-text-body")
        inner = _render_blocks(body.children, "") if body is not None else []
        head = "**%s**" % label + (": %s" % title if title else "")
        content = "\n\n".join([head] + inner)
        return ["\n".join(indent + "> " + ln if ln else indent + ">"
                          for ln in content.split("\n"))]

    if name in ("toc", "children", "pagetree"):
        return [indent + "<!-- macro: %s -->" % name]

    body = _macro_child(node, "ac:rich-text-body")
    if body is not None:
        inner = _render_blocks(body.children, indent)
        if inner:
            return [indent + "<!-- macro: %s -->" % name] + inner
    plain = _macro_child(node, "ac:plain-text-body")
    if plain is not None:
        text = _plain_text(plain.children).strip()
        if text:
            return [_indent_block("```\n%s\n```" % text, indent)]
    return [indent + "<!-- macro: %s -->" % name] if name else []


def storage_to_markdown(storage):
    parser = _StorageParser()
    parser.feed(storage or "")
    parser.close()
    blocks = _render_blocks(parser.root.children, "")
    text = "\n\n".join(blocks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n" if text.strip() else ""


# --------------------------------------------------------------------------- #
# markdown -> storage (XHTML)                                                  #
# --------------------------------------------------------------------------- #

_INLINE_RE = re.compile(
    r"`(?P<code>[^`]+?)`"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|(?<!\w)_(?P<emu>[^_]+?)_(?!\w)"
    r"|(?<![\w*])\*(?P<ems>[^*\n]+?)\*(?![\w*])"
    r"|~~(?P<del>.+?)~~"
    r"|!\[(?P<ialt>[^\]]*)\]\((?P<isrc>[^)]+)\)"
    r"|\[(?P<ltext>[^\]]+)\]\((?P<lhref>[^)]+)\)")


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def esc_attr(text):
    return esc(text).replace('"', "&quot;")


def md_inline(text):
    """Convierte inline markdown a XHTML. Escapa primero, marca después."""
    return _md_inline_escaped(esc(text))


def _image_storage(src, alt=""):
    """Imagen: URL externa o adjunto de la página (por nombre de archivo)."""
    alt_attr = ' ac:alt="%s"' % alt.replace('"', "&quot;") if alt else ""
    src = src.replace('"', "&quot;")
    if re.match(r"^https?://", src):
        ref = '<ri:url ri:value="%s" />' % src
    else:
        ref = '<ri:attachment ri:filename="%s" />' % src
    return "<ac:image%s>%s</ac:image>" % (alt_attr, ref)


def _md_inline_escaped(src):
    out = []
    pos = 0
    for m in _INLINE_RE.finditer(src):
        if m.start() > pos:
            out.append(src[pos:m.start()])
        if m.group("code") is not None:
            out.append("<code>%s</code>" % m.group("code"))
        elif m.group("bold") is not None:
            out.append("<strong>%s</strong>" % _md_inline_escaped(m.group("bold")))
        elif m.group("emu") is not None:
            out.append("<em>%s</em>" % _md_inline_escaped(m.group("emu")))
        elif m.group("ems") is not None:
            out.append("<em>%s</em>" % _md_inline_escaped(m.group("ems")))
        elif m.group("del") is not None:
            out.append("<del>%s</del>" % _md_inline_escaped(m.group("del")))
        elif m.group("isrc") is not None:
            out.append(_image_storage(m.group("isrc"), m.group("ialt")))
        else:
            href = m.group("lhref").replace('"', "&quot;")
            out.append('<a href="%s">%s</a>' % (href, m.group("ltext")))
        pos = m.end()
    if pos < len(src):
        out.append(src[pos:])
    return "".join(out)


def _indent_width(line):
    expanded = line.replace("\t", "    ")
    return len(expanded) - len(expanded.lstrip(" "))


_RE_BULLET = re.compile(r"^(\s*)[\*\-\+]\s+(?!\[[ xX]\]\s)(.*)$")
_RE_ORDERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_RE_TASK = re.compile(r"^(\s*)[\*\-\+]\s+\[([ xX])\]\s+(.*)$")
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_HR = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_RE_FENCE = re.compile(r"^\s*```+\s*([A-Za-z0-9+#_\-]*)\s*$")
_RE_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_RE_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _is_table_row(line):
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def markdown_to_storage(text, diagrams=None):
    """Convierte el subconjunto de markdown que usamos a storage format.

    Si se pasa la lista `diagrams`, cada bloque ```mermaid se añade a ella y en
    su lugar queda un marcador que `_resolve_diagrams` sustituye después por
    la macro de Mermaid, la imagen adjunta o el bloque de código.

    Soporta: encabezados, párrafos, reglas (---), listas anidadas (viñeta y
    numeradas), listas de tareas (- [ ] / - [x]), citas (>), tablas,
    bloques de código con ``` (macro `code` de Confluence) e inline
    (**negrita**, _cursiva_, `código`, ~~tachado~~, [texto](url)).
    Cualquier línea no reconocida se preserva como párrafo.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out = []
    para = []

    def flush():
        if para:
            out.append("<p>%s</p>" % "<br />".join(md_inline(p) for p in para))
            del para[:]

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()

        if s == "":
            flush()
            i += 1
            continue

        m = _RE_FENCE.match(raw)
        if m:
            flush()
            lang = m.group(1) or ""
            i += 1
            body = []
            while i < n and not _RE_FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # cierre
            if lang.lower() == "mermaid" and diagrams is not None:
                diagrams.append("\n".join(body))
                out.append(_DIAGRAM_MARK % (len(diagrams) - 1))
            else:
                out.append(_code_macro("\n".join(body), lang))
            continue

        if _RE_HR.match(s):
            flush()
            out.append("<hr />")
            i += 1
            continue

        m = _RE_HEADING.match(s)
        if m:
            flush()
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, md_inline(m.group(2).strip()), level))
            i += 1
            continue

        if _is_table_row(raw) and i + 1 < n and _RE_TABLE_SEP.match(lines[i + 1]):
            flush()
            html, i = _consume_table(lines, i, n)
            out.append(html)
            continue

        if _RE_QUOTE.match(raw):
            flush()
            body = []
            while i < n and (_RE_QUOTE.match(lines[i]) or
                             (lines[i].strip() and body and
                              not _RE_HEADING.match(lines[i].strip()))):
                m2 = _RE_QUOTE.match(lines[i])
                body.append(m2.group(1) if m2 else lines[i].strip())
                i += 1
            inner = markdown_to_storage("\n".join(body), diagrams)
            out.append("<blockquote>%s</blockquote>" % inner)
            continue

        if _RE_TASK.match(raw) or _RE_BULLET.match(raw) or _RE_ORDERED.match(raw):
            flush()
            html, i = _consume_list(lines, i, n, _indent_width(raw))
            out.append(html)
            continue

        para.append(s)
        i += 1

    flush()
    return "".join(out)


def _code_macro(code, lang):
    params = ""
    if lang:
        params = '<ac:parameter ac:name="language">%s</ac:parameter>' % esc_attr(lang)
    return ('<ac:structured-macro ac:name="code" ac:schema-version="1">'
            '%s<ac:plain-text-body><![CDATA[%s]]></ac:plain-text-body>'
            '</ac:structured-macro>' % (params, code.replace("]]>", "]]]]><![CDATA[>")))


def _consume_table(lines, i, n):
    header = _split_row(lines[i])
    i += 2  # fila de encabezado + separador
    rows = []
    while i < n and _is_table_row(lines[i]):
        rows.append(_split_row(lines[i]))
        i += 1
    width = max([len(header)] + [len(r) for r in rows]) if rows else len(header)
    html = ["<table><tbody><tr>"]
    for idx in range(width):
        cell = header[idx] if idx < len(header) else ""
        html.append("<th>%s</th>" % md_inline(cell))
    html.append("</tr>")
    for row in rows:
        html.append("<tr>")
        for idx in range(width):
            cell = row[idx] if idx < len(row) else ""
            html.append("<td>%s</td>" % md_inline(cell))
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html), i


def _list_kind(line):
    if _RE_TASK.match(line):
        return "task"
    if _RE_BULLET.match(line):
        return "ul"
    if _RE_ORDERED.match(line):
        return "ol"
    return None


def _list_item_text(line):
    m = _RE_TASK.match(line)
    if m:
        return m.group(3), (m.group(2).lower() == "x")
    m = _RE_BULLET.match(line)
    if m:
        return m.group(2), None
    m = _RE_ORDERED.match(line)
    if m:
        return m.group(2), None
    return line.strip(), None


def _consume_list(lines, i, n, base_indent):
    """Consume una lista (con anidamiento por indentación) desde lines[i]."""
    kind = _list_kind(lines[i])
    items = []
    while i < n:
        line = lines[i]
        if not line.strip():
            # Una línea en blanco solo corta si lo que sigue no es la lista.
            if i + 1 < n and _list_kind(lines[i + 1]) and \
                    _indent_width(lines[i + 1]) >= base_indent:
                i += 1
                continue
            break
        this_kind = _list_kind(line)
        if not this_kind:
            break
        width = _indent_width(line)
        if width < base_indent:
            break
        if width > base_indent:
            nested, i = _consume_list(lines, i, n, width)
            if items:
                items[-1]["children"].append(nested)
            continue
        if this_kind != kind:
            break
        text, done = _list_item_text(line)
        items.append({"text": text, "done": done, "children": []})
        i += 1

    if kind == "task":
        html = ["<ac:task-list>"]
        for it in items:
            status = "complete" if it["done"] else "incomplete"
            html.append("<ac:task><ac:task-status>%s</ac:task-status>"
                        "<ac:task-body>%s%s</ac:task-body></ac:task>"
                        % (status, md_inline(it["text"]), "".join(it["children"])))
        html.append("</ac:task-list>")
        return "".join(html), i

    tag = "ol" if kind == "ol" else "ul"
    html = ["<%s>" % tag]
    for it in items:
        html.append("<li>%s%s</li>" % (md_inline(it["text"]), "".join(it["children"])))
    html.append("</%s>" % tag)
    return "".join(html), i


# --------------------------------------------------------------------------- #
# check                                                                        #
# --------------------------------------------------------------------------- #

def cmd_check(profile, args):
    result = {"ok": True, "profile": profile.get("profileName") or profile["_path"],
              "baseUrl": profile["baseUrl"], "connection": False}

    status, me = request(profile, "GET", "/wiki/rest/api/user/current")
    if status in (401, 403):
        die("No se pudo autenticar contra Confluence (HTTP %s). Revisa "
            "auth.email / auth.apiToken en %s." % (status, profile["_path"]), me)
    if status != 200 or not isinstance(me, dict):
        die("No se pudo conectar a Confluence (HTTP %s). Revisa que baseUrl "
            "(%s) sea el sitio correcto y que Confluence esté habilitado."
            % (status, profile["baseUrl"]), me)
    result["connection"] = True
    result["account"] = me.get("displayName")
    result["accountId"] = me.get("accountId")

    key = args.space or profile["confluence"].get("defaultSpaceKey")
    if key:
        space = find_space(profile, key)
        if not space:
            die("El espacio '%s' no existe o tu cuenta no tiene acceso en %s."
                % (key, profile["baseUrl"]))
        result["space"] = {"key": space.get("key"), "id": space.get("id"),
                           "name": space.get("name"),
                           "homepageId": space.get("homepageId")}
    else:
        result["space"] = None
        result["note"] = ("El perfil no define confluence.defaultSpaceKey; "
                          "tendrás que pasar --space al crear páginas.")
    emit(result)


# --------------------------------------------------------------------------- #
# resolve / read                                                               #
# --------------------------------------------------------------------------- #

def cmd_resolve(profile, args):
    target = resolve_target(profile, args.url)
    page = get_page(profile, target["pageId"], body_format=None)
    emit({"ok": True, "pageId": page.get("id"), "title": page.get("title"),
          "spaceKey": space_key_by_id(profile, page.get("spaceId")),
          "spaceId": page.get("spaceId"), "parentId": page.get("parentId"),
          "version": (page.get("version") or {}).get("number"),
          "status": page.get("status"), "resolvedVia": target["via"],
          "url": page_url(profile, page)})


def cmd_read(profile, args):
    target = resolve_target(profile, args.url)
    fmt = "storage" if args.format in ("markdown", "storage") else args.format
    page = get_page(profile, target["pageId"], body_format=fmt)
    body = ((page.get("body") or {}).get(fmt) or {}).get("value") or ""

    content = body if args.format == "storage" else storage_to_markdown(body)
    meta = {"ok": True, "pageId": page.get("id"), "title": page.get("title"),
            "spaceKey": space_key_by_id(profile, page.get("spaceId")),
            "version": (page.get("version") or {}).get("number"),
            "format": args.format, "chars": len(content),
            "url": page_url(profile, page)}

    if args.out:
        path = os.path.expanduser(args.out)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            if args.format != "storage":
                fh.write("# %s\n\n" % page.get("title"))
            fh.write(content)
        meta["out"] = path
    else:
        meta["content"] = content
    emit(meta)


# --------------------------------------------------------------------------- #
# children                                                                     #
# --------------------------------------------------------------------------- #

def _children(profile, page_id):
    items = []
    path = "/wiki/api/v2/pages/%s/children?limit=250" % page_id
    while path:
        status, data = request(profile, "GET", path)
        if status != 200 or not isinstance(data, dict):
            die("Error listando hijos de %s (HTTP %s)." % (page_id, status), data)
        items.extend(data.get("results") or [])
        nxt = (data.get("_links") or {}).get("next")
        path = nxt if nxt else None
    return items


def _tree(profile, page_id, depth, base_url):
    if depth <= 0:
        return []
    nodes = []
    for child in _children(profile, page_id):
        node = {"pageId": child.get("id"), "title": child.get("title"),
                "url": "%s/wiki/pages/viewpage.action?pageId=%s"
                       % (base_url, child.get("id"))}
        sub = _tree(profile, child.get("id"), depth - 1, base_url)
        if sub:
            node["children"] = sub
        nodes.append(node)
    return nodes


def cmd_children(profile, args):
    target = resolve_target(profile, args.url)
    page = get_page(profile, target["pageId"], body_format=None)
    tree = _tree(profile, target["pageId"], max(1, args.depth), profile["baseUrl"])

    def count(nodes):
        return sum(1 + count(nd.get("children") or []) for nd in nodes)

    emit({"ok": True, "root": {"pageId": page.get("id"), "title": page.get("title"),
                               "url": page_url(profile, page)},
          "depth": args.depth, "total": count(tree), "tree": tree})


# --------------------------------------------------------------------------- #
# search                                                                       #
# --------------------------------------------------------------------------- #

def _cql_quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cmd_search(profile, args):
    if args.cql:
        cql = args.cql
    elif args.text:
        parts = ["type=page", "text ~ %s" % _cql_quote(args.text)]
        key = args.space or profile["confluence"].get("defaultSpaceKey")
        if key and not args.all_spaces:
            parts.insert(0, "space=%s" % _cql_quote(key))
        cql = " AND ".join(parts)
    else:
        die("Pasa --text <palabras> o --cql <consulta>.")

    status, data = request(profile, "GET", "/wiki/rest/api/search",
                           query={"cql": cql, "limit": args.limit})
    if status != 200 or not isinstance(data, dict):
        die("Error en la búsqueda (HTTP %s). Revisa la sintaxis CQL."
            % status, data)

    base = (data.get("_links") or {}).get("base") or (profile["baseUrl"] + "/wiki")
    results = []
    for item in data.get("results") or []:
        content = item.get("content") or {}
        results.append({
            "pageId": content.get("id"),
            "type": content.get("type"),
            "title": item.get("title") or content.get("title"),
            "space": ((item.get("resultGlobalContainer") or {}).get("title")),
            "lastModified": item.get("lastModified"),
            "url": base + item.get("url", "") if item.get("url") else None,
        })
    emit({"ok": True, "cql": cql, "count": len(results), "results": results})


# --------------------------------------------------------------------------- #
# create / update                                                              #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# diagramas mermaid -> macro de la app, PNG adjunto o código                   #
# --------------------------------------------------------------------------- #

_DIAGRAM_MARK = "@@MERMAID-DIAGRAM-%d@@"
MERMAID_CLI_PACKAGE = "@mermaid-js/mermaid-cli"
MERMAID_MODES = ("macro", "image", "code")


def _mermaid_macro(code):
    """Macro de la app Mermaid de Confluence, con el formato que ella guarda."""
    body = json.dumps([{"body": code, "date": int(time.time() * 1000)}],
                      ensure_ascii=False)
    return ('<ac:structured-macro ac:name="%s" ac:schema-version="1">'
            '<ac:parameter ac:name="theme">default</ac:parameter>'
            '<ac:parameter ac:name="alignment">left</ac:parameter>'
            '<ac:parameter ac:name="look">classic</ac:parameter>'
            '<ac:plain-text-body><![CDATA[%s]]></ac:plain-text-body>'
            '</ac:structured-macro>'
            % (MERMAID_MACRO, body.replace("]]>", "]]]]><![CDATA[>")))


def _mermaid_command():
    if shutil.which("mmdc"):
        return ["mmdc"]
    if shutil.which("npx"):
        return ["npx", "-y", MERMAID_CLI_PACKAGE]
    return None


def _diagram_filename(code):
    digest = hashlib.sha1(code.strip().encode("utf-8")).hexdigest()[:12]
    return "mermaid-%s.png" % digest


def render_mermaid(code, out_path):
    """Renderiza `code` a PNG en `out_path`. Devuelve None o el motivo del fallo."""
    cmd = _mermaid_command()
    if not cmd:
        return ("No hay renderizador de Mermaid: instala Node.js (npx) o "
                "`npm install -g %s`." % MERMAID_CLI_PACKAGE)
    src = out_path[:-4] + ".mmd"
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(code + "\n")
    try:
        proc = subprocess.run(
            cmd + ["-i", src, "-o", out_path, "-b", "white", "-s", "2"],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "No se pudo ejecutar mermaid-cli: %s" % exc
    if proc.returncode != 0 or not os.path.exists(out_path):
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return "mermaid-cli falló: %s" % " | ".join(tail)
    return None


def attachment_exists(profile, page_id, filename):
    status, data = request(
        profile, "GET", "/wiki/rest/api/content/%s/child/attachment" % page_id,
        query={"filename": filename, "limit": 1})
    return status == 200 and isinstance(data, dict) and bool(data.get("results"))


def upload_attachment(profile, page_id, path, filename):
    """Sube un archivo como adjunto de la página. Devuelve None o el error."""
    boundary = "----confluence-skill-%s" % uuid.uuid4().hex
    with open(path, "rb") as fh:
        content = fh.read()
    body = b"".join([
        ("--%s\r\n" % boundary).encode("ascii"),
        ('Content-Disposition: form-data; name="file"; filename="%s"\r\n'
         % filename).encode("utf-8"),
        b"Content-Type: image/png\r\n\r\n", content, b"\r\n",
        ("--%s\r\n" % boundary).encode("ascii"),
        b'Content-Disposition: form-data; name="minorEdit"\r\n\r\ntrue\r\n',
        ("--%s--\r\n" % boundary).encode("ascii")])
    url = "%s/wiki/rest/api/content/%s/child/attachment" % (profile["baseUrl"], page_id)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", auth_header(profile))
    req.add_header("Accept", "application/json")
    req.add_header("X-Atlassian-Token", "nocheck")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    try:
        with urllib.request.urlopen(req, timeout=60):
            return None
    except urllib.error.HTTPError as exc:
        return "HTTP %s al subir %s: %s" % (
            exc.code, filename, exc.read().decode("utf-8", "replace")[:300])
    except urllib.error.URLError as exc:
        return "No se pudo subir %s: %s" % (filename, exc.reason)


def _resolve_diagrams(profile, page_id, storage, diagrams, mode="macro"):
    """Sustituye los marcadores de diagrama. Devuelve (storage, informe).

    - `macro`: macro de la app Mermaid de Confluence (la renderiza la página).
    - `image`: PNG adjunto a la página; necesita `page_id`. Si falla el
      renderizado o la subida, ese diagrama queda como código.
    - `code`: bloque de código.
    """
    report = {"total": len(diagrams), "mode": mode, "images": 0, "warnings": []}
    if not diagrams:
        return storage, report
    workdir = tempfile.mkdtemp(prefix="confluence-mermaid-")
    try:
        for index, code in enumerate(diagrams):
            html = None
            if mode == "macro":
                html = _mermaid_macro(code)
            elif mode == "image" and page_id:
                filename = _diagram_filename(code)
                error = None
                if not attachment_exists(profile, page_id, filename):
                    path = os.path.join(workdir, filename)
                    error = (render_mermaid(code, path) or
                             upload_attachment(profile, page_id, path, filename))
                if error:
                    report["warnings"].append("Diagrama %d: %s" % (index + 1, error))
                else:
                    html = ('<ac:image ac:align="center" ac:alt="Diagrama %d">'
                            '<ri:attachment ri:filename="%s" /></ac:image>'
                            % (index + 1, filename))
                    report["images"] += 1
            if html is None:
                html = _code_macro(code, "mermaid")
            storage = storage.replace(_DIAGRAM_MARK % index, html)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return storage, report


def _diagram_fields(report):
    if not report["total"]:
        return {}
    out = {"mermaidDiagrams": report["total"], "mermaidMode": report["mode"]}
    if report["mode"] == "image":
        out["mermaidAsImages"] = report["images"]
    if report["warnings"]:
        out["mermaidWarnings"] = report["warnings"]
    return out


def read_body(args):
    if args.body_file:
        path = os.path.expanduser(args.body_file)
        if not os.path.exists(path):
            die("No existe el archivo de contenido: %s" % path)
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    if args.body is not None:
        return args.body
    die("Pasa el contenido con --body-file <archivo.md> o --body <texto>.")


def find_page_by_title(profile, space_id, title):
    status, data = request(profile, "GET", "/wiki/api/v2/pages",
                           query={"space-id": space_id, "title": title,
                                  "status": "current", "limit": 5})
    if status != 200 or not isinstance(data, dict):
        return None
    for page in data.get("results") or []:
        if (page.get("title") or "").strip() == title.strip():
            return page
    return None


def cmd_create(profile, args):
    key = args.space or profile["confluence"].get("defaultSpaceKey")
    if not key:
        die("No indicaste espacio. Pasa --space <KEY> o define "
            "confluence.defaultSpaceKey en %s." % profile["_path"])
    space = find_space(profile, key)
    if not space:
        die("El espacio '%s' no existe o tu cuenta no tiene acceso." % key)

    markdown = read_body(args)
    diagrams = []
    storage = markdown_to_storage(markdown, diagrams)
    mode = args.mermaid

    parent_id = None
    if args.parent:
        parent_id = resolve_target(profile, args.parent)["pageId"]
    elif profile["confluence"].get("defaultParentUrl"):
        parent_id = resolve_target(
            profile, profile["confluence"]["defaultParentUrl"])["pageId"]

    existing = find_page_by_title(profile, space["id"], args.title)
    if existing and not args.update_if_exists:
        emit({"ok": True, "skipped": True,
              "reason": "Ya existe una página con ese título en el espacio.",
              "pageId": existing.get("id"), "title": args.title,
              "url": page_url(profile, existing),
              "hint": "Usa update --url <link> o create --update-if-exists."})
        return
    if existing and args.update_if_exists:
        _do_update(profile, existing.get("id"), args.title, storage,
                   args.dry_run, args.version_message,
                   diagrams=diagrams, mode=mode)
        return

    # En modo `image` los adjuntos necesitan una página que ya exista: se crea
    # primero con los diagramas como código y se actualiza después.
    initial, report = _resolve_diagrams(profile, None, storage, diagrams, mode)
    payload = {"spaceId": space["id"], "status": "current",
               "title": args.title,
               "body": {"representation": "storage", "value": initial}}
    if parent_id:
        payload["parentId"] = parent_id

    if args.dry_run:
        out = {"ok": True, "dryRun": True, "action": "create",
               "space": key, "title": args.title, "parentId": parent_id,
               "storageChars": len(initial), "storagePreview": initial[:1200]}
        if diagrams:
            out["mermaidDiagrams"] = len(diagrams)
        emit(out)
        return

    status, data = request(profile, "POST", "/wiki/api/v2/pages", body=payload)
    if status not in (200, 201) or not isinstance(data, dict):
        die("No se pudo crear la página (HTTP %s)." % status, data)

    if diagrams and mode == "image":
        final, report = _resolve_diagrams(profile, data.get("id"), storage,
                                          diagrams, mode)
        if report["images"]:
            version = (data.get("version") or {}).get("number") or 1
            update = {"id": str(data.get("id")), "status": "current",
                      "title": args.title,
                      "body": {"representation": "storage", "value": final},
                      "version": {"number": version + 1,
                                  "message": "Diagramas Mermaid como imagen"}}
            status, updated = request(
                profile, "PUT", "/wiki/api/v2/pages/%s" % data.get("id"), body=update)
            if status in (200, 201) and isinstance(updated, dict):
                data = updated
            else:
                report["warnings"].append(
                    "La página se creó, pero no se pudieron insertar las "
                    "imágenes (HTTP %s); los diagramas quedaron como código." % status)
                report["images"] = 0

    out = {"ok": True, "action": "created", "pageId": data.get("id"),
           "title": data.get("title"), "space": key,
           "version": (data.get("version") or {}).get("number"),
           "url": page_url(profile, data)}
    out.update(_diagram_fields(report))
    emit(out)


def _do_update(profile, page_id, new_title, storage, dry_run, message,
               expected_version=None, diagrams=None, mode="macro"):
    current = get_page(profile, page_id, body_format=None)
    version = (current.get("version") or {}).get("number") or 1
    title = new_title or current.get("title")

    if expected_version is not None and int(expected_version) != int(version):
        die("Conflicto de versión: esperabas la v%s pero la página va en la v%s "
            "(alguien la editó). Vuelve a leerla antes de escribir."
            % (expected_version, version))

    diagrams = diagrams or []
    if dry_run:
        # El simulacro no renderiza ni sube adjuntos.
        storage, _ = _resolve_diagrams(profile, None, storage, diagrams, mode)
        out = {"ok": True, "dryRun": True, "action": "update",
               "pageId": page_id, "title": title,
               "currentVersion": version, "nextVersion": version + 1,
               "storageChars": len(storage), "storagePreview": storage[:1200]}
        if diagrams:
            out["mermaidDiagrams"] = len(diagrams)
        emit(out)
        return

    storage, report = _resolve_diagrams(profile, page_id, storage, diagrams,
                                        mode)

    payload = {"id": str(page_id), "status": "current", "title": title,
               "body": {"representation": "storage", "value": storage},
               "version": {"number": version + 1,
                           "message": message or "Actualizado desde Claude Code"}}
    status, data = request(profile, "PUT", "/wiki/api/v2/pages/%s" % page_id,
                           body=payload)
    if status not in (200, 201) or not isinstance(data, dict):
        die("No se pudo actualizar la página %s (HTTP %s)." % (page_id, status), data)
    out = {"ok": True, "action": "updated", "pageId": data.get("id"),
           "title": data.get("title"),
           "version": (data.get("version") or {}).get("number"),
           "previousVersion": version, "url": page_url(profile, data)}
    out.update(_diagram_fields(report))
    emit(out)


def cmd_update(profile, args):
    target = resolve_target(profile, args.url)
    markdown = read_body(args)
    diagrams = []
    storage = markdown_to_storage(markdown, diagrams)
    _do_update(profile, target["pageId"], args.title, storage, args.dry_run,
               args.version_message, args.expected_version,
               diagrams=diagrams, mode=args.mermaid)


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(
        description="Cliente Confluence Cloud (perfil compartido con Jira).")
    parser.add_argument("--profile", required=True,
                        help="Nombre del perfil o path a ~/.jira-profiles/<n>.json")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("check", help="Valida conexión y espacio por defecto")
    p.add_argument("--space", help="Space key a validar (default: el del perfil)")

    p = sub.add_parser("resolve", help="Link de Confluence -> pageId")
    p.add_argument("--url", required=True)

    p = sub.add_parser("read", help="Lee una página y la devuelve en markdown")
    p.add_argument("--url", required=True, help="Link de Confluence o pageId")
    p.add_argument("--format", default="markdown",
                   choices=["markdown", "storage"])
    p.add_argument("--out", help="Guarda el contenido en un archivo")

    p = sub.add_parser("children", help="Árbol de páginas bajo una página/espacio")
    p.add_argument("--url", required=True)
    p.add_argument("--depth", type=int, default=1)

    p = sub.add_parser("search", help="Busca páginas por texto o CQL")
    p.add_argument("--text", help="Palabras a buscar")
    p.add_argument("--cql", help="Consulta CQL cruda")
    p.add_argument("--space", help="Restringe al espacio (default: el del perfil)")
    p.add_argument("--all-spaces", action="store_true",
                   help="Ignora el espacio por defecto y busca en todo el sitio")
    p.add_argument("--limit", type=int, default=25)

    p = sub.add_parser("create", help="Crea una página desde markdown")
    p.add_argument("--space", help="Space key (default: el del perfil)")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", help="Archivo .md con el contenido")
    p.add_argument("--body", help="Contenido markdown inline")
    p.add_argument("--parent", help="Link o pageId de la página padre")
    p.add_argument("--update-if-exists", action="store_true",
                   help="Si ya existe una página con ese título, la actualiza")
    p.add_argument("--version-message", help="Mensaje de versión")
    p.add_argument("--mermaid", choices=MERMAID_MODES, default="macro",
                   help="Cómo subir los bloques mermaid: macro de la app de "
                        "Confluence (default), image (PNG adjunto) o code")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("update", help="Actualiza una página existente")
    p.add_argument("--url", required=True, help="Link de Confluence o pageId")
    p.add_argument("--title", help="Nuevo título (opcional)")
    p.add_argument("--body-file", help="Archivo .md con el contenido")
    p.add_argument("--body", help="Contenido markdown inline")
    p.add_argument("--expected-version", type=int,
                   help="Falla si la página ya no va en esta versión")
    p.add_argument("--version-message", help="Mensaje de versión")
    p.add_argument("--mermaid", choices=MERMAID_MODES, default="macro",
                   help="Cómo subir los bloques mermaid: macro de la app de "
                        "Confluence (default), image (PNG adjunto) o code")
    p.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(2)

    profile = load_profile(args.profile)
    handlers = {"check": cmd_check, "resolve": cmd_resolve, "read": cmd_read,
                "children": cmd_children, "search": cmd_search,
                "create": cmd_create, "update": cmd_update}
    handlers[args.command](profile, args)


if __name__ == "__main__":
    main()
