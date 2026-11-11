# Bot de avisos de Stripchat → Telegram

Bot que avisa a un grupo de Telegram cuando una modelo de Stripchat se
conecta (y opcionalmente cuando se desconecta). No necesita ninguna API key
de Stripchat: usa la API pública del sitio.

```
🔴 ¡usuaria está EN VIVO en Stripchat!

Show: público
👉 Ver stream: https://stripchat.com/usuaria
```

Incluye la foto de la sala en el aviso (se puede desactivar).

Además, en el grupo se puede escribir **`/top`** y el bot responde con el
top de donadores del día (o del mes, ver más abajo).

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `bot.py` | el bot |
| `requirements.txt` | dependencias (solo `requests`) |
| `.env.example` | plantilla de configuración (copiar a `.env`) |
| `state.json` | recuerda el último estado (lo crea solo, **no borrarlo** si usás GitHub Actions) |
| `.github/workflows/check.yml` | automatización gratis con GitHub Actions |

## Paso 1 — Crear el bot en Telegram

1. Abrí Telegram y buscá **@BotFather** (el bot oficial, con visto azul).
2. Mandale `/newbot`.
   - Te va a pedir un **nombre** (ej: `Avisos de MiStreamer`).
   - Después un **username** que termine en `bot` (ej: `avisos_mi_streamer_bot`).
3. Te responde con un **token** parecido a `123456789:AAEhB...`. Copialo y
   guardalo: es la "contraseña" del bot. **No lo compartas con nadie.**

## Paso 2 — Agregar el bot al grupo

> No hace falta ser dueño del grupo: el bot solo necesita ser un miembro más
> con permiso de escribir (lo normal en cualquier grupo de chat). Si el grupo
> no te deja agregar miembros, pedile a un admin que lo agregue.

1. Entrá al grupo de Telegram → tocá el nombre del grupo → **Agregar miembros**.
2. Buscá el username del bot (ej: `avisos_mi_streamer_bot`) y agregalo.
   - No necesita ser admin del grupo para mandar mensajes.
   - Solo importaría en grupos donde únicamente los admins pueden escribir.

## Paso 3 — Obtener el ID del grupo

1. Una vez agregado el bot, mandá **cualquier mensaje en el grupo** (ej: "hola").
2. En la carpeta del bot, creá un archivo `.env` con esto (completá el token):

   ```
   TELEGRAM_BOT_TOKEN=123456789:AAEhB...
   ```

3. Corré:

   ```
   python bot.py get-chat-id
   ```

4. Te va a listar los chats que ve el bot. El del grupo empieza con `-100...`
   (o es el marcado como "probablemente tu grupo"). Copiá ese número.

   Si no aparece nada: mandá en el grupo un mensaje que mencione al bot
   (ej: `@tubot hola`) y probá de nuevo. No hace falta hacer al bot admin.

