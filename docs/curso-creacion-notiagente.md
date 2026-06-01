# Curso: Lanza tu propio agente de noticias de IA en menos de 1 hora

> Para personas no técnicas. La app ya existe y funciona. Vos la copiás a tu
> cuenta, la personalizás con tu marca, y la conectás a tu Telegram. Cero
> programación, todo copy-paste.

**Tiempo total del video:** ~55 min.
**Lo que vas a tener al final:** un agente que cada mañana te manda a
Telegram las noticias de IA más relevantes y un guion listo para grabar,
con tu marca, tu tono y tu paleta visual.

---

## 🎯 Antes de empezar

Esto NO es un curso de programación. Es un curso de **operación**: vas a
copiar una app que ya está hecha, decirle quién sos, conectarle tus claves y
dejarla corriendo. Cuando termines, no vas a haber escrito código. Vas a
haber **lanzado un producto**.

Lo que necesitás encima del escritorio:
- Una computadora con navegador (Chrome o Safari, da igual).
- Tu teléfono con Telegram instalado.
- Tarjeta de crédito o débito (solo para cargar saldo en OpenAI, ~5 USD).
- 55 minutos sin distracciones.

---

## 🎬 Esquema del video

| Bloque | Qué hacés | Tiempo |
|---|---|---|
| 1 | Crear las 5 cuentas | 10 min |
| 2 | Copiar la app a tu GitHub | 4 min |
| 3 | Personalizar con prompts (marca, audiencia, tono) | 12 min |
| 4 | Conectar el Bot de Telegram | 7 min |
| 5 | Subir tus claves a GitHub | 4 min |
| 6 | Desplegar el Cloudflare Worker | 12 min |
| 7 | Primer disparo y verificación en Telegram | 4 min |
| 8 | Cierre y costos reales | 2 min |

---

## Bloque 1 — Crear las cuentas (10 min)

Vas a abrir 5 pestañas, una para cada cuenta. Hacelo en este orden.

### 1.1 GitHub (donde va a vivir tu app)

1. Abrí <https://github.com/signup>.
2. Email, contraseña, nombre de usuario. Anotá tu **nombre de usuario** porque
   lo vas a usar.
3. Confirmá tu email.

**Verificación:** entrá a `https://github.com/<tu-usuario>` y debe cargarte
tu perfil.

### 1.2 OpenAI API (el cerebro de la app)

1. Entrá a <https://platform.openai.com/signup>. Si ya tenés cuenta de ChatGPT,
   usá esa misma.
2. Una vez adentro, andá a <https://platform.openai.com/api-keys>.
3. Click en **Create new secret key**, ponele nombre `notiagente` y copiala.
4. Pegala en un Bloc de Notas temporal. Si la perdés, hay que crear otra.
5. Andá a <https://platform.openai.com/account/billing> y cargá **5 USD**.
   Te van a durar más de un mes.

**Verificación:** la página de API keys debe mostrar tu key recién creada.

### 1.3 Telegram + Bot (la cara de tu app)

1. Abrí Telegram en tu teléfono.
2. Buscá **@BotFather** (oficial, con tilde azul) y abrí el chat.
3. Escribí `/newbot`.
4. Ponele un nombre, por ejemplo `Mi NotiAgente`.
5. Ponele un username que termine en `bot`, por ejemplo `mi_notiagente_bot`.
6. BotFather te va a dar un **token**. Copialo. Se ve así:
   `1234567890:ABCdef...`. Pegalo en tu Bloc de Notas.
7. Abrí el chat con tu nuevo bot y mandale cualquier mensaje (`hola` está
   bien). Esto es importante.
8. En el navegador, andá a esta URL reemplazando `<TOKEN>` por el tuyo:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
9. Vas a ver un JSON. Buscá el número de `"chat":{"id":XXXX`. Ese número es
   tu **Chat ID**. Copialo al Bloc de Notas.

**Verificación:** tenés dos cosas anotadas: el **Bot Token** y el **Chat ID**.

### 1.4 Cloudflare (para que el Bot pueda dispararte contenido)

