import os
import json
import urllib.parse
from urllib.parse import urlparse
from datetime import datetime
import time

import requests
import feedparser
from dotenv import load_dotenv
from openai import OpenAI

# -----------------------------
# Cargar variables de entorno
# -----------------------------
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RADAR_MODE = os.getenv("RADAR_MODE", "brief").strip().lower()

if not OPENAI_API_KEY:
    raise ValueError("Falta OPENAI_API_KEY en .env")
if not TELEGRAM_TOKEN:
    raise ValueError("Falta TELEGRAM_BOT_TOKEN en .env")
if not CHAT_ID:
    raise ValueError("Falta TELEGRAM_CHAT_ID en .env")
if RADAR_MODE not in {"brief", "content"}:
    raise ValueError("RADAR_MODE debe ser 'brief' o 'content'")

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# Configuración
# -----------------------------
OFFICIAL_SOURCES = [
    # OpenAI News. TODO: OpenAI API changelog no expone RSS oficial estable.
    "https://openai.com/news/rss.xml",
    # Claude Code changelog. TODO: Claude app release notes y Anthropic API release notes no exponen RSS oficial estable.
    "https://code.claude.com/docs/en/changelog/rss.xml",
    # Vertex AI Generative AI release notes.
    "https://docs.cloud.google.com/feeds/generative-ai-on-vertex-ai-release-notes.xml",
    # Google Gemini product updates. TODO: Gemini API changelog no expone RSS oficial estable.
    "https://blog.google/products-and-platforms/products/gemini/rss/",
    # Google DeepMind blog.
    "https://deepmind.google/blog/rss.xml",
]

OFFICIAL_DOMAINS = {
    "openai.com",
    "www.openai.com",
    "platform.openai.com",
    "help.openai.com",
    "anthropic.com",
    "www.anthropic.com",
    "docs.anthropic.com",
    "platform.claude.com",
    "support.claude.com",
    "code.claude.com",
    "deepmind.google",
    "www.deepmind.google",
    "blog.google",
    "www.blog.google",
    "ai.googleblog.com",
    "ai.google.dev",
    "cloud.google.com",
    "docs.cloud.google.com",
}

OFFICIAL_SOURCE_TODOS = [
    "OpenAI API changelog: https://platform.openai.com/docs/changelog (sin RSS oficial estable)",
    "ChatGPT release notes: https://help.openai.com/en/articles/6825453-chatgpt-release-notes (sin RSS oficial estable)",
    "Anthropic API release notes: https://docs.anthropic.com/en/release-notes/api (sin RSS oficial estable)",
    "Claude release notes: https://support.claude.com/en/articles/12138966-release-notes (sin RSS oficial estable)",
    "Gemini API release notes: https://ai.google.dev/gemini-api/docs/changelog (sin RSS oficial estable)",
]

# Fallback: radar de releases vía Google News RSS (gratis)
KEYWORDS = [
    "OpenAI API changelog",
    "ChatGPT release notes",
    "OpenAI new model release",
    "Anthropic Claude release notes",
    "Claude Code changelog",
    "Gemini API release notes",
    "Vertex AI Gemini release notes",
    "Google Gemini new model",
    "DeepMind new model",
]

HISTORY_FILE = f"history_{RADAR_MODE}.json"
SELECTED_RELEASE_FILE = "selected_release.json"
RECENT_HOURS = 72  # solo tendencias recientes (3 dias)
MIN_RELEASE_SCORE = 45

def is_recent(published_ts, hours=RECENT_HOURS):
    if not published_ts:
        return False
    now_ts = int(time.time())
    return (now_ts - published_ts) <= hours * 3600

# Para que el mensaje salga SIEMPRE ordenado, forzamos un formato corto.
# Objetivo: 1 release relevante al día + guion 60s listo para grabar.


