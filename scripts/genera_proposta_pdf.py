"""Genera una proposta di viaggio BellaRota in PDF (HTML+CSS → WeasyPrint).

Funzione pura: riceve i dati della proposta (riepilogo scelte del cliente + output
del modello Sonnet) e produce un PDF ben formattato salvato su disco con un token
casuale non indovinabile. Ritorna l'URL pubblico (servito da GET /p/{token}).

Nessun riferimento HTTP qui dentro (pattern del repo: logica pura in scripts/).
"""

from __future__ import annotations

import os
import secrets

from jinja2 import Template
from weasyprint import HTML

# Directory persistente (volume montato sul container python-utils) e base URL pubblico
DATA_DIR = os.environ.get("PROPOSTE_DIR", "/app/data/proposte")
BASE_URL = os.environ.get("PROPOSTE_BASE_URL", "https://bellarota.com/p")

# Palette brand BellaRota
_C = {
    "blu": "#14507E",
    "azul": "#0c3354",
    "laranja": "#E8603C",
    "amarelo": "#F2B53A",
    "verde": "#1E4D40",
    "creme": "#FFF8EE",
    "ceu": "#7CC2D6",
    "papel": "#fbf7ef",
}

_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<style>
  @page {
    size: A4;
    margin: 18mm 16mm 20mm 16mm;
    @bottom-center {
      content: "BellaRota  ·  info@bellarota.com  ·  WhatsApp +39 328 981 7688";
      font-family: Georgia, serif; font-size: 8pt; color: #9aa7b0;
    }
    @bottom-right { content: counter(page) "/" counter(pages); font-size: 8pt; color: #9aa7b0; }
  }
  * { box-sizing: border-box; }
  body { font-family: Georgia, "Times New Roman", serif; color: {{ C.blu }}; margin: 0; line-height: 1.55; }
  h1, h2, h3 { margin: 0; }
  .eyebrow { font-size: 9pt; letter-spacing: 2pt; text-transform: uppercase; color: {{ C.verde }}; margin: 0 0 4pt; }
  /* Copertina */
  .cover { background: linear-gradient(135deg, {{ C.blu }}, {{ C.azul }});
           color: {{ C.creme }}; border-radius: 14pt; padding: 26pt 24pt; margin: 0 0 18pt; }
  .brand { font-size: 20pt; font-weight: bold; letter-spacing: .5pt; margin: 0 0 2pt; }
  .brand span { color: {{ C.amarelo }}; }
  .cover .kicker { color: {{ C.ceu }}; font-size: 9pt; letter-spacing: 2pt; text-transform: uppercase; margin: 0 0 16pt; }
  .cover h1 { font-size: 25pt; line-height: 1.2; margin: 0 0 8pt; }
  .cover .taglio { color: {{ C.amarelo }}; font-size: 12pt; font-style: italic; margin: 0 0 14pt; }
  .cover .meta { font-size: 10pt; color: #dCEaf2; border-top: 1pt solid rgba(255,255,255,.2); padding-top: 10pt; }
  /* Sezioni */
  .sec { margin: 0 0 16pt; }
  .sec h2 { color: {{ C.laranja }}; font-size: 15pt; margin: 0 0 8pt; }
  .card { background: {{ C.papel }}; border: 1pt solid #e7ddca; border-radius: 10pt; padding: 12pt 14pt; }
  .rota { font-size: 11pt; margin: 0 0 10pt; }
  .rota b { color: {{ C.laranja }}; }
  .chips { margin: 0; }
  .chip { display: inline-block; background: #fff; border: 1pt solid {{ C.ceu }}; color: {{ C.blu }};
          border-radius: 20pt; padding: 3pt 9pt; margin: 0 5pt 6pt 0; font-size: 9.5pt; }
  .chip b { color: {{ C.verde }}; }
  ul.inj { list-style: none; padding: 0; margin: 10pt 0 0; }
  ul.inj li { font-size: 10pt; color: {{ C.verde }}; margin: 0 0 4pt; }
  .dica { font-style: italic; color: {{ C.verde }}; margin: 10pt 0 0; }
  .sealed { color: {{ C.laranja }}; font-weight: bold; margin: 6pt 0 0; }
  .abertura { font-size: 12pt; line-height: 1.6; margin: 0 0 12pt; }
  .ideabox { background: {{ C.azul }}; color: {{ C.creme }}; border-radius: 12pt; padding: 16pt 18pt; margin: 0 0 14pt; }
  .ideabox h2 { color: {{ C.creme }}; font-size: 18pt; margin: 0 0 8pt; }
  .ideabox p { color: #dCEaf2; font-size: 11pt; margin: 0; line-height: 1.65; }
  table.dias { width: 100%; border-collapse: collapse; margin: 0 0 6pt; }
  table.dias td { padding: 8pt 0; border-bottom: 1pt solid #e7ddca; vertical-align: top; }
  table.dias td.q { width: 34%; }
  table.dias td.q b { color: {{ C.laranja }}; font-size: 11pt; }
  table.dias td.t { font-size: 10.5pt; padding-left: 12pt; }
  .alts { width: 100%; border-collapse: collapse; }
  .alts td { width: 50%; vertical-align: top; padding: 12pt; background: {{ C.papel }};
             border: 1pt solid #e7ddca; border-radius: 10pt; }
  .alts .at { font-weight: bold; color: {{ C.verde }}; margin: 0 0 5pt; font-size: 11pt; }
  .alts .ar { font-size: 10pt; margin: 0; }
  .moat { font-size: 10pt; color: #6b7a86; font-style: italic; line-height: 1.5;
          border-left: 3pt solid {{ C.amarelo }}; padding: 4pt 0 4pt 12pt; margin: 0 0 14pt; }
  .next { background: {{ C.creme }}; border: 1.5pt dashed {{ C.amarelo }}; border-radius: 12pt; padding: 16pt 18pt; }
  .next h2 { color: {{ C.blu }}; font-size: 14pt; margin: 0 0 8pt; }
  .next ol { margin: 6pt 0 0; padding-left: 18pt; font-size: 10.5pt; }
  .next li { margin: 0 0 5pt; }
  .spacer { height: 6pt; }
</style></head>
<body>

  <div class="cover">
    <p class="brand">Bella<span>Rota</span></p>
    <p class="kicker">sua proposta de viagem</p>
    <h1>{{ titulo }}</h1>
    {% if taglio %}<p class="taglio">{{ taglio }}</p>{% endif %}
    <p class="meta">Preparado para <b>{{ nome }}</b>{% if meta_line %} &nbsp;·&nbsp; {{ meta_line }}{% endif %}</p>
  </div>

  <div class="sec">
    <p class="eyebrow">O que você nos contou</p>
    <div class="card">
      {% if rota %}<p class="rota"><b>Sua rota:</b> {{ rota }}</p>{% endif %}
      <p class="chips">{% for c in chips %}<span class="chip"><b>{{ c.topic }}:</b> {{ c.value }}</span>{% endfor %}</p>
      {% if injections %}<ul class="inj">{% for i in injections %}<li>&#10003; {{ i }}</li>{% endfor %}</ul>{% endif %}
      {% if dica %}<p class="dica">{{ dica }}</p>{% endif %}
      {% if sealed %}<p class="sealed">{{ sealed }}</p>{% endif %}
    </div>
  </div>

  <div class="sec">
    <p class="eyebrow">A viagem que sonhamos pra você</p>
    {% if abertura %}<p class="abertura">{{ abertura }}</p>{% endif %}
    <div class="ideabox">
      <h2>{{ titulo }}</h2>
      {% if narrativa %}<p>{{ narrativa }}</p>{% endif %}
    </div>
    {% if dias %}
    <table class="dias">
      {% for d in dias %}<tr><td class="q"><b>{{ d.quando }}</b></td><td class="t">{{ d.texto }}</td></tr>{% endfor %}
    </table>
    {% endif %}
  </div>

  {% if alternativas %}
  <div class="sec">
    <p class="eyebrow">Ou, se preferir, dois outros caminhos</p>
    <table class="alts"><tr>
      {% for a in alternativas %}<td>
        <p class="at">{{ a.titulo }}</p>
        <p class="ar">{{ a.resumo }}</p>
      </td>{% if not loop.last %}<td style="width:14pt;background:#fff;border:0;">&nbsp;</td>{% endif %}{% endfor %}
    </tr></table>
  </div>
  {% endif %}

  <div class="sec">
    <p class="moat">Essa primeira ideia foi sonhada pela nossa "Máquina". Mas quem constrói a
    viagem de verdade — escolhendo cada hotel, cada restaurante, cada guia, com gente que
    conhecemos pessoalmente na Itália — somos nós dois, à mão.</p>
    <div class="next">
      <h2>Como seguimos a partir daqui</h2>
      <ol>
        <li><b>Gostou da direção?</b> Responda nosso e-mail com <b>1</b> — começamos a construir o roteiro completo.</li>
        <li><b>Quer ajustar algo?</b> Responda com <b>2</b> e conte o que mudaria — refinamos juntos.</li>
        <li><b>Prefere conversar?</b> Responda com <b>3</b> ou chame no WhatsApp +39 328 981 7688.</li>
      </ol>
    </div>
  </div>

</body></html>""",
    autoescape=True,
)


def _clean(value: object) -> str:
    """Stringa safe per il template. Rimuove None e spazi; l'escape HTML dei valori
    interpolati è gestito da jinja (autoescape=True)."""
    return "" if value is None else str(value).strip()


def _build_context(p: dict) -> dict:
    idea = p.get("idea_principal") or {}
    teaser = p.get("teaser") or {}
    recap = p.get("recap") or []
    route = p.get("route") or []
    stops = teaser.get("stops") or []

    # rotta leggibile: preferisci i nomi dal teaser, fallback agli id route
    if stops:
        rota = "  →  ".join(
            f"{_clean(s.get('nome'))} · {s.get('days', '')}d" for s in stops
        )
    else:
        rota = "  →  ".join(
            f"{_clean(r.get('id'))} · {r.get('days', '')}d" for r in route
        )

    travelers = p.get("travelers")
    month = _clean(p.get("month"))
    meta_bits = []
    if month:
        meta_bits.append(month)
    if travelers:
        meta_bits.append(f"{travelers} viajante" + ("s" if travelers != 1 else ""))
    total = p.get("totalDays")
    if total:
        meta_bits.append(f"~{total} dias")

    dias = [
        {"quando": _clean(d.get("quando")), "texto": _clean(d.get("texto"))}
        for d in (idea.get("dias") or [])
        if _clean(d.get("texto"))
    ]
    alternativas = [
        {"titulo": _clean(a.get("titulo")), "resumo": _clean(a.get("resumo"))}
        for a in (p.get("alternativas") or [])
        if _clean(a.get("titulo"))
    ]
    chips = [
        {"topic": _clean(c.get("topic")), "value": _clean(c.get("value"))}
        for c in recap
        if _clean(c.get("value"))
    ]

    return {
        "C": _C,
        "nome": _clean(p.get("nome")) or "viajante",
        "titulo": _clean(idea.get("titulo")) or "Sua viagem pela Itália",
        "taglio": _clean(p.get("taglio")),
        "meta_line": " · ".join(meta_bits),
        "rota": rota,
        "chips": chips,
        "injections": [_clean(i) for i in (teaser.get("injections") or []) if _clean(i)],
        "dica": _clean(teaser.get("dicaSecreta")),
        "sealed": _clean(teaser.get("sealed")),
        "abertura": _clean(p.get("abertura")),
        "narrativa": _clean(idea.get("narrativa")),
        "dias": dias,
        "alternativas": alternativas,
    }


def genera_proposta_pdf(payload: dict) -> dict:
    """Genera il PDF della proposta e lo salva con token casuale.

    Ritorna {"url": "<base>/<token>", "token": "<token>"}.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    ctx = _build_context(payload or {})
    html_str = _TEMPLATE.render(**ctx)
    token = secrets.token_urlsafe(24)
    out_path = os.path.join(DATA_DIR, f"{token}.pdf")
    HTML(string=html_str).write_pdf(out_path)
    return {"url": f"{BASE_URL}/{token}", "token": token}
