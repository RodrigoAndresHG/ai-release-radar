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

# Fuentes editoriales: cubren lanzamientos virales y cobertura curada
# que no aparece en RSS oficiales.
EDITORIAL_RSS_SOURCES = [
    # TechCrunch tag IA: cobertura editorial diaria.
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    # The Verge AI: cobertura editorial de producto.
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    # MIT Technology Review IA.
    "https://www.technologyreview.com/topic/artificial-intelligence/feed",
]

# Hacker News (Algolia): captura lanzamientos comentados el mismo dia.
HN_KEYWORDS = [
    "OpenAI",
    "Anthropic",
    "Claude",
    "Gemini",
    "DeepMind",
    "GPT",
    "Sora",
]
HN_MIN_POINTS = 80  # filtro minimo de relevancia comunitaria

HISTORY_FILE = f"history_{RADAR_MODE}.json"
SELECTED_RELEASE_FILE = "selected_release.json"
INSTAGRAM_IMAGE_PATH = os.path.join("output", "instagram_release.png")
BACKGROUND_IMAGE_PATH = os.path.join("output", "background.png")
BRAND_AVATAR_PATH = os.path.join("assets", "brand", "rodrigo.png")
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


def fetch_hacker_news(keywords, min_points=HN_MIN_POINTS, hours=RECENT_HOURS):
    """
    Pesca posts comentados de HN via Algolia (gratis, sin auth).
    Filtra por puntos minimos para evitar ruido y por ventana de recencia.
    """
    items = []
    seen_urls = set()
    cutoff_ts = int(time.time()) - hours * 3600

    for keyword in keywords:
        params = {
            "query": keyword,
            "tags": "story",
            "numericFilters": f"points>={min_points},created_at_i>{cutoff_ts}",
            "hitsPerPage": 20,
        }
        try:
            response = requests.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"HN fetch fallo para '{keyword}': {exc}")
            continue

        for hit in payload.get("hits", []):
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = (hit.get("title") or "").strip()
            if not title:
                continue

            domain = urlparse(url).netloc
            items.append(
                {
                    "title": title,
                    "link": url,
                    "summary": f"Hacker News: {hit.get('points', 0)} puntos, {hit.get('num_comments', 0)} comentarios.",
                    "source": "hn_algolia",
                    "domain": domain,
                    "published_ts": hit.get("created_at_i"),
                }
            )

    return items


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
    elif source_kind == "editorial_rss":
        score += 8  # TechCrunch/Verge/MIT TR: cobertura editorial curada
    elif source_kind == "hacker_news":
        score += 5  # senal de atencion comunitaria, no curacion editorial
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

    def _add(article, source_kind):
        if not article.get("link") or article["link"] in new_seen:
            return
        if not is_recent(article.get("published_ts")):
            return
        tier = "confirmed" if article.get("domain") in OFFICIAL_DOMAINS else "trend"
        articles.append({**article, "tier": tier, "source_kind": source_kind})
        new_seen.add(article["link"])

    # 1) Fuentes oficiales primero
    for url in OFFICIAL_SOURCES:
        for article in parse_feed(url, limit=15):
            _add(article, "official_rss")

    # 2) Fuentes editoriales (TechCrunch, Verge, MIT TR): captura lanzamientos
    #    cubiertos editorialmente que no aparecen en changelogs oficiales.
    for url in EDITORIAL_RSS_SOURCES:
        for article in parse_feed(url, limit=15):
            _add(article, "editorial_rss")

    # 3) Hacker News: captura lanzamientos virales el mismo dia.
    for article in fetch_hacker_news(HN_KEYWORDS):
        _add(article, "hacker_news")

    # 4) Fallback Google News si no hay nada o nada llega al umbral.
    qualifying = [release_score(a) for a in articles]
    if not qualifying or max(qualifying) < MIN_RELEASE_SCORE:
        for keyword in KEYWORDS:
            url = google_news_rss(keyword)
            for article in parse_feed(url, limit=10):
                _add(article, "google_news_rss")

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
    # Selecciona releases reales sobre ruido editorial y diversifica proveedor/producto.
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


# -----------------------------
# Capa editorial LLM
# -----------------------------
EDITORIAL_MODEL = "gpt-5-mini"