1. Abrí <https://dash.cloudflare.com/sign-up>.
2. Email, contraseña, verificación.
3. Saltate cualquier paso de "agregar dominio". No necesitás dominio.

**Verificación:** estás dentro del dashboard de Cloudflare.

### 1.5 Claude (para personalizar la app con prompts)

1. Abrí <https://claude.ai/login>. Usá Google o email.
2. Plan gratis está perfecto.

**Verificación:** podés abrir una conversación con Claude.

---

## Bloque 2 — Copiar la app a tu GitHub (4 min)

### 2.1 Forkear el repo original

1. Abrí <https://github.com/RodrigoAndresHG/ai-release-radar>.
2. Click en **Fork** (esquina superior derecha).
3. Asegurate que el dueño sea tu usuario.
4. Cambiá el nombre si querés, por ejemplo `mi-notiagente`.
5. **Importante:** desmarcá "Copy the main branch only" (queremos todas las
   ramas).
6. Click **Create fork**.

**Verificación:** en menos de 10 segundos estás en
`https://github.com/<tu-usuario>/mi-notiagente`.

### 2.2 Abrir el editor de GitHub en el navegador

GitHub tiene un editor web. **No necesitás instalar nada.**

1. Estando en tu repo, presioná la tecla `.` (punto).
2. Se abre VS Code dentro del navegador, ya conectado a tu repo.

**Verificación:** ves la lista de archivos del proyecto a la izquierda.

> Si preferís editar archivo por archivo, también podés hacer click en cada
> archivo en GitHub y usar el lápiz para editar. Las dos formas funcionan.

---

## Bloque 3 — Personalizar con prompts (12 min)

Acá usás Claude.ai para que te genere los cambios exactos que tenés que
copiar y pegar en `daily_brief.py`. **Vos no vas a programar, le vas a pedir
a Claude que te diga qué pegar dónde.**

Para cada cambio, hacés esto:

1. Abrí una conversación nueva en <https://claude.ai>.
2. Copiá el prompt de abajo y pegalo en Claude.
3. Claude te devuelve un bloque de texto con la línea exacta a reemplazar.
4. Vas al editor web de GitHub, abrís `daily_brief.py`, usás `Ctrl+F` para
   encontrar la línea, la reemplazás y guardás.

### 3.1 Cambiar el nombre de tu app y tu marca personal

**Prompt para Claude:**

```
Tengo un archivo Python llamado daily_brief.py con estas dos constantes:

APP_NAME = "NotiAgente Hered-IA"
PERSONAL_BRAND = "Rodrigo Hered IA"

Quiero cambiarlas a:

APP_NAME = "<PONE ACA EL NOMBRE DE TU AGENTE, EJEMPLO: NotiTech Lucia AI>"
PERSONAL_BRAND = "<PONE ACA TU NOMBRE PUBLICO, EJEMPLO: Lucia Martinez>"

Devolveme las dos lineas finales listas para pegar. No expliques nada mas.
```

**Qué hacer con la respuesta:**
1. En el editor de GitHub, `Ctrl+F` (o `Cmd+F` en Mac).
2. Buscá `APP_NAME = "NotiAgente Hered-IA"`.
3. Reemplazala por la línea que te dio Claude.
4. Lo mismo con `PERSONAL_BRAND`.
5. Click en el ícono de **Source Control** (arriba a la izquierda, el de las
   ramas), escribí "Cambio marca" como mensaje y **Commit**.

### 3.2 Cambiar la audiencia objetivo del editor

La app por defecto escribe para "rectores, gerentes, emprendedores y builders
no técnicos en LATAM". Si tu audiencia es otra, cambialo.

**Prompt para Claude:**

```
En daily_brief.py hay una funcion llamada _editorial_prompt. Adentro tiene
esta linea:

Audiencia: rectores, gerentes, emprendedores, builders y creators NO tecnicos.

Quiero cambiar la audiencia a:

<DESCRIBE TU AUDIENCIA EN UNA LINEA. EJEMPLOS:
- "abogados y profesionales legales en Latinoamerica"
- "duenos de pymes de retail en Mexico"
- "estudiantes universitarios de ingenieria">

Dame la linea final lista para pegar, conservando exactamente el formato
(empieza con "Audiencia:"). No agregues nada mas.
```

