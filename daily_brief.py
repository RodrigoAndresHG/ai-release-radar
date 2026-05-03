import os
import json
import re
import base64
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
SELECT_CHOICE = os.getenv("SELECT_CHOICE", "").strip()
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

if not OPENAI_API_KEY:
    raise ValueError("Falta OPENAI_API_KEY en .env")
if not TELEGRAM_TOKEN:
    raise ValueError("Falta TELEGRAM_BOT_TOKEN en .env")
if not CHAT_ID:
    raise ValueError("Falta TELEGRAM_CHAT_ID en .env")
if RADAR_MODE not in {"brief", "content"}:
    raise ValueError("RADAR_MODE debe ser 'brief' o 'content'")
if SELECT_CHOICE and SELECT_CHOICE not in {"1", "2", "3"}:
    raise ValueError("SELECT_CHOICE debe ser 1, 2 o 3")

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
INSTAGRAM_IMAGE_PATH = os.path.join("output", "instagram_release.png")
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

    releases = data.get("releases") or []
    if not releases and data.get("release"):
        releases = [data.get("release")]

    choice_index = int(SELECT_CHOICE) - 1 if SELECT_CHOICE else 0
    if choice_index >= len(releases):
        return False, None

    selected = releases[choice_index]
    if SELECT_CHOICE:
        print(f"SELECT_CHOICE={SELECT_CHOICE}. Usando release #{choice_index + 1}.")

    return True, selected


def with_human_title(release):
    if release:
        return {**release, "human_title": build_human_title(release)}
    return None


def save_selected_release(release):
    release = with_human_title(release)
    payload = {
        "selected_date_utc": selection_date(),
        "release": release,
        "releases": [release] if release else [],
    }
    with open(SELECTED_RELEASE_FILE, "w") as f:
        json.dump(payload, f, indent=2)