def _editorial_prompt(candidates):
    candidate_lines = []
    for cand in candidates:
        candidate_lines.append(json.dumps(cand, ensure_ascii=False))
    candidates_block = "\n".join(candidate_lines)

    return f"""
Actuas como editor jefe de un canal de IA en espanol para LATAM.
Audiencia: rectores, gerentes, emprendedores, builders y creators NO tecnicos.
Tu trabajo es decidir cual lanzamiento merece publicacion hoy y como contarlo.

Recibes una lista de candidatos detectados por un radar de releases.
Para CADA candidato, devuelves un objeto con:

- id: el mismo id que recibiste.
- editorial_score: 0-100. Criterio:
    80-100 = lanzamiento real, novedad clara, accionable o con impacto inmediato para no tecnicos.
    50-79  = cambio relevante pero incremental.
    0-49   = cosmetico, niche, sin angulo claro.
- headline_es: titular humano en espanol natural, 8-14 palabras.
    No Spanglish. No traduccion literal. No numeros de version.
    No frases tipo "actualiza con cambios importantes".
    Suena como algo que un creador diria en voz alta.
- hook: una linea (max 18 palabras) que explique por que importa para alguien NO tecnico.
    No repetir el titular. Sin jerga. Concreto.
- image_title: 4-7 palabras para la imagen, en espanol, sin signos raros, sin emojis.
- image_concept: descripcion visual EN INGLES (25-55 palabras) de UNA sola
    imagen cinematografica conceptual del release. Estilo portada de revista
    editorial (TIME, Wired, The Atlantic). Especifica:
    - sujeto principal real y concreto (objeto, paisaje, escena conceptual);
    - iluminacion (cinematic dramatic, blue hour, neon noir, golden hour, etc);
    - paleta dominante (deep navy + amber, monochrome blue, etc);
    - composicion (low angle, wide shot, close-up macro, aerial, etc).
    Prohibido: robots, brains, neural nets, holograms, glowing AI orbs,
    fantasy sci-fi, screens with code, stock photo aesthetic, generic tech.
    Ejemplo: "A massive industrial transformer station at twilight, thick
    power cables glowing electric blue, low-angle wide shot, deep navy
    sky and amber rim light, photorealistic cinematic atmosphere".
- skip_reason: null si vale la pena publicar, o un string corto si NO vale la pena
    (ej. "cambio cosmetico", "rumor sin fuente", "release de nicho dev puro").
    Solo si editorial_score < 40.

Reglas duras:
- No inventes datos, fechas, benchmarks, precios ni disponibilidad.
- Si el input no lo dice, no lo digas.
- Espanol natural, no traducido del ingles.
- Elige la plantilla de diagrama que mas le conviene al release real,
    no por defecto FLOW.

Candidatos (JSON, uno por linea):
{candidates_block}

Responde SOLO con JSON valido en este shape exacto:
{{
  "ranked": [
    {{
      "id": int,
      "editorial_score": int,
      "headline_es": "string",
      "hook": "string",
      "image_title": "string",
      "image_concept": "string en ingles 25-55 palabras",
      "skip_reason": null
    }}
  ]
}}
""".strip()


def _normalize_editorial_item(item, original):
    def _str(value):
        return value.strip() if isinstance(value, str) and value.strip() else None

    score = item.get("editorial_score")
    if not isinstance(score, (int, float)):
        score = None

    return {
        **original,
        "headline_es": _str(item.get("headline_es")),
        "hook": _str(item.get("hook")),
        "image_title": _str(item.get("image_title")),
        "image_concept": _str(item.get("image_concept")),
        "editorial_score": score,
        "skip_reason": _str(item.get("skip_reason")),
    }