> **Otras formas de conseguir el ID sin el bot** (por ejemplo, pedíndoselo a
> un admin del grupo):
> - Mandarle a **@getidsbot** (privado) cualquier mensaje reenviado del
>   grupo; responde con el Chat ID. (Si el grupo restringe el contenido,
>   agregar @getidsbot al grupo un momento y luego sacarlo.)
> - En Telegram de PC: botón derecho sobre un mensaje → **Copiar enlace al
>   mensaje** → queda `t.me/c/NUMERO/...` → el ID es `-100` + `NUMERO`.
> - En [web.telegram.org](https://web.telegram.org), el ID aparece en la
>   barra de direcciones al abrir el grupo.
>
> Igual el bot **tiene que ser agregado al grupo** para poder escribir: con
> el ID solo no alcanza.

## Paso 4 — Completar la configuración

Dejá el `.env` así:

```
STRIPCHAT_MODEL=usuaria
TELEGRAM_BOT_TOKEN=123456789:AAEhB...
TELEGRAM_CHAT_ID=-1001234567890
```

`STRIPCHAT_MODEL` es el **nombre de usuario** de la modelo, el que aparece en
la URL de su perfil: `https://stripchat.com/USUARIA` → `USUARIA`. También
podés pegar la URL completa.

Instalá las dependencias (una sola vez):

```
pip install -r requirements.txt
```

## Paso 5 — Probar

```
python bot.py test-message   # tiene que llegar un mensaje al grupo
python bot.py status         # estado actual de la modelo
python bot.py top            # top de donadores de hoy (no manda nada)
python bot.py check          # una corrida real: guarda el estado
```

Nota: la **primera** corrida de `check` no avisa nada, solo guarda el estado
actual (para no spamear el grupo si la modelo ya estaba en vivo). A partir de
ahí, avisa cada vez que **pase de desconectada a conectada**.

## Cómo dejarlo corriendo gratis

### Opción A — GitHub Actions (recomendada, gratis y siempre encendida)

1. Creá una cuenta en [github.com](https://github.com) si no tenés.
2. Creá un repositorio **nuevo y público** (Add repository → New).
   - Público porque así GitHub Actions es gratis e ilimitado. Los datos
     sensibles van en "secrets" y no se ven en el código.
3. Subí los archivos del bot. Desde la web: **Add file → Create new file**.
   Cargá `bot.py`, `requirements.txt`, `.env.example`, `.gitignore` y, para el
   workflow, escribí la ruta completa `.github/workflows/check.yml` en el
   nombre del archivo y pegá su contenido. (O si usás git: cloná y commiteá.)
4. Andá a **Settings → Secrets and variables → Actions → New repository
   secret** y creá estos tres secretos:

   | Nombre | Valor |
   |---|---|
   | `STRIPCHAT_MODEL` | el usuario de la modelo |
   | `TELEGRAM_BOT_TOKEN` | el token del bot |
   | `TELEGRAM_CHAT_ID` | el ID del grupo |

5. Andá a la solapa **Actions**, entrá al workflow "Aviso de stream" y
   tocá **Run workflow** para probarlo (la primera corrida solo guarda
   estado; no va a mandar avisos todavía, es normal).
6. Listo: se ejecuta solo cada 5 minutos, para siempre, gratis.

Consejos:
- Para chequear cada 10 o 15 minutos, editá el `cron` en
  `.github/workflows/check.yml` (`*/10 * * * *`, `*/15 * * * *`).
- El workflow commitea `state.json` cuando cambia el estado; así recuerda si
  la modelo estaba conectada entre corridas. No lo borres.
- Si algún día GitHub te manda mail de que desactivó el workflow por
  "inactividad", entrá a Actions y reactiválo con un clic.
- **Nunca** subas el `.env` al repo (el `.gitignore` ya lo bloquea).

### Opción B — Tu propia PC

Si dejás la PC encendida:

```
python bot.py loop
```

Chequea cada 60 segundos (configurable con `CHECK_INTERVAL` en el `.env`).
Funciona igual, pero solo avisa mientras la PC esté prendida.

### Opción C — Un servidor (VPS)

Cualquier VPS sirve (inclusive los gratuitos tipo Oracle Cloud Always Free):
subís los archivos, `pip install -r requirements.txt`, y dejás corriendo
`python bot.py loop` (con systemd/screen/tmux para que sobreviva al cerrar la
sesión).

> Elegí **una sola** opción: si corrés el bot en dos lugares a la vez,
> pueden salir avisos duplicados (cada uno tiene su propio `state.json`).

## Personalización (todo opcional, en el `.env`)

```
# sticker en vez de la foto de la sala (ver abajo cómo se consigue)
STICKER_FILE_ID=...

# mensaje de conexión: {model} {show} {url} (\n = salto de línea)
MESSAGE_ONLINE=Prendio directo la Queen 👑👑👑❤️❤️❤️\n👉 {url}

# foto de la sala en el aviso (solo si no hay sticker; por defecto: sí)
SEND_PHOTO=0

# avisar también cuando se desconecta (por defecto: no)
NOTIFY_OFFLINE=1

# cada cuántos segundos chequear en modo loop (por defecto: 60)
CHECK_INTERVAL=30

# mensaje de desconexión
MESSAGE_OFFLINE=⚫ {model} se desconectó

# contestar /top en el grupo (1 = sí, 0 = no; por defecto: 1)
TOP_ENABLED=1

# cuántos puestos mostrar en /top (máximo 10; por defecto: 10)
TOP_LIMIT=10
```

### Comando `/top` en el grupo

Cualquiera en el grupo puede escribir:

```
/top            → top de donadores de hoy
/top mes        → top del mes en curso
/top mes pasado → top del mes anterior
```

El bot contesta citando el mensaje, con los primeros puestos (hasta 10) y los
tokens donados. La información es la misma que muestra Stripchat en el ranking de
"top tippers" de la sala, así que **solo funciona si la modelo tiene ese
ranking público** (`tipLeaderboardSettings.isPublic`).

Cosas a tener en cuenta:

- En GitHub Actions el bot lee los mensajes **en cada corrida del cron**
  (cada 5 minutos), así que la respuesta puede demorar hasta ~5 minutos.
  Si corrés `python bot.py loop` en una PC/VPS, contesta en el próximo
  chequeo (por defecto, 60 segundos).
- Solo contesta en el grupo configurado en `TELEGRAM_CHAT_ID` (y por privado
  a tu usuario de `TELEGRAM_USER_ID`, para que puedas probarlo).
- El bot guarda hasta dónde leyó en `state.json` (campo `update_offset`),
  así no repite la misma respuesta en cada corrida.
- Como el chequeo automático también lee los mensajes, puede consumir los
  updates que usan `get-chat-id` y `get-sticker-id`. Si necesitás volver a
  correr esos comandos, poné `TOP_ENABLED=0` un momento (o pausá el
  workflow), mandá el mensaje/sticker de nuevo y repetí.

### Sticker en vez de la foto

1. Abrí un chat **privado** con el bot (ej: `@panchiibot`) y mandale el
   sticker que quieras usar.
2. Corré `python bot.py get-sticker-id` → te muestra el `file_id`.
3. Ponelo en `STICKER_FILE_ID` (en el `.env` o como secret de GitHub
   Actions). El aviso queda: sticker + mensaje de texto.

Si en algún momento querés cambiar el sticker, mandale otro al bot por
privado, volvé a correr `get-sticker-id` y actualizá el valor.

### Crear tu propio sticker animado (de video)

Telegram acepta stickers de video en `.webm` con codec VP9: un lado de
exactamente 512px, hasta 3 segundos, hasta 30 fps, sin audio y menos de
256 KB. El flujo completo:

1. Hacé un video corto con lo que tengas (CapCut, Canva, un GIF, etc.).
2. Convertilo al formato exacto con ffmpeg:

   ```
   ffmpeg -i entrada.mp4 -t 3 -vf "scale=512:512:force_original_aspect_ratio=increase,crop=512:512,fps=30" -c:v libvpx-vp9 -b:v 0 -crf 40 -an sticker.webm
   ```

   (si pesa más de 256 KB, subí el `-crf`: números más grandes = más chico)

3. Mandale antes un mensaje privado al bot (requisito de Telegram para
   crear packs) y creá el pack:

   ```
   python bot.py make-sticker-set sticker.webm
   ```

   → te devuelve el link del pack (`t.me/addstickers/...`, para usarlo en
   todos tus chats) y el `file_id`.
4. Cargá ese `file_id` en `STICKER_FILE_ID`.

## Problemas comunes

- **"no existe la modelo"** → el usuario no es el de la URL del perfil. Andá
  al perfil en Stripchat y fijate qué viene después de `stripchat.com/`.
- **No llegan mensajes al grupo** → verificá el `TELEGRAM_CHAT_ID` con
  `get-chat-id` (tiene que empezar con `-100`), y que el bot esté en el grupo.
  Si el grupo solo deja escribir a los admins, un admin tiene que darle
  permiso de escritura al bot.
- **"Telegram rechazó sendMessage: bot was kicked..."** → el bot fue sacado
  del grupo; volvelo a agregar.
- **"no se pudo consultar Stripchat"** → falla momentánea de la API o de la
  red; el bot reintenta en el próximo chequeo, no pasa nada.
- **Aviso tardío con GitHub Actions** → el cron de GitHub a veces se demora
  unos minutos en horas pico. Es lo que hay con gratis 😅.
- **`/top` no contesta** → revisá que `TOP_ENABLED` no esté en `0`, que el
  bot esté en el grupo y que la modelo tenga el ranking público. En GitHub
  Actions puede tardar hasta ~5 minutos. Si tenés el bot corriendo en dos
  lugares a la vez, Telegram rechaza uno de los dos `getUpdates`: dejá una
  sola instancia.

## ¿Cómo funciona?

Consultar si una modelo está en vivo no requiere autenticación:

1. `GET stripchat.com/api/front/users/user-ids/{usuario}` → ID numérico.
2. `POST stripchat.com/api/front/models/get-statuses` → si la modelo está en
   vivo aparece en la respuesta (con el tipo de show).
3. `GET stripchat.com/api/front/models/{id}/tips-leaderboard` → top de
   donadores del día (también hay `/current-month` y `/monthly/{mes}/{año}`).

La foto sale de `img.doppiocdn.com`. El bot solo manda mensajes al grupo y,
para el `/top`, lee los mensajes nuevos con `getUpdates` (no lee todo el
historial del grupo). No necesita estar corriendo todo el tiempo: alcanza con
ejecutarlo cada tanto (por eso funciona en GitHub Actions).

El flujo de la API es el mismo que usa el proyecto open-source
[bcmk/siren](https://github.com/bcmk/siren) (un bot de avisos para muchas
plataformas de webcams, si algún día querés algo más completo).
