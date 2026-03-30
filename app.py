import json
import re
import os
import urllib.error
import urllib.request
from flask import Flask, request, jsonify, send_from_directory

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static", static_url_path="")


def _webhook_urls():
    raw = os.getenv("DISCORD_WEBHOOK_URLS", "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    single = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    return [single] if single else []


TOMS_VALIDOS = frozenset(
    "C C# D D# E F F# G G# A A# B Db Eb Gb Ab Bb".split()
)


def _format_louvor_line(item) -> str:
    if isinstance(item, dict):
        mus = (item.get("musica") or "").strip()
        tom = (item.get("tom") or "").strip()
        if tom and tom not in TOMS_VALIDOS:
            tom = ""
        if not mus and not tom:
            return ""
        parts = []
        if mus:
            parts.append(mus)
        else:
            parts.append("(música não selecionada)")
        bits = []
        if tom:
            bits.append("Tom: %s" % tom)
        line = "• " + parts[0]
        if bits:
            line += " — " + " — ".join(bits)
        return line
    s = str(item).strip()
    return ("• %s" % s) if s else ""


def _louvores_lines_from_payload(data: dict):
    raw = data.get("louvores")
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return [_format_louvor_line(x) for x in raw]
    if isinstance(raw, list):
        return [("• %s" % str(x).strip()) for x in raw if str(x).strip()]
    out = []
    for i in range(1, 5):
        s = (data.get("louvor_%d" % i) or "").strip()
        if s:
            out.append("• %s" % s)
    return out


def _format_message(data: dict) -> str:
    raw_data_culto = (data.get("data_culto") or "").strip()
    data_culto = raw_data_culto or "(sem data)"

    # Input type="date" envia YYYY-MM-DD; o projeto quer exibir DD/MM/AAAA.
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", data_culto)
    if m:
        data_culto = f"{m.group(3)}/{m.group(2)}/{m.group(1)}"

    titulo = (data.get("titulo") or "").strip()
    roupa = (data.get("roupa") or "").strip()
    obs = (data.get("observacoes") or "").strip()

    louvor_lines = [ln for ln in _louvores_lines_from_payload(data) if ln]
    louvores_fmt = "\n".join(louvor_lines) or "• (não informado)"

    sem_data = data_culto == "(sem data)"
    if titulo and not sem_data:
        tema = "%s · %s 🎵" % (titulo, data_culto)
    elif titulo:
        tema = "%s 🎵" % titulo
    elif not sem_data:
        tema = "%s 🎵" % data_culto
    else:
        tema = "(não informado)"

    lines = [
        "**Tema do culto:** %s" % tema,
        "",
        "**Repertório**",
        louvores_fmt,
    ]
    if roupa:
        lines.extend(["", "**Roupa:**", roupa])
    if obs:
        lines.extend(["", "**Observações:**", obs])
    return "\n".join(lines)


def _post_discord(url: str, body: dict):
    # Cloudflare (Discord) bloqueia muitas vezes o User-Agent padrão do Python (403 / 1010).
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "RepertorioDiscord/1.0 (webhook; +https://discord.com/developers/docs/resources/webhook)",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.getcode()


@app.post("/api/repertorio")
def enviar_repertorio():
    urls = _webhook_urls()
    if not urls:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "DISCORD_WEBHOOK_URL(S) não configurado no servidor.",
                }
            ),
            500,
        )

    payload = request.get_json(silent=True) or {}
    content = _format_message(payload)
    discord_body = {"content": content}
    errors = []
    for url in urls:
        try:
            code = _post_discord(url, discord_body)
            if code not in (200, 204):
                errors.append("%s" % code)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            errors.append("HTTP %s: %s" % (e.code, body))
        except urllib.error.URLError as e:
            errors.append(str(e.reason))

    if errors and len(errors) == len(urls):
        return jsonify({"ok": False, "error": "; ".join(errors)}), 502

    return jsonify({"ok": True, "message": content, "warnings": errors})


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/musicais.js")
def musicais_js():
    return send_from_directory(app.static_folder, "musicais.js")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
