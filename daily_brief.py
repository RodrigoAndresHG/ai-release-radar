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

if not OPENAI_API_KEY:
    raise ValueError("Falta OPENAI_API_KEY en .env")
if not TELEGRAM_TOKEN:
    raise ValueError("Falta TELEGRAM_BOT_TOKEN en .env")
if not CHAT_ID:
    raise ValueError("Falta TELEGRAM_CHAT_ID en .env")

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

HISTORY_FILE = "history.json"
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


def build_prompt(today: str, best):
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

    prompt = f"""
Actua como un radar de lanzamientos de productos y modelos de IA.
Tu audiencia son creators, builders, equipos de tecnologia junior, gerentes y CIOs que necesitan saber que cambio concreto acaba de salir.

Objetivo:
Convertir UN lanzamiento real o cambio concreto en un mensaje claro y accionable.

Reglas:
- Release-first: explica que producto, modelo, API, SDK, pricing, rollout, deprecation o feature cambio.
- No hagas editorial estrategico ni predicciones.
- No conviertas opiniones de CEOs en noticia si no hay lanzamiento, disponibilidad, modelo, API, pricing o feature concreta.
- No uses rumores, "reportedly", predicciones AGI ni articulos de analisis como release.
- Si falta evidencia oficial, dilo claramente y baja el tono.
- No inventes datos, fechas, benchmarks, disponibilidad ni precios.

Contexto del item elegido:
{context}

Clasifica TIPO_EVENTO usando solo una opcion:
model_release | product_launch | api_change | pricing_change | availability_change | deprecation | feature_release | sdk_tooling | none

Guia:
- model_release: nuevo GPT/Claude/Gemini/Gemma/Sora/Veo/Lyria/etc.
- product_launch: nueva app o producto oficial.
- api_change: nuevo endpoint, API, capability o cambio de plataforma.
- pricing_change: cambio de precios, limites o billing.
- availability_change: GA, preview, beta, region, plan o rollout.
- deprecation: retiro, reemplazo o fecha de fin.
- feature_release: agentes, audio, video, coding, multimodalidad, realtime, tools.
- sdk_tooling: SDK, CLI, changelog developer, Claude Code, librerias.

Salida obligatoria (formato exacto, ordenado, facil de leer):
AI RELEASE RADAR (Rodri)
FECHA: {today}
PROVEEDOR:
TIPO_EVENTO:

TITULAR:
1 frase clara y corta.

QUE CAMBIO:
2-4 lineas. Di exactamente que se lanzo, cambio o quedo disponible.

POR_QUE_IMPORTA:
3 bullets max. Enfocate en decisiones practicas.

IMPACTO_PARA_CREATORS_Y_BUILDERS:
2-4 bullets sobre que pueden construir, probar, migrar o vigilar.

CASO_APLICADO:
Un ejemplo concreto y simple para una universidad, cooperativa, fintech, creator o equipo dev.

GUION 60s (listo para grabar):
Hook (0-5s): 1 frase que sorprenda sin exagerar.
Parte 1 (5-20s): que cambio, explicado facil.
Parte 2 (20-40s): que habilita para creators/builders.
Parte 3 (40-55s): que probaria hoy.
Cierre (55-60s): invitacion a comentar.

LINK:
URL verificable.

Importante:
- No inventes datos.
- No uses lenguaje alarmista ni grandilocuente.
- Si no puedes confirmar que sea release real, TIPO_EVENTO debe ser none y debes decirlo.
"""
    return prompt.strip()


def generate_signal(best):
    today = datetime.now().strftime("%Y-%m-%d")

    if not best:
        return (
            "AI RELEASE RADAR (Rodri)\n"
            f"FECHA: {today}\n"
            "PROVEEDOR: -\n"
            "TIPO_EVENTO: none\n\n"
            "TITULAR:\n"
            "No hay lanzamientos relevantes nuevos hoy.\n\n"
            "LINK:\n-\n"
        )

    prompt = build_prompt(today, best)

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
    if os.getenv("TEST_MODE") == "1":
        articles = fake_test_articles()
        new_seen = load_history()
        print("TEST_MODE=1 activo. Usando artículos falsos.")
        print_release_scores(articles)
    else:
        articles, new_seen = fetch_new_articles()

    best = pick_best_article(articles)
    msg = generate_signal(best)
    send_to_telegram(msg)
    save_history(new_seen)
    print("✅ AI Release Radar enviado a Telegram.")