# -----------------------------
# Historial (anti-repetición)
# -----------------------------
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    try:
        with open(HISTORY_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_history(seen_links):
    with open(HISTORY_FILE, "w") as f:
        json.dump(list(seen_links), f)


def selection_date():
    return datetime.utcnow().strftime("%Y-%m-%d")


def load_selected_release():
    if not os.path.exists(SELECTED_RELEASE_FILE):
        return False, None
    try:
        with open(SELECTED_RELEASE_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return False, None

    if data.get("selected_date_utc") != selection_date():
        return False, None

    return True, data.get("release")


def save_selected_release(release):
    payload = {
        "selected_date_utc": selection_date(),
        "release": release,
    }
    with open(SELECTED_RELEASE_FILE, "w") as f:
        json.dump(payload, f, indent=2)


# -----------------------------
# Utilidades de feeds
# -----------------------------
def parse_feed(url, limit=10):
    feed = feedparser.parse(url)
    items = []

    for entry in feed.entries[:limit]:
        link = getattr(entry, "link", None)
        if not link:
            continue

        domain = urlparse(link).netloc

        # published_parsed/updated_parsed: struct_time (si está disponible)
        published_ts = None
        parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if parsed_time:
            try:
                published_ts = int(time.mktime(parsed_time))
            except Exception:
                published_ts = None

        items.append(
            {
                "title": getattr(entry, "title", "").strip(),
                "link": link,
                "summary": entry.get("summary", ""),
                "source": url,
                "domain": domain,
                "published_ts": published_ts,  # epoch o None
            }
        )

    return items

def google_news_rss(query: str):
    q = urllib.parse.quote(query)
    # Español LATAM + Ecuador
    return f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=EC&ceid=EC:es-419"


def _matches_any(text, terms):
    normalized = " " + text.replace("-", " ").replace("_", " ") + " "
    for term in terms:
        term_l = term.lower()
        if len(term_l) <= 3:
            if f" {term_l} " in normalized:
                return True
        elif term_l in text:
            return True
    return False


def _count_matches(text, terms):
    return sum(1 for term in terms if _matches_any(text, [term]))


def release_score(article):
    """
    Score release-first: modelos, APIs, SDKs, pricing, availability y deprecations.
    Penaliza opinion, prediccion, AGI, rumores y piezas de analisis sin cambio concreto.
    """
    title = article.get("title", "")
    summary = article.get("summary", "")
    link = article.get("link", "")
    source = article.get("source", "")
    domain = (article.get("domain") or "").lower()
    source_kind = article.get("source_kind", "")
    text = urllib.parse.unquote(f"{title} {summary} {link} {source}").lower()

    official_release_domains = {
        "openai.com",
        "www.openai.com",
        "platform.openai.com",
        "help.openai.com",
        "anthropic.com",
        "www.anthropic.com",
        "docs.anthropic.com",
        "platform.claude.com",
        "support.claude.com",
        "code.claude.com",
        "deepmind.google",
        "www.deepmind.google",
        "blog.google",
        "www.blog.google",
        "ai.google.dev",
        "cloud.google.com",
        "docs.cloud.google.com",
        "github.com",
    }
    official_release_paths = [
        "changelog",
        "release-notes",
        "release_notes",
        "releases",
        "docs/changelog",
        "api/docs/changelog",
        "generative-ai/docs/release-notes",
    ]
    release_terms = [
        "release",
        "released",
        "launched",
        "launch",
        "introducing",
        "available",
        "preview",
        "beta",
        "ga",
        "generally available",
        "general availability",
        "pricing",
        "deprecation",
        "deprecated",
        "sdk",
        "api",
        "changelog",
        "release notes",
    ]
    priority_entities = [
        "openai",
        "chatgpt",
        "gpt",
        "sora",
        "claude",
        "anthropic",
        "gemini",
        "deepmind",
        "vertex ai",
    ]
    priority_capabilities = [
        "agents",
        "agent",
        "audio",
        "video",
        "coding",
        "code",
        "multimodal",
        "realtime",
        "function calling",
        "tools",
    ]
    penalty_terms = [
        "agi",
        "prediction",
        "predicts",
        "ceo says",
        "opinion",
        "analysis",
        "rumor",
        "rumour",
        "reportedly",
        "could",
        "might",
        "future of ai",
    ]
    concrete_release_terms = [
        "release",
        "released",
        "launched",
        "introducing",
        "available",
        "model",
        "api",
        "pricing",
        "feature",
        "sdk",
        "changelog",
        "deprecation",
        "rollout",
    ]

    score = 0

    if domain in official_release_domains:
        score += 25
    if any(path in text for path in official_release_paths):
        score += 20
    if source_kind == "official_rss":
        score += 10
    elif source_kind == "google_news_rss":
        score -= 8

    score += 10 * _count_matches(text, release_terms)
    score += 8 * _count_matches(text, priority_entities)
    score += 5 * _count_matches(text, priority_capabilities)
    score -= 15 * _count_matches(text, penalty_terms)

    has_concrete_release = _matches_any(text, concrete_release_terms)
    ceo_or_opinion = _matches_any(
        text,
        ["ceo", "sam altman", "dario amodei", "demis hassabis", "says", "said"],
    )
    if ceo_or_opinion and not has_concrete_release:
        score -= 30

    published_ts = article.get("published_ts")
    if is_recent(published_ts, hours=RECENT_HOURS):
        score += 15
    elif not published_ts:
        score -= 10
    else:
        age_hours = (int(time.time()) - published_ts) / 3600
        score -= 25 if age_hours > 24 * 14 else 10

    return score


# -----------------------------
# Obtener artículos (oficial -> fallback)
# -----------------------------
def fetch_new_articles():
    seen_links = load_history()
    new_seen = set(seen_links)
    articles = []

    # 1) Fuentes oficiales primero
    for url in OFFICIAL_SOURCES:
        for a in parse_feed(url, limit=15):
            if not a.get("link") or a["link"] in seen_links:
                continue

            tier = "confirmed" if a.get("domain") in OFFICIAL_DOMAINS else "trend"
            articles.append({**a, "tier": tier, "source_kind": "official_rss"})
            new_seen.add(a["link"])

    # 2) Fallback Google News si no hay nada o si lo oficial no llega al umbral.
    if not articles or max(release_score(a) for a in articles) < MIN_RELEASE_SCORE:
        for kw in KEYWORDS:
            url = google_news_rss(kw)
            for a in parse_feed(url, limit=10):
                if not a.get("link") or a["link"] in seen_links:
                    continue

                if not is_recent(a.get("published_ts")):
                    continue

                tier = "confirmed" if a.get("domain") in OFFICIAL_DOMAINS else "trend"
                articles.append({**a, "tier": tier, "source_kind": "google_news_rss"})
                new_seen.add(a["link"])

    return articles, new_seen


def fake_test_articles():
    now_ts = int(time.time())
    return [
        {
            "title": "OpenAI releases GPT-5.5 in the API with lower latency and new coding capabilities.",
            "link": "https://platform.openai.com/docs/changelog/test-gpt-5-5",
            "summary": "Official simulated API release with a new GPT model, lower latency, coding capabilities, and availability for builders.",
            "source": "test_mode",
            "domain": "platform.openai.com",
            "published_ts": now_ts,
            "tier": "confirmed",
            "source_kind": "official_rss",
        },
        {
            "title": "Claude Code changelog adds faster coding tools for daily developer work.",
            "link": "https://code.claude.com/docs/en/changelog/test-coding-tools",
            "summary": "Official simulated Claude Code tooling release with new coding tools and better availability for builders.",
            "source": "test_mode",
            "domain": "code.claude.com",
            "published_ts": now_ts,
            "tier": "confirmed",
            "source_kind": "official_rss",
        },
        {
            "title": "Gemini API preview makes realtime audio easier for product teams.",
            "link": "https://blog.google/products-and-platforms/products/gemini/test-realtime-audio",
            "summary": "Official simulated Gemini API preview for realtime audio and multimodal product experiments.",
            "source": "test_mode",
            "domain": "blog.google",
            "published_ts": now_ts,
            "tier": "confirmed",
            "source_kind": "official_rss",
        },
        {
            "title": "CEO predicts AGI will arrive soon.",
            "link": "https://example.com/ceo-predicts-agi",
            "summary": "Opinion and prediction without a concrete model release, API change, pricing update, or feature launch.",
            "source": "test_mode",
            "domain": "example.com",
            "published_ts": now_ts,
            "tier": "trend",
            "source_kind": "test_noise",
        },
    ]


def print_release_scores(articles):
    for article in articles:
        print(f"release_score={release_score(article)} | {article.get('title')}")


# -----------------------------
# Elegir 1 mejor release + generar mensaje estructurado
# -----------------------------
def pick_best_article(articles):
    """
    Queremos 1 solo release real diario.
    Si nada supera MIN_RELEASE_SCORE, no enviamos noticia como release.
    """
    if not articles:
        return None

    scored = []
    for article in articles:
        score = release_score(article)
        scored.append({**article, "release_score": score})

    best = sorted(
        scored,
        key=lambda a: (a.get("release_score", 0), a.get("published_ts") or 0),
        reverse=True,
    )[0]

    if best.get("release_score", 0) < MIN_RELEASE_SCORE:
        return None

    return best


def get_top_releases(limit=3, articles=None):
    if articles is None:
        articles, _ = fetch_new_articles()

    scored = []
    for article in articles:
        score = release_score(article)
        if score >= MIN_RELEASE_SCORE:
            scored.append({**article, "release_score": score})

    ranked = sorted(
        scored,
        key=lambda a: (a.get("release_score", 0), a.get("published_ts") or 0),
        reverse=True,
    )

    return diversify_releases(ranked, limit=limit)


def product_key(article):
    text = f"{article.get('title', '')} {article.get('summary', '')} {article.get('link', '')}".lower()

    if "claude code" in text or "code.claude.com" in text:
        return "claude_code"
    if "chatgpt" in text:
        return "chatgpt"
    if "gemini api" in text or "ai.google.dev" in text:
        return "gemini_api"
    if "platform.openai.com" in text or "openai api" in text:
        return "openai_api"
    if "openai" in text or "gpt" in text or "sora" in text:
        return "openai"
    if "gemini" in text:
        return "gemini"
    if "vertex ai" in text or "docs.cloud.google.com" in text:
        return "vertex_ai"
    if "deepmind" in text:
        return "deepmind"

    domain = (article.get("domain") or "").lower()
    return domain or "unknown"


def diversify_releases(ranked_articles, limit=3):
    selected = []
    used_products = set()
    used_providers = set()

    def add_if_allowed(article, require_new_provider=False):
        provider = provider_name(article)
        product = product_key(article)
        provider_product = (provider, product)

        if provider_product in used_products:
            return False
        if require_new_provider and provider in used_providers:
            return False

        selected.append(article)
        used_products.add(provider_product)
        used_providers.add(provider)
        return True

    for article in ranked_articles:
        if len(selected) >= limit:
            break
        add_if_allowed(article, require_new_provider=True)

    for article in ranked_articles:
        if len(selected) >= limit:
            break
        if article in selected:
            continue
        add_if_allowed(article, require_new_provider=False)

    return selected[:limit]


def fetch_articles_for_selection():
    if os.getenv("TEST_MODE") == "1":
        articles = fake_test_articles()
        new_seen = load_history()
        print("TEST_MODE=1 activo. Usando artículos falsos.")
        print_release_scores(articles)
        return articles, new_seen

    return fetch_new_articles()


def get_top_release():
    """
    Seleccion unica del release del dia.
    brief selecciona y guarda selected_release.json.
    content reutiliza ese archivo para no elegir otro item del mismo changelog.
    """
    if RADAR_MODE == "content":
        found, selected = load_selected_release()
        if not found:
            raise ValueError(
                "RADAR_MODE=content requiere selected_release.json generado hoy por RADAR_MODE=brief"
            )
        print("Reutilizando release seleccionado desde selected_release.json.")
        return selected, load_history()

    articles, new_seen = fetch_articles_for_selection()
    top_releases = get_top_releases(limit=1, articles=articles)
    best = top_releases[0] if top_releases else None
    save_selected_release(best)
    return best, new_seen


def get_brief_releases():
    articles, new_seen = fetch_articles_for_selection()
    top_releases = get_top_releases(limit=3, articles=articles)
    save_selected_release(top_releases[0] if top_releases else None)
    return top_releases, new_seen


def provider_name(article):
    text = f"{article.get('title', '')} {article.get('summary', '')} {article.get('link', '')}".lower()
    domain = (article.get("domain") or "").lower()

    if "openai" in text or "chatgpt" in text or "gpt" in text or "sora" in text:
        return "OpenAI"
    if "anthropic" in text or "claude" in text or "code.claude.com" in text:
        return "Anthropic"
    if (
        "gemini" in text
        or "deepmind" in text
        or "vertex ai" in text
        or "blog.google" in domain
        or "docs.cloud.google.com" in domain
    ):
        return "Google"
    return domain or "Fuente oficial"


def provider_product_label(article):
    provider = provider_name(article)
    product = product_key(article)
    labels = {
        "claude_code": "Claude Code",
        "chatgpt": "ChatGPT",
        "openai_api": "API",
        "openai": "OpenAI",
        "gemini_api": "Gemini API",
        "gemini": "Gemini",
        "vertex_ai": "Vertex AI",
        "deepmind": "DeepMind",
    }
    product_label = labels.get(product)
    return f"{provider} / {product_label}" if product_label else provider


def looks_like_version_title(title):
    cleaned = title.strip().lower().lstrip("v")
    if not cleaned:
        return True
    if len(cleaned) <= 12 and all(c.isdigit() or c in ".-" for c in cleaned):
        return True
    parts = cleaned.split()
    return len(parts) == 1 and any(c.isdigit() for c in cleaned) and "." in cleaned


def clean_summary_text(summary):
    text = " ".join((summary or "").replace("\n", " ").split())
    while "<" in text and ">" in text:
        start = text.find("<")
        end = text.find(">", start)
        if end == -1:
            break
        text = text[:start] + " " + text[end + 1 :]
        text = " ".join(text.split())
    return text


def human_summary_fragment(summary):
    text = clean_summary_text(summary)
    replacements = [
        (" for Claude Code", ""),
        (" for Gemini API", ""),
        (", and ", ", "),
        (" and ", " y "),
        ("Improves ", "mejora "),
        ("Fixes ", "corrige "),
        ("Adds ", "agrega "),
        ("New ", "nuevo "),
        ("remote login", "login remoto"),
        ("project cleanup", "limpieza de proyectos"),
        ("MCP gateways", "gateways MCP"),
        ("gateways", "gateways"),
        ("terminal rendering", "visualizacion de terminal"),
        ("shell handling", "manejo de terminal"),
        ("lower latency", "menor latencia"),
        ("coding capabilities", "capacidades de programacion"),
        ("realtime audio", "audio en tiempo real"),
        ("generally available", "disponible de forma general"),
        ("available", "disponible"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def human_title(article, max_len=110):
    title = (article.get("title") or "").replace("\n", " ").strip()
    if title and not looks_like_version_title(title):
        final_title = title
    else:
        summary = human_summary_fragment(article.get("summary", ""))
        product = provider_product_label(article).split(" / ")[-1]
        if summary:
            final_title = f"{product} {summary}"
        else:
            final_title = f"{product} trae una actualizacion oficial relevante"

    final_title = final_title.rstrip(".")
    if len(final_title) <= max_len:
        return final_title
    return final_title[: max_len - 3].rstrip() + "..."


def build_brief_top3(top_releases):
    today = datetime.now().strftime("%Y-%m-%d")

    if not top_releases:
        return (
            "AI RELEASE RADAR TOP 3 (Rodri)\n"
            f"FECHA: {today}\n\n"
            "No hay lanzamientos relevantes nuevos hoy.\n"
        )

    lines = [
        "AI RELEASE RADAR TOP 3 (Rodri)",
        f"FECHA: {today}",
        "",
    ]

    for i, article in enumerate(top_releases, start=1):
        lines.extend(
            [
                f"{i}. {provider_product_label(article)}",
                f"   TITULAR: {human_title(article)}",
                f"   SCORE: {article.get('release_score')}",
                f"   LINK: {article.get('link')}",
                "",
            ]
        )

    recommendation_index = 1
    recommendation = (
        f"Publica primero el #{recommendation_index} porque tiene el score mas alto "
        "y es el release con mejor mezcla de fuente oficial, novedad e impacto practico."
    )

    lines.extend(["", "RECOMENDACION:", recommendation])
    return "\n".join(lines)


def build_prompt(today: str, best, mode: str):
    # best es 1 solo release detectado por scoring deterministico
    title = (best.get("title") or "").replace("\n", " ").strip()
    summary = (best.get("summary") or "").replace("\n", " ").strip()
    link = best.get("link") or ""
    source_kind = best.get("source_kind")
    tier = best.get("tier")
    score = best.get("release_score")

    context = (
        f"ESTADO: {tier}\n"
        f"FUENTE: {source_kind}\n"
        f"RELEASE_SCORE: {score}\n"
        f"PUBLICADO_TS: {best.get('published_ts')}\n"
        f"DOMINIO: {best.get('domain')}\n"
        f"TITULO: {title}\n"
        f"RESUMEN: {summary}\n"
        f"LINK: {link}\n"
    )

    base_rules = f"""
Actua como un creador de contenido que explica lanzamientos reales de IA de forma simple y lista para grabar.
Tu audiencia: rectores, gerentes, emprendedores, creators y builders no necesariamente tecnicos.

Objetivo:
Convertir UN lanzamiento real o cambio concreto en una pieza clara, util y con criterio.

Reglas:
- Maximo 300 palabras total.
- Lenguaje simple.
- Cero jerga innecesaria.
- Escribe como creador de contenido, no como ingeniero.
- Mantén precisión, pero simplifica al máximo.
- Suena como alguien que ya implemento IA en la vida real y sabe donde se pierde tiempo.
- Autoridad tranquila: claro, directo, con criterio, sin agresividad.
- No sonar como consultor.
- No sonar como paper.
- No incluir tablas.
- No incluir analisis largo.
- No hagas editorial estrategico ni predicciones.
- No conviertas opiniones en noticia si no hay lanzamiento real.
- No inventes datos, fechas, benchmarks, disponibilidad ni precios.

Contexto del item elegido:
{context}
"""

    if mode == "content":
        prompt = f"""
{base_rules}

Salida obligatoria. Usa exactamente este formato:
AI RELEASE RADAR (Rodri)
FECHA: {today}

GUION TIKTOK/REEL 60s:
Hook: maximo 12 palabras, conversacional, basado en problema real o beneficio.
Explicacion: dilo como si se lo contaras a una persona ocupada.
Impacto: explica que cambia en la vida/trabajo de alguien, sin jerga.
Accion: una cosa simple que probarias hoy.
Cierre: no uses CTA generico; refuerza autoridad con tono de experiencia real.

CAPTION:
Texto corto para publicar. Humano, claro, con autoridad tranquila.

3 HOOKS ALTERNATIVOS:
1.
2.
3.

PREGUNTA PARA COMENTARIOS:
Una pregunta concreta, no generica.

FRASE FINAL:
Debe reforzar autoridad o valor practico. Ejemplos de tono: "Si trabajas con IA en serio, esto si importa" o "Este tipo de cambios separan el toy del sistema real".

LINK:
URL verificable.
"""
    else:
        prompt = f"""
{base_rules}

Salida obligatoria. Usa exactamente este formato:
AI RELEASE RADAR (Rodri)
FECHA: {today}

TITULAR:
1 frase clara y simple, como algo que alguien diria en voz alta.
Enfocate en beneficio directo, no en el numero de version ni en tono de changelog.
Puedes usar lenguaje humano o emocional si ayuda: frustracion, bloqueo, ahorro de tiempo o alivio real.
Evita palabras como "integracion", "configuracion" y "flujo".

QUE CAMBIO:
Maximo 3 lineas:
- que salio
- que hace
- por que es diferente

POR QUE IMPORTA EN SIMPLE:
Maximo 3 lineas, explicado para un rector, gerente o emprendedor.
Debe iniciar con: "Esto significa algo simple:"
Debe entenderse en 5 segundos. Evita terminos tecnicos si hay una palabra mas simple.
Traduce todo a impacto practico y conectalo con experiencia real del usuario: tiempo, costo, errores, adopcion o calidad.

EJEMPLO REAL:
Universidad: 1 ejemplo claro.
Fintech/Cooperativa: 1 ejemplo claro.

LINK:
URL verificable.
"""
    return prompt.strip()


def generate_signal(best):
    today = datetime.now().strftime("%Y-%m-%d")

    if not best:
        return (
            "AI RELEASE RADAR (Rodri)\n"
            f"FECHA: {today}\n\n"
            "No hay lanzamientos relevantes nuevos hoy.\n"
        )

    prompt = build_prompt(today, best, RADAR_MODE)

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )
    return response.output_text.strip()

# -----------------------------
# Enviar a Telegram (1 mensaje idealmente)
# -----------------------------
def send_to_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Telegram límite ~4096. Buscamos 1 mensaje; si se pasa, lo partimos.
    if len(text) <= 4000:
        response = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=20)
        response.raise_for_status()
        return

    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        response = requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=20)
        response.raise_for_status()


# -----------------------------
# Ejecución principal
# -----------------------------
if __name__ == "__main__":
    if RADAR_MODE == "brief":
        top_releases, new_seen = get_brief_releases()
        msg = build_brief_top3(top_releases)
    else:
        best, new_seen = get_top_release()
        msg = generate_signal(best)

    send_to_telegram(msg)
    save_history(new_seen)
    print("✅ AI Release Radar enviado a Telegram.")