def save_selected_releases(releases):
    releases = [with_human_title(release) for release in releases]
    releases = [release for release in releases if release]
    payload = {
        "selected_date_utc": selection_date(),
        "release": releases[0] if releases else None,
        "releases": releases,
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
    Si content corre manualmente sin cache, reconstruye el Top 3 y continua.
    """
    if RADAR_MODE == "content":
        found, selected = load_selected_release()
        if found:
            print("Reutilizando release seleccionado desde selected_release.json.")
            return selected, load_history()

        print("No hay selected_release.json valido. Reconstruyendo Top 3 para content.")
        articles, new_seen = fetch_articles_for_selection()
        top_releases = get_top_releases(limit=3, articles=articles)
        save_selected_releases(top_releases)

        choice_index = int(SELECT_CHOICE) - 1 if SELECT_CHOICE else 0
        selected = top_releases[choice_index] if choice_index < len(top_releases) else None
        if SELECT_CHOICE and selected:
            print(f"SELECT_CHOICE={SELECT_CHOICE}. Usando release #{choice_index + 1}.")
        return selected, new_seen

    articles, new_seen = fetch_articles_for_selection()
    top_releases = get_top_releases(limit=1, articles=articles)
    best = top_releases[0] if top_releases else None
    save_selected_releases(top_releases)
    return best, new_seen


def get_brief_releases():
    articles, new_seen = fetch_articles_for_selection()
    top_releases = get_top_releases(limit=3, articles=articles)
    save_selected_releases(top_releases)
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


def looks_like_date_title(title):
    cleaned = title.strip()
    return bool(
        re.match(
            r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}$",
            cleaned,
            flags=re.IGNORECASE,
        )
    )


def starts_with_raw_technical_text(title):
    cleaned = title.strip()
    technical_prefixes = ("/", "endpoint", "api endpoint", "the /")
    lowered = cleaned.lower()
    return lowered.startswith(technical_prefixes) or "/" in lowered[:35]


def clean_summary_text(summary):
    text = re.sub(r"<[^>]+>", " ", summary or "")
    text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
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


def title_is_descriptive(title):
    if not title:
        return False
    if looks_like_version_title(title) or looks_like_date_title(title):
        return False
    if starts_with_raw_technical_text(title):
        return False
    return len(title.split()) >= 3


def build_human_title(article, max_len=100):
    link = article.get("link") or ""
    title = (article.get("title") or "").replace("\n", " ").strip()
    summary = clean_summary_text(article.get("summary", ""))
    raw_text = f"{title} {summary} {link}".lower()
    provider = provider_name(article)
    product = provider_product_label(article).split(" / ")[-1]

    if product_key(article) == "claude_code" and "#2-1-126" in link:
        return "Claude Code mejora login remoto, limpieza de proyectos y seleccion de modelos"
    if "come to aws" in raw_text or "comes to aws" in raw_text or "to aws" in raw_text:
        return "OpenAI lleva sus modelos y agentes a AWS"
    if "deprecated" in raw_text:
        return "Gemini elimina funciones antiguas de video y obliga a actualizar integraciones"
    if "release notes" in raw_text:
        return "Gemini actualiza capacidades en Vertex AI"
    if provider == "OpenAI" and ("endpoint" in raw_text or "available" in raw_text or "availability" in raw_text):
        return "OpenAI actualiza modelos disponibles para desarrolladores"

    english_markers = [
        "deprecated",
        "release",
        "endpoint",
        "preview",
        "available",
        "update",
        "updates",
        "adds",
        "improves",
        "fixes",
        "generally available",
    ]
    has_english_marker = any(marker in raw_text for marker in english_markers)

    if title_is_descriptive(title) and not has_english_marker:
        final_title = title
    else:
        summary = human_summary_fragment(summary)
        if summary:
            prefix = "" if summary.lower().startswith(product.lower()) else f"{product} "
            final_title = f"{prefix}{summary}"
        else:
            final_title = f"{provider} actualiza {product} con cambios importantes"

    noise_patterns = [
        r"\bdeprecated\b",
        r"\bpreview\b",
        r"\bendpoints?\b",
        r"\btable describes\b",
        r"\bfollowing\b",
        r"\brelease notes\b",
        r"\bversion\s*\d+(?:\.\d+)*\b",
        r"\bv?\d+(?:\.\d+){1,3}\b",
    ]
    for pattern in noise_patterns:
        final_title = re.sub(pattern, " ", final_title, flags=re.IGNORECASE)

    replacements = {
        "Video generation": "funciones de video",
        "video generation": "funciones de video",
        "available": "disponible",
        "Available": "disponible",
        "generally disponible": "disponible de forma general",
        "updates": "actualiza",
        "Updates": "actualiza",
        "update": "actualiza",
        "Update": "actualiza",
        "adds": "agrega",
        "Adds": "agrega",
        "improves": "mejora",
        "Improves": "mejora",
        "fixes": "corrige",
        "Fixes": "corrige",
        "models": "modelos",
        "model": "modelo",
        "managed agents": "agentes administrados",
        "capabilities": "capacidades",
        "availability": "disponibilidad",
        "improvements": "mejoras",
        "customers": "usuarios",
        "developers": "desarrolladores",
        "for ": "para ",
        " and ": " y ",
    }
    for old, new in replacements.items():
        final_title = final_title.replace(old, new)

    final_title = re.sub(r"\s+", " ", final_title)
    final_title = re.sub(r"^\W+", "", final_title).strip().rstrip(".")
    if not title_is_descriptive(final_title):
        final_title = f"{provider} actualiza {product} con cambios importantes"

    if len(final_title) <= max_len:
        return final_title
    return final_title[: max_len - 3].rstrip() + "..."


def human_title(article, max_len=110):
    return build_human_title(article, max_len=max_len)


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
                f"   TITULAR: {build_human_title(article)}",
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


def compact_image_title(release, max_chars=60):
    title = release.get("human_title") or build_human_title(release)
    if not title:
        title = clean_summary_text(release.get("title", ""))

    title = re.sub(r"\s+", " ", title).strip().rstrip(".")
    title = re.sub(r"\b(v?\d+(?:\.\d+){1,3})\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" -:|")

    if not title:
        title = f"{provider_name(release)} actualiza {product_key(release)}"

    if len(title) <= max_chars:
        return title
    return title[: max_chars - 3].rstrip() + "..."


def image_template(release):
    text = f"{release.get('title', '')} {release.get('summary', '')} {release.get('link', '')}".lower()

    if _matches_any(text, ["deprecated", "deprecation", "pricing", "availability", "available", "lower latency"]):
        return "BEFORE_AFTER"
    if _matches_any(text, ["api", "sdk", "agents", "agent", "tools", "function calling", "vertex ai"]):
        return "ARCHITECTURE"
    return "FLOW"


def image_template_instruction(template):
    instructions = {
        "FLOW": (
            "Use the FLOW template only: three clean blocks in one horizontal sequence, "
            "A -> B -> C, with arrows between blocks."
        ),
        "BEFORE_AFTER": (
            "Use the BEFORE_AFTER template only: two clean columns labeled exactly "
            "ANTES and DESPUES, with [X] -> [Y] as the central comparison."
        ),
        "ARCHITECTURE": (
            "Use the ARCHITECTURE template only: a vertical Top -> Middle -> Bottom "
            "system structure with 3-5 connected blocks."
        ),
    }
    return instructions.get(template, instructions["FLOW"])


def build_image_prompt(release, content_text):
    title = compact_image_title(release)
    provider_product = provider_product_label(release)
    template = image_template(release)
    template_instruction = image_template_instruction(template)
    summary = clean_summary_text(release.get("summary", ""))[:500]

    return f"""
Create a 1080x1080 Instagram image with a fixed premium visual identity for "Rodrigo Hered IA".
Make it look like a real system explanation created by a CTO, not a generic AI poster.

STEP 1 - SELECTED TEMPLATE:
- Use exactly one visual template: {template}.
- Template meaning:
  FLOW = how something works.
  BEFORE_AFTER = change or comparison.
  ARCHITECTURE = system view.

STEP 2 - STRICT 1080x1080 LAYOUT:
TOP 20%:
- Strong title, clean and bold.
- Use this exact title, max 60 characters:
"{title}"

CENTER 60%:
- Diagram based on the selected template.
- {template_instruction}
- The diagram must communicate what changed, why it matters, and how it works as a system or process.
- Include a small provider/product label: "{provider_product}".
- Max 3-5 diagram elements.

BOTTOM 20%:
- Use this exact bottom text:
"Rodrigo Hered IA"
- DO NOT MODIFY THIS TEXT.
- Keep it subtle, clean, consistent, and premium.

STEP 3 - VISUAL STYLE:
- Dark background.
- Minimal UI.
- Clean spacing.
- Subtle glow lines.
- Grid alignment feel.
- High contrast typography.
- Mobile readable.
- Max 3-5 elements.

STEP 4 - FORBIDDEN:
- No robots.
- No brains.
- No generic AI glowing art.
- No stock images.
- No fantasy visuals.
- No clutter.
- No long paragraphs.
- No excessive text.
- No tiny unreadable labels.

STEP 5 - SYSTEM FEEL:
- Make it look like a real system explanation created by a CTO, not a generic AI poster.

STEP 6 - CONSISTENCY:
- All images must look like the same brand.
- Same spacing.
- Same hierarchy.
- Same visual logic.
- Professional, CIO-level, educational, high authority.

Context for tone only:
Release summary: {summary}
Generated content: {content_text[:900]}
""".strip()


def generate_instagram_image(prompt):
    output_dir = "output"
    output_path = INSTAGRAM_IMAGE_PATH
    os.makedirs(output_dir, exist_ok=True)

    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        quality="medium",
    )

    image_data = result.data[0]
    if getattr(image_data, "b64_json", None):
        raw_image = base64.b64decode(image_data.b64_json)
    elif getattr(image_data, "url", None):
        response = requests.get(image_data.url, timeout=60)
        response.raise_for_status()
        raw_image = response.content
    else:
        raise ValueError("La respuesta de OpenAI Images no incluyó b64_json ni url")

    temp_path = os.path.join(output_dir, "instagram_release_raw.png")
    with open(temp_path, "wb") as f:
        f.write(raw_image)

    from PIL import Image

    with Image.open(temp_path) as image:
        image = image.convert("RGB").resize((1080, 1080), Image.LANCZOS)
        image.save(output_path, "PNG")

    try:
        os.remove(temp_path)
    except OSError:
        pass

    return output_path


def upload_to_google_drive(file_path):
    # TODO: Implementar subida cuando estén definidas las credenciales y el flujo OAuth/Service Account.
    # Esperado: usar GOOGLE_DRIVE_FOLDER_ID y GOOGLE_SERVICE_ACCOUNT_JSON para subir file_path
    # y devolver una URL compartible.
    if not GOOGLE_DRIVE_FOLDER_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    return None


def generate_content_image_status(release, content_text):
    try:
        image_prompt = build_image_prompt(release, content_text)
        image_path = generate_instagram_image(image_prompt)
        drive_url = upload_to_google_drive(image_path)
        if drive_url:
            return f"\n\nIMAGEN INSTAGRAM:\n{drive_url}"
        return (
            "\n\nIMAGEN INSTAGRAM:\n"
            f"Generada localmente en {image_path}. Google Drive aun no esta configurado."
        )
    except Exception as exc:
        return f"\n\nIMAGEN INSTAGRAM:\nNo se pudo generar la imagen esta vez. Error: {exc}"


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


def send_telegram_photo(file_path, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(file_path, "rb") as image_file:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "caption": caption or "",
            },
            files={"photo": image_file},
            timeout=60,
        )
    response.raise_for_status()


# -----------------------------
# Ejecución principal
# -----------------------------
if __name__ == "__main__":
    image_ready = False

    if RADAR_MODE == "brief":
        top_releases, new_seen = get_brief_releases()
        msg = build_brief_top3(top_releases)
    else:
        best, new_seen = get_top_release()
        msg = generate_signal(best)
        if best:
            try:
                os.remove(INSTAGRAM_IMAGE_PATH)
            except OSError:
                pass
            msg += generate_content_image_status(best, msg)
            image_ready = os.path.exists(INSTAGRAM_IMAGE_PATH)

    send_to_telegram(msg)
    if RADAR_MODE == "content" and image_ready:
        try:
            send_telegram_photo(
                INSTAGRAM_IMAGE_PATH,
                caption="Imagen lista para Instagram - Rodri HeredIA",
            )
        except Exception as exc:
            try:
                send_to_telegram(f"No se pudo enviar la imagen por Telegram. Error: {exc}")
            except Exception:
                print(f"No se pudo enviar la imagen por Telegram. Error: {exc}")

    save_history(new_seen)
    print("✅ AI Release Radar enviado a Telegram.")