def editorial_enrich(releases, max_candidates=8):
    """
    Pasa el pool de releases por una capa editorial con gpt-5-mini.
    Reordena por editorial_score y agrega headline_es, hook, image_title e
    image_concept (descripcion visual cinematografica para gpt-image-1).
    Si la llamada falla o devuelve algo invalido, devuelve los releases
    originales sin tocar para que los fallbacks deterministas operen.
    """
    if not releases:
        return releases

    pool = releases[:max_candidates]
    candidates = []
    for idx, release in enumerate(pool):
        candidates.append(
            {
                "id": idx,
                "title": (release.get("title") or "").strip(),
                "summary": clean_summary_text(release.get("summary", ""))[:500],
                "link": release.get("link") or "",
                "provider": canonical_provider_name(provider_name(release)),
                "product": image_product_name(release),
                "release_score": release.get("release_score"),
                "published_ts": release.get("published_ts"),
                "tier": release.get("tier"),
            }
        )

    prompt = _editorial_prompt(candidates)

    try:
        response = client.responses.create(
            model=EDITORIAL_MODEL,
            input=prompt,
            text={"format": {"type": "json_object"}},
        )
        raw = (response.output_text or "").strip()
        if not raw:
            raise ValueError("respuesta editorial vacia")
        data = json.loads(raw)
    except Exception as exc:
        print(f"editorial_enrich fallo, uso fallbacks deterministas. Error: {exc}")
        return releases

    items = data.get("ranked") if isinstance(data, dict) else None
    if not isinstance(items, list):
        print("editorial_enrich devolvio shape invalido. Uso fallbacks.")
        return releases

    by_id = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if isinstance(item_id, int) and 0 <= item_id < len(pool):
            by_id[item_id] = item

    enriched = []
    skipped = []
    for idx, release in enumerate(pool):
        item = by_id.get(idx)
        if not item:
            enriched.append(release)
            continue

        normalized = _normalize_editorial_item(item, release)
        if normalized.get("skip_reason") and (normalized.get("editorial_score") or 0) < 40:
            skipped.append((normalized.get("editorial_score"), normalized.get("skip_reason"), release.get("title")))
            continue
        enriched.append(normalized)

    for score, reason, title in skipped:
        print(f"editorial_enrich descarto release ({score}, {reason}): {title}")

    enriched.sort(
        key=lambda r: (
            r.get("editorial_score") if r.get("editorial_score") is not None else -1,
            r.get("release_score") or 0,
            r.get("published_ts") or 0,
        ),
        reverse=True,
    )

    if not enriched:
        # Si el editor descarto TODO, no forzamos contenido flojo:
        # devolvemos lista vacia para que el caller muestre "no hay nada hoy".
        return []

    return enriched


EDITORIAL_POOL_SIZE = 8


def _selection_pool(articles):
    # Pool diversificado mas grande (limit=8) para que el editor tenga de
    # donde escoger. La capa editorial reordena y devuelve los mejores.
    return get_top_releases(limit=EDITORIAL_POOL_SIZE, articles=articles)


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
        pool = _selection_pool(articles)
        enriched = editorial_enrich(pool)
        top_releases = enriched[:3]
        save_selected_releases(top_releases)

        choice_index = int(SELECT_CHOICE) - 1 if SELECT_CHOICE else 0
        selected = top_releases[choice_index] if choice_index < len(top_releases) else None
        if SELECT_CHOICE and selected:
            print(f"SELECT_CHOICE={SELECT_CHOICE}. Usando release #{choice_index + 1}.")
        return selected, new_seen

    articles, new_seen = fetch_articles_for_selection()
    pool = _selection_pool(articles)
    enriched = editorial_enrich(pool)
    best = enriched[0] if enriched else None
    save_selected_releases(enriched[:3])
    return best, new_seen


def get_brief_releases():
    articles, new_seen = fetch_articles_for_selection()
    pool = _selection_pool(articles)
    enriched = editorial_enrich(pool)
    top_releases = enriched[:3]
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
    # Si la capa editorial LLM ya redacto el titular, lo respetamos.
    headline = (article.get("headline_es") or "").strip()
    if headline:
        if len(headline) <= max_len:
            return headline
        return headline[: max_len - 3].rstrip() + "..."

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
            "No hay lanzamientos que valga la pena publicar hoy.\n"
            "El editor descarto todo el pool por falta de angulo claro.\n"
        )

    lines = [
        "AI RELEASE RADAR TOP 3 (Rodri)",
        f"FECHA: {today}",
        "",
    ]

    for i, article in enumerate(top_releases, start=1):
        provider_label = provider_product_label(article)
        title = build_human_title(article)
        hook = (article.get("hook") or "").strip()
        editorial_score = article.get("editorial_score")
        release_score_value = article.get("release_score")

        score_bits = []
        if isinstance(editorial_score, (int, float)):
            score_bits.append(f"editorial {int(editorial_score)}")
        if isinstance(release_score_value, (int, float)):
            score_bits.append(f"tecnico {int(release_score_value)}")
        score_line = " | ".join(score_bits) if score_bits else ""

        lines.append(f"{i}. {title}")
        lines.append(f"   {provider_label}")
        if hook:
            lines.append(f"   POR QUE IMPORTA: {hook}")
        if score_line:
            lines.append(f"   SCORE: {score_line}")
        lines.append(f"   LINK: {article.get('link')}")
        lines.append("")

    top = top_releases[0]
    top_score = top.get("editorial_score")
    if isinstance(top_score, (int, float)):
        recommendation = (
            f"Publica primero el #1: el editor le dio {int(top_score)}/100 "
            "por novedad, magnitud y angulo claro para audiencia no tecnica."
        )
    else:
        recommendation = (
            "Publica primero el #1: tiene la mejor mezcla de fuente, "
            "novedad e impacto practico segun el scoring."
        )

    lines.extend(["RECOMENDACION:", recommendation])
    return "\n".join(lines)