**Qué hacer con la respuesta:**
1. `Ctrl+F` busca `Audiencia: rectores`.
2. Reemplazá esa línea completa por la que te dio Claude.
3. Commit "Cambio audiencia".

### 3.3 Cambiar el tono de los titulares

La app pide titulares "humanos, sin spanglish, 8-14 palabras". Si querés
otro tono (más provocador, más técnico, más casual), cambialo.

**Prompt para Claude:**

```
En daily_brief.py hay una funcion llamada _editorial_prompt. Tiene este
bloque que describe el headline_es:

- headline_es: titular humano en espanol natural, 8-14 palabras.
    No Spanglish. No traduccion literal. No numeros de version.
    No frases tipo "actualiza con cambios importantes".
    Suena como algo que un creador diria en voz alta.

Quiero cambiar el tono a:

<DESCRIBE EL TONO QUE QUIERES. EJEMPLOS:
- "provocador, con titulares que generen polemica sana"
- "tecnico y preciso, para audiencia con base en programacion"
- "casual y divertido, con humor sutil, tipo Twitter">

Devolveme el bloque completo modificado, manteniendo el formato con guiones
y la sangria. Empieza con "- headline_es:". No agregues nada mas.
```

**Qué hacer con la respuesta:** reemplazá el bloque viejo con el nuevo.
Commit "Cambio tono".

### 3.4 Cambiar las fuentes según tu nicho

La app pesca de feeds de OpenAI, Anthropic, Google, TechCrunch, The Verge,
MIT Tech Review y Hacker News. Si tu nicho es distinto (legal, salud,
educación), cambialo.

**Prompt para Claude:**

```
En daily_brief.py tengo estas constantes con feeds RSS:

OFFICIAL_SOURCES = [
    "https://openai.com/news/rss.xml",
    "https://code.claude.com/docs/en/changelog/rss.xml",
    "https://docs.cloud.google.com/feeds/generative-ai-on-vertex-ai-release-notes.xml",
    "https://blog.google/products-and-platforms/products/gemini/rss/",
    "https://deepmind.google/blog/rss.xml",
]

EDITORIAL_RSS_SOURCES = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed",
]

Quiero reemplazarlas por feeds reales y activos del siguiente nicho:

<DESCRIBE TU NICHO. EJEMPLOS:
- "tecnologia legal y legal tech en espanol y en ingles"
- "salud digital y telemedicina"
- "educacion online y EdTech">

Devolveme las dos constantes completas, con URLs reales que existan hoy y
publiquen regularmente. Manteneme el mismo formato Python. Verifica
mentalmente cada URL antes de incluirla.
```

**Qué hacer con la respuesta:** reemplazá ambas constantes. Commit "Cambio
fuentes".

> ⚠️ Algunas URLs sugeridas por Claude pueden no existir. Probá una por una
> antes de publicar: pegá la URL en el navegador, si devuelve XML estás bien;
> si devuelve 404, sacala.

### 3.5 Cambiar el avatar personal

1. Buscá una foto tuya cuadrada, fondo limpio, idealmente 512×512 píxeles.
2. En el editor web de GitHub, andá a la carpeta `assets/brand/`.
3. Click en el archivo `rodrigo.png` → ícono de basurero → **Delete file**.
4. Click derecho en la carpeta `brand` → **Upload files** → arrastrá tu foto.
5. Renombrá tu archivo a exactamente `rodrigo.png` (mantenemos el nombre
   porque el código lo busca así; podemos renombrarlo después con otro
   prompt si querés).
6. Commit "Cambio avatar".

---

## Bloque 4 — Conectar el Bot de Telegram (7 min)

Ya tenés el bot y el token del Bloque 1. Ahora subís esas claves al repo
para que GitHub Actions pueda usar tu bot.

### 4.1 Abrí Secrets en tu repo de GitHub

1. En tu repo, andá a **Settings** (arriba a la derecha).
2. Sidebar izquierdo: **Secrets and variables** → **Actions**.
3. Click **New repository secret**.