def build_prompt(today: str, best, mode: str):
    # best es 1 solo release detectado por scoring deterministico,
    # opcionalmente enriquecido por la capa editorial (headline_es, hook).
    title = (best.get("title") or "").replace("\n", " ").strip()
    summary = (best.get("summary") or "").replace("\n", " ").strip()
    link = best.get("link") or ""
    source_kind = best.get("source_kind")
    tier = best.get("tier")
    score = best.get("release_score")
    headline_es = (best.get("headline_es") or "").strip()
    hook = (best.get("hook") or "").strip()

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

    if headline_es:
        context += f"TITULAR_EDITORIAL: {headline_es}\n"
    if hook:
        context += f"ANGULO_EDITORIAL: {hook}\n"

    editorial_lock = ""
    if headline_es:
        editorial_lock += (
            f"\nIMPORTANTE: el TITULAR_EDITORIAL '{headline_es}' es la decision editorial "
            "del dia. Tu guion DEBE girar alrededor de ese mensaje y reforzarlo. "
            "Usa TITULO y RESUMEN solo como fuente de hechos (que salio, que hace, "
            "por que importa), no como lead narrativo.\n"
        )
    if hook:
        editorial_lock += (
            f"El ANGULO_EDITORIAL '{hook}' es la promesa al lector. "
            "El guion debe entregar ese angulo de forma clara.\n"
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
{editorial_lock}
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
    # Genera solo el texto de Telegram; la imagen se compone en una capa separada.
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


def safe_image_text(text, max_chars=42, fallback="Cambio importante"):
    text = clean_summary_text(text or "")
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"\b(TODO|TBD|PLACEHOLDER|N/A|NULL)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[\\<>{}*_`~|]+", " ", text)
    text = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ .,;:()/&+\-]", " ", text)
    text = re.sub(r"\b(v?\d+(?:\.\d+){1,4})\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -:|.,")

    if not text:
        text = fallback

    if len(text) <= max_chars:
        return text

    clipped = text[:max_chars].rsplit(" ", 1)[0].strip(" -:|.,")
    if len(clipped) < max(12, max_chars // 2):
        clipped = text[:max_chars].strip(" -:|.,")
    return clipped or fallback


def canonical_provider_name(provider):
    text = (provider or "").lower()

    if "anthropic" in text or "claude" in text:
        return "Anthropic"
    if "openai" in text or "chatgpt" in text or "gpt" in text or "sora" in text:
        return "OpenAI"
    if "aws" in text or "amazon" in text:
        return "AWS"
    if "google" in text or "gemini" in text or "deepmind" in text or "vertex" in text:
        return "Google"
    return safe_image_text(provider, max_chars=24, fallback="Proveedor")


def compact_image_title(release, max_chars=60):
    title = release.get("human_title") or build_human_title(release)
    if not title:
        title = clean_summary_text(release.get("title", ""))

    fallback = f"{canonical_provider_name(provider_name(release))} actualiza IA"
    return safe_image_text(title, max_chars=max_chars, fallback=fallback)


def _trim_bad_title_ending(title):
    bad_endings = {"de", "y", "con", "para", "por", "en", "a", "el", "la", "los", "las", ","}
    words = title.strip(" -:|.,").split()
    while words and words[-1].lower().strip(",") in bad_endings:
        words = words[:-1]
    return " ".join(words).strip(" -:|.,")


def build_short_image_title(release):
    # Fallback deterministico: el titular humano del release, limpio para la imagen.
    # La capa editorial LLM puede sobreescribir esto via release["image_title"].
    override = (release.get("image_title") or "").strip()
    if override:
        return safe_image_text(override, max_chars=72, fallback=override)

    product = image_product_name(release)
    provider = canonical_provider_name(provider_name(release))
    title = compact_image_title(release, max_chars=64)
    title = _trim_bad_title_ending(title)
    fallback = f"{provider} estrena cambios en {product}" if product != provider else f"{provider} estrena cambios"
    return safe_image_text(title, max_chars=72, fallback=fallback)


def image_product_name(release):
    product = provider_product_label(release).split(" / ")[-1]
    canonical_products = {
        "API": "API",
        "OpenAI": "OpenAI",
        "ChatGPT": "ChatGPT",
        "Claude Code": "Claude Code",
        "Gemini API": "Gemini API",
        "Gemini": "Gemini",
        "Vertex AI": "Vertex AI",
        "DeepMind": "DeepMind",
    }
    return canonical_products.get(product, safe_image_text(product, max_chars=24, fallback="Producto IA"))


def get_brand_avatar_path():
    return BRAND_AVATAR_PATH if os.path.exists(BRAND_AVATAR_PATH) else None


def draw_circular_avatar(image, path, x, y, size):
    if not path or not os.path.exists(path):
        return False

    try:
        from PIL import Image, ImageDraw

        with Image.open(path) as avatar:
            avatar = avatar.convert("RGBA")
            width, height = avatar.size
            crop_size = min(width, height)
            left = (width - crop_size) // 2
            top = (height - crop_size) // 2
            avatar = avatar.crop((left, top, left + crop_size, top + crop_size))
            avatar = avatar.resize((size, size), Image.LANCZOS)

            mask = Image.new("L", (size, size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
            avatar.putalpha(mask)

            border_size = size + 8
            border = Image.new("RGBA", (border_size, border_size), (0, 0, 0, 0))
            border_draw = ImageDraw.Draw(border)
            border_draw.ellipse(
                (0, 0, border_size - 1, border_size - 1),
                fill=(120, 220, 255, 235),
            )
            border.alpha_composite(avatar, (4, 4))

            image.alpha_composite(border, (int(x - 4), int(y - 4)))
            return True
    except Exception as exc:
        print(f"No se pudo dibujar avatar de marca {path}. Error: {exc}")
        return False


def build_image_prompt(release, content_text):
    # gpt-image-1 genera la imagen conceptual editorial de portada.
    # El concepto especifico al release viene de la capa editorial LLM.
    concept = (release.get("image_concept") or "").strip()
    if not concept:
        concept = (
            "A cinematic wide shot of soft glowing connection lines flowing "
            "through a deep navy space, dramatic single light source, premium "
            "editorial atmosphere, photorealistic"
        )

    return f"""
Create a 1080x1080 square cinematic editorial cover image.
Style: premium magazine cover (TIME, Wired, The Atlantic). NOT infographic, NOT tech ad.

SUBJECT (mandatory, follow exactly):
{concept}

Composition rules:
- One clear hero subject. No collage, no split panels, no multi-subject layouts.
- Strong cinematic lighting with a single dominant light source.
- High contrast, dramatic atmosphere, deep shadows.
- Lower 40% of the frame should be visually quieter / darker so overlaid
    text remains readable. The hero subject sits in the upper-middle area.
- Photorealistic OR painterly conceptual, NEVER cartoon or 3D render.

Strict prohibitions:
- No text, letters, words, numbers, captions, watermarks anywhere.
- No logos, icons, brand marks, UI labels, dashboards, screenshots.
- No diagrams, arrows, flow lines, charts, schematics, wireframes.
- No rectangles, cards, panels, frames, boxes, glass UI overlays.
- No robots, humanoid AI, brains, neural nets, holograms, glowing AI orbs.
- No fantasy sci-fi tropes, no spaceships, no aliens.
- No stock photo aesthetic, no clipart, no generic tech.
- No people's faces unless the concept explicitly demands them.

The output must be a single cohesive cinematic image with a clear emotional
mood, not a generic background.
""".strip()


def load_font(size, bold=False):
    from PIL import ImageFont

    font_paths = (
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )

    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size=size)
            except OSError:
                continue

    return ImageFont.load_default()


def _text_width(text, font):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_text(text, font, max_width, max_lines, add_ellipsis=True):
    words = safe_image_text(text, max_chars=120).split()
    lines = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if _text_width(candidate, font) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if lines and _text_width(lines[-1], font) > max_width:
        while lines[-1] and _text_width(lines[-1] + "...", font) > max_width:
            lines[-1] = lines[-1][:-1].rstrip()
        if add_ellipsis:
            lines[-1] = (lines[-1] + "...").strip()

    # Solo recortamos preposiciones colgantes en la ultima linea.
    # En lineas intermedias, "para" / "de" / "con" deben quedarse para no
    # romper la gramatica, p.ej. "Disponible para\nequipos".
    if lines:
        lines[-1] = _trim_bad_title_ending(lines[-1])
    lines = [line for line in lines if line]
    return lines or ["Cambio importante"]


def fit_wrapped_title(text, max_width, max_lines=2, start_size=60, min_size=42):
    title = build_short_text_title(text)

    for size in range(start_size, min_size - 1, -2):
        font = load_font(size, bold=True)
        lines = wrap_text(title, font, max_width, max_lines, add_ellipsis=False)
        if len(lines) <= max_lines and all(_text_width(line, font) <= max_width for line in lines):
            return font, lines

    fallback = _trim_bad_title_ending(safe_image_text(title, max_chars=42, fallback="Cambio importante"))
    font = load_font(min_size, bold=True)
    return font, wrap_text(fallback, font, max_width, max_lines, add_ellipsis=False)


def build_short_text_title(text):
    title = safe_image_text(text, max_chars=60, fallback="Cambio importante")
    title = _trim_bad_title_ending(title)
    if len(title) <= 48:
        return title
    title = safe_image_text(title, max_chars=48, fallback="Cambio importante")
    return _trim_bad_title_ending(title)


def create_fallback_background(output_path=BACKGROUND_IMAGE_PATH):
    # Fallback editorial cuando gpt-image-1 falla: gradiente cinematografico
    # vertical sin diagramas, sin grid, sin lineas. Listo para titular grande.
    from PIL import Image, ImageDraw, ImageFilter

    width = height = 1080
    image = Image.new("RGB", (width, height), "#04060a")
    pixels = image.load()

    for y in range(height):
        # Gradiente vertical: cobre/ambar arriba a la izquierda -> azul profundo abajo.
        ty = y / height
        r = int(28 * (1 - ty) ** 2)
        g = int(20 + 8 * (1 - ty) ** 2)
        b = int(36 + 18 * ty)
        for x in range(width):
            tx = x / width
            # Vineta horizontal sutil para foco editorial.
            edge = abs(tx - 0.5) * 2
            edge_factor = 1 - 0.35 * (edge ** 2)
            pixels[x, y] = (
                max(0, int(r * edge_factor)),
                max(0, int(g * edge_factor)),
                max(0, int(b * edge_factor)),
            )

    # Highlight calido arriba a la izquierda, simulando luz cinematografica.
    highlight = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(highlight)
    for radius, alpha in [(420, 90), (260, 120), (140, 150)]:
        hl_draw.ellipse(
            (180 - radius, 120 - radius, 180 + radius, 120 + radius),
            fill=(220, 150, 90, alpha),
        )
    highlight = highlight.filter(ImageFilter.GaussianBlur(radius=80))
    image = image.convert("RGBA")
    image.alpha_composite(highlight)

    # Sombra inferior progresiva (refuerza la zona del titular).
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(shadow)
    for y in range(int(height * 0.5), height):
        t = (y - height * 0.5) / (height * 0.5)
        sh_draw.line([(0, y), (width, y)], fill=(0, 0, 0, int(160 * t)))
    image.alpha_composite(shadow)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    image.convert("RGB").save(output_path, "PNG")
    return output_path


def generate_background_image(prompt):
    # Si falla la imagen de OpenAI, se mantiene el flujo con un fondo fallback local.
    output_dir = "output"
    output_path = BACKGROUND_IMAGE_PATH
    os.makedirs(output_dir, exist_ok=True)

    try:
        result = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            quality="high",
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

        temp_path = os.path.join(output_dir, "background_raw.png")
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
    except Exception as exc:
        print(f"No se pudo generar fondo con OpenAI Images. Usando fallback. Error: {exc}")
        return create_fallback_background(output_path)


def _draw_bottom_gradient(image):
    # Oscurece progresivamente la mitad inferior para que el titular grande
    # quede legible sobre cualquier imagen cinematografica.
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    width, height = image.size
    start_y = int(height * 0.42)
    for y in range(start_y, height):
        t = (y - start_y) / max(1, height - start_y)
        alpha = int(min(235, 255 * (t ** 1.6)))
        overlay_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(image, overlay)


def _draw_brand_mark(image, draw):
    # Marca personal compacta, esquina superior derecha, estilo editorial.
    margin = 64
    avatar_size = 56
    brand_font = load_font(22, bold=True)
    text = "Rodrigo Hered IA"
    bbox = draw.textbbox((0, 0), text, font=brand_font)
    text_width = bbox[2] - bbox[0]

    avatar_path = get_brand_avatar_path()
    if avatar_path:
        avatar_x = 1080 - margin - avatar_size
        avatar_y = margin
        draw_circular_avatar(image, avatar_path, avatar_x, avatar_y, avatar_size)
        text_x = 1080 - margin - text_width
        text_y = avatar_y + avatar_size + 12
    else:
        text_x = 1080 - margin - text_width
        text_y = margin

    # Sombra suave para legibilidad sobre fondos brillantes.
    draw.text((text_x + 1, text_y + 2), text, font=brand_font, fill=(0, 0, 0, 160))
    draw.text((text_x, text_y), text, font=brand_font, fill=(255, 255, 255, 240))


def _draw_kicker(draw, today):
    # Kicker editorial: linea pequena sobre el titular, tipo seccion de revista.
    margin = 64
    kicker_font = load_font(20, bold=True)
    kicker = f"AI RELEASE RADAR · {today}"
    # Sombra ligera.
    draw.text((margin + 1, 990 + 1), kicker, font=kicker_font, fill=(0, 0, 0, 140))
    draw.text((margin, 990), kicker, font=kicker_font, fill=(0, 220, 255, 240))


def _draw_magazine_headline(draw, headline):
    # Titular gigante, alineado a la izquierda, ocupando la zona inferior.
    margin = 64
    max_width = 1080 - 2 * margin
    title_font, title_lines = fit_wrapped_title(
        headline, max_width, max_lines=3, start_size=128, min_size=72
    )

    line_metrics = []
    total_height = 0
    line_gap = 12
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_height = bbox[3] - bbox[1]
        line_metrics.append((line, line_height))
        total_height += line_height + line_gap
    total_height -= line_gap

    bottom_margin = 96
    # El kicker ocupa una linea ~32px sobre el headline; lo dejamos a y=990.
    # El headline sube desde y = 1080 - bottom_margin hacia arriba.
    title_y = 1080 - bottom_margin - total_height

    for line, line_height in line_metrics:
        # Doble sombra: una desplazada para profundidad, otra base para contorno.
        draw.text((margin + 3, title_y + 4), line, font=title_font, fill=(0, 0, 0, 180))
        draw.text((margin, title_y), line, font=title_font, fill=(255, 255, 255, 252))
        title_y += line_height + line_gap


def compose_instagram_image(background_path, release, content_text):
    # Layout magazine cover: imagen full-bleed + gradient inferior + titular gigante
    # alineado a la izquierda + marca personal en esquina superior derecha.
    from PIL import Image, ImageDraw

    output_path = INSTAGRAM_IMAGE_PATH
    headline = build_short_image_title(release)
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        background = Image.open(background_path).convert("RGB").resize((1080, 1080), Image.LANCZOS)
    except Exception:
        create_fallback_background(background_path)
        background = Image.open(background_path).convert("RGB").resize((1080, 1080), Image.LANCZOS)

    image = background.convert("RGBA")
    image = _draw_bottom_gradient(image)
    draw = ImageDraw.Draw(image, "RGBA")

    _draw_brand_mark(image, draw)
    _draw_kicker(draw, today)
    _draw_magazine_headline(draw, headline)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    image.convert("RGB").save(output_path, "PNG")
    return output_path


def generate_instagram_image(prompt, release=None, content_text=""):
    background_path = generate_background_image(prompt)
    if release is None:
        return background_path
    return compose_instagram_image(background_path, release, content_text)


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
        image_path = generate_instagram_image(image_prompt, release=release, content_text=content_text)
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
    # Envio principal por Telegram; parte el mensaje si supera el limite practico.
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
    # Envia la imagen final compuesta por Pillow, no el fondo generado por IA.
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