### 4.2 Agregá los tres secretos

Repetí el flujo "New repository secret" tres veces, uno por cada par:

| Nombre del secret | Valor |
|---|---|
| `OPENAI_API_KEY` | la key que copiaste de OpenAI |
| `TELEGRAM_BOT_TOKEN` | el token que te dio BotFather |
| `TELEGRAM_CHAT_ID` | el número que sacaste del `getUpdates` |

**Verificación:** la pantalla de Secrets te muestra los tres nombres
listados.

---

## Bloque 5 — Subir tus claves a GitHub (4 min)

Esto ya lo hiciste en el Bloque 4. **Pasamos directo al deploy del Worker.**

> Este bloque queda como recordatorio de revisión: si vas a grabar el video,
> mostrá acá la captura final de la pantalla de Secrets con los tres
> nombres listos.

---

## Bloque 6 — Desplegar el Cloudflare Worker (12 min)

El Worker es lo que conecta Telegram con GitHub. Cuando escribís "1", "2" o
"3" en Telegram, el Worker recibe el mensaje y le dice a GitHub que arme el
contenido de ese número.

### 6.1 Generá un Personal Access Token de GitHub

El Worker necesita permiso para disparar workflows en tu repo.

1. Andá a <https://github.com/settings/tokens?type=beta> (fine-grained).
2. Click **Generate new token**.
3. Token name: `worker-notiagente`. Expiration: 90 días (renová cada 3 meses).
4. **Repository access** → Only select repositories → elegí tu repo.
5. **Repository permissions** → **Actions** → **Read and write**.
6. Click **Generate token** y copialo. Pegalo en tu Bloc de Notas.

### 6.2 Creá el Worker en Cloudflare

1. En el dashboard de Cloudflare, sidebar izquierdo: **Workers & Pages**.
2. Click **Create application** → **Create Worker**.
3. Nombre: `notiagente-bot`.
4. Click **Deploy** (te da un Worker vacío).
5. Click **Edit code**.

### 6.3 Pegá el código del Worker

Borrá todo lo que hay en el editor y pegá esto:

```javascript
export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok");

    const update = await request.json();
    const msg = update?.message;
    if (!msg?.text || !msg?.chat?.id) return new Response("ok");

    const chatId = msg.chat.id;
    const text = msg.text.trim();
    const choice = ["1", "2", "3"].includes(text) ? text : null;

    if (!choice) {
      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Escribi 1, 2 o 3 para generar contenido del Top 3.",
      });
      return new Response("ok");
    }

    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: `✅ Recibido. Voy a generar contenido del release #${choice}.`,
    });

    const dispatched = await dispatchWorkflow(env, choice);

    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: dispatched
        ? `🚀 Workflow lanzado. En unos segundos te llegara el contenido del release #${choice}.`
        : `❌ No pude lanzar el workflow. Revisa los logs en GitHub.`,
    });

    return new Response("ok");
  },
};

async function tg(env, method, payload) {
  return fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function dispatchWorkflow(env, choice) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/radar-content.yml/dispatches`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "notiagente-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({
      ref: env.GITHUB_REF || "main",
      inputs: { choice },
    }),
  });
  return r.ok;
}
```

Click **Save and deploy**.

### 6.4 Cargá los secretos del Worker

1. Volvé al overview del Worker.
2. Pestaña **Settings** → **Variables and Secrets**.
3. Click **Add variable**, tipo **Secret** (no plaintext) y agregá los 5:

| Nombre | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el mismo token de BotFather |
| `GITHUB_TOKEN` | el token fine-grained que creaste en 6.1 |
| `GITHUB_OWNER` | tu nombre de usuario de GitHub |
| `GITHUB_REPO` | nombre del repo (ej: `mi-notiagente`) |
| `GITHUB_REF` | `main` |

Click **Save and deploy** al terminar.

### 6.5 Conectá el webhook de Telegram

1. Copiá la URL pública de tu Worker. La ves en el dashboard del Worker; se
   ve como `https://notiagente-bot.<algo>.workers.dev`.
2. Pegá esta URL en tu navegador, reemplazando `<TOKEN>` por tu Bot Token y
   `<WORKER_URL>` por la URL del Worker:

```
https://api.telegram.org/bot<TOKEN>/setWebhook?url=<WORKER_URL>
```

3. El navegador debe mostrar `{"ok":true,"result":true,"description":"Webhook was set"}`.

**Verificación:** en tu chat con el bot, escribí `1`. El bot debe
responderte "✅ Recibido. Voy a generar contenido del release #1." y unos
segundos después "🚀 Workflow lanzado".

---

## Bloque 7 — Primer disparo y verificación (4 min)

### 7.1 Disparar el brief manualmente

1. En tu repo de GitHub, pestaña **Actions**.
2. Sidebar izquierdo: **AI Release Radar Brief**.
3. Botón **Run workflow** (derecha) → dejá la rama en `main` → **Run workflow**.
4. Esperá 1-2 minutos. Refrescá la página.

### 7.2 Verificar el Top 3 en Telegram

Mirá tu Telegram. Te llegó un mensaje empezando con:

```
NotiAgente Hered-IA · TOP 3
FECHA: 2026-...
1. ...
```

(Si lo personalizaste en el Bloque 3, va a aparecer **tu** nombre de app y
el headline en tu tono.)

### 7.3 Probar el botón

En el chat con tu bot, escribí `1` y mandá. En 30-60 segundos:
- "✅ Recibido"
- "🚀 Workflow lanzado"
- Mensaje con el guion en 4 formatos (TikTok, IG, LinkedIn, X)
- Imagen 1080×1080 con tu marca y titular en tipografía Anton

**Si pasó eso, terminaste.** Tu agente está vivo.

---

## Bloque 8 — Cierre y costos reales (2 min)

A partir de mañana, **a las 12:00 UTC** (7 AM Ecuador, 8 AM Colombia, 9 AM
Argentina, etc.) el sistema corre solo:
- 12:00 UTC → brief con Top 3.
- 12:10 UTC → contenido del #1 (por defecto), con imagen.
- Si escribís 2 o 3 en Telegram, te arma el de ese número.

**Costos mensuales reales:**

| Servicio | Costo |
|---|---|
| GitHub Actions | 0 USD |
| Cloudflare Worker | 0 USD |
| Telegram | 0 USD |
| OpenAI (1 brief + 1 content + 1 imagen al día) | ~2.50 USD |
| **Total** | **~2.50 USD al mes** |

**Si algo falla**, te va a llegar a Telegram un mensaje
`❌ NotiAgente fallo en modo brief` con el error. No vas a quedarte sin
saber qué pasó.

---

## ✅ Checklist final

- [ ] Las 5 cuentas creadas
- [ ] Repo forkeado a mi GitHub
- [ ] Marca personal y nombre cambiados (Bloque 3.1)
- [ ] Audiencia cambiada a la mía (Bloque 3.2)
- [ ] Tono editorial cambiado (Bloque 3.3)
- [ ] Fuentes actualizadas a mi nicho (Bloque 3.4)
- [ ] Mi foto en lugar del avatar default (Bloque 3.5)
- [ ] Bot de Telegram creado y testeado
- [ ] Los 3 secretos cargados en GitHub
- [ ] Cloudflare Worker deployado con los 5 secretos
- [ ] Webhook de Telegram registrado
- [ ] Brief de prueba recibido en Telegram
- [ ] Botón "1" probado y contenido recibido

Cuando todo eso esté marcado, listo. Ya tenés tu propio agente.

---

## 🚀 Si querés ir más allá

Cuando lleves dos semanas usándolo y sepas qué te falta, podés pedirle a
Claude prompts para:

- Agregar más formatos de contenido (script de podcast, email newsletter).
- Postear automático a Instagram o LinkedIn (requiere meterse con API de
  Meta, más avanzado).
- Cambiar la paleta de colores del fondo de fallback.
- Cambiar la tipografía a otra fuente bold.

Pero esto recién después de usarlo. Lo que mata estos proyectos no es la
falta de features, es no usarlos.
