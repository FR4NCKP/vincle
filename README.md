# Vincle

Vincle convierte el celular en trackpad y teclado de la computadora. La conexión pasa por internet (Supabase Realtime), así que el celular y la PC no tienen que estar en la misma red.

```
Celular (PWA)  ──Broadcast──▶  Supabase Realtime  ──Broadcast──▶  PC (Python)
web/                           canal privado room:<id>            desktop/vincle.py
```

- `web/`: app del celular. Vite + TypeScript sin framework, publicada en GitHub Pages.
- `desktop/`: programa de la PC. Python con `pynput` (mouse y teclado), `tkinter` (ventana) y `segno` (QR).
- `supabase/migrations/`: tablas, funciones y políticas de la base de datos.

## Cómo se usa

1. En la PC abres Vincle. La ventana muestra un QR y un código de 6 dígitos que vence a los 2 minutos (luego aparece otro).
2. En el celular escaneas el QR con la cámara (abre la app con el código puesto) o abres la app y escribes el código.
3. La PC pregunta si permites la conexión. Mientras no aceptes, no se ejecuta nada de lo que llegue del celular.
4. Trackpad:
   - un dedo mueve el cursor
   - tocar es clic, tocar con dos dedos es clic derecho
   - mantener pulsado medio segundo y mover arrastra
   - dos dedos desplazan
5. Teclado (ícono de teclado arriba a la derecha):
   - lo que escribes se manda completo con **Enviar** o con la tecla intro del celular; con el campo vacío, Enviar funciona como Enter
   - `esc`, `tab` y las flechas se mandan al instante
   - `ctrl` queda activo para la siguiente tecla: tocas `ctrl` y luego la `c` y se manda ctrl + c
   - borrar con el campo vacío borra en la PC
6. Si recargas la app del celular, vuelve a la misma sesión sin pedir el código. **Desconectar** (en Ajustes del celular o en la ventana de la PC) cierra la sesión.

## Configuración de Supabase

El proyecto `vincle` ya está creado (plan Free, región `sa-east-1`, São Paulo) y la migración ya se aplicó. Si hay que recrearlo:

1. Crea un proyecto en el plan **Free**. Conviene la región más cercana a quienes lo usan.
2. Aplica `supabase/migrations/20261020000000_rooms_and_realtime_auth.sql` (en el SQL Editor o con `supabase db push`).
3. En **Authentication → Sign In / Providers**, activa **Allow anonymous sign-ins**.
4. Opcional, para más seguridad: en **Realtime → Settings**, desactiva **Allow public access**, así solo se permiten canales privados.
5. Copia la URL del proyecto y la clave publicable (`sb_publishable_…`) en `web/src/net.ts` y en `desktop/vincle.py`. Ambas son públicas por diseño; lo que protege los datos son las políticas RLS.

### Qué crea la migración

| Objeto | Para qué |
| --- | --- |
| `rooms` | Una sala por PC: PIN, quién la creó (`host_id`), quién la reclamó (`guest_id`) y cuándo vence el PIN. Cada miembro solo puede leer su propia sala. |
| `claim_attempts` | Intentos de reclamar un PIN. Se aceptan 10 cada 10 minutos por usuario. |
| `create_room(nombre)` | La llama la PC. Borra su sala anterior y crea otra con un PIN aleatorio que no esté en uso. |
| `claim_room(pin)` | La llama el celular. Si el PIN existe, está vigente y nadie lo usó, lo asigna a quien llama. Después de eso el PIN ya no sirve. |
| Políticas en `realtime.messages` | En el canal `room:<id>` solo el host y el guest de esa sala pueden unirse, enviar y recibir Broadcast y Presence. |

Las dos funciones son `SECURITY DEFINER` a propósito: son la única forma de crear o reclamar salas, porque la tabla no tiene políticas de inserción ni de actualización. El aviso del linter de Supabase sobre ellas es esperado.

## Protocolo

Todo viaja como Broadcast en el canal privado `room:<id>`.

Del celular a la PC:

| Evento | Datos | Efecto en la PC |
| --- | --- | --- |
| `hello` | `{}` | El celular entró al canal. La PC pide permiso o, si ya lo dio, responde `accepted`. |
| `move` | `{x, y}` en píxeles | Mueve el cursor de forma relativa. |
| `scroll` | `{x, y}` en píxeles de dedo | Rueda del mouse, con desplazamiento natural (unos 40 px por clic de rueda). |
| `click` | `{button: "left" \| "right"}` | Clic. |
| `drag` | `{down: true \| false}` | Mantiene o suelta el botón izquierdo. |
| `text` | `{text}` | Escribe el texto (admite tildes y ñ). |
| `key` | `{key, ctrl}` | `esc`, `tab`, `left`, `right`, `enter`, `backspace` o un solo carácter. |

De la PC al celular: `status` con `{state: "pending" | "accepted" | "rejected" | "closed"}`.

Presence: la PC se registra con la clave `host` y el celular con `guest`. Con eso cada uno sabe si el otro está en línea.

### Por qué ~30 mensajes por segundo

El plan Free de Supabase corta la conexión si el proyecto pasa de 100 mensajes por segundo, y cada Broadcast cuenta dos veces: una al enviarse y otra al recibirse. Por eso el celular acumula el movimiento y lo manda cada 33 ms como máximo. Así queda margen y el cursor se sigue viendo fluido.

La cuota mensual del plan Free es de 2 millones de mensajes. A 30 por segundo, cada hora de mover el cursor sin pausa gasta unos 216 000, o sea alrededor de 9 horas al mes de movimiento continuo. En uso real, con pausas, alcanza para bastante más. Si se pasa la cuota, Supabase no cobra en el plan Free: avisa por correo y puede restringir el servicio.

## Desarrollo

### App del celular

```bash
cd web
npm install
npm run dev
```

`npm run dev` la sirve en la red local (`--host`). Para abrirla desde el celular usa la IP de la PC (por ejemplo `http://192.168.1.20:5173`). La cámara solo funciona con HTTPS o en `localhost`, así que en la red local usa el código de 6 dígitos.

Para que el QR de la PC apunte a esa versión local:

```bash
set VINCLE_APP_URL=http://192.168.1.20:5173/
```

### Programa de la PC

```bash
cd desktop
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python vincle.py
```

Para generar un `.exe` que no necesite Python instalado:

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\pyinstaller --onefile --windowed --name Vincle vincle.py
```

La sesión anónima de la PC se guarda en `%APPDATA%\Vincle\session.json`. Gracias a eso la PC sigue siendo el mismo usuario cada vez que se abre.

### Publicación

Cada push a `main` que toque `web/` compila la app y la publica en GitHub Pages (`.github/workflows/pages.yml`). Dirección: https://fr4nckp.github.io/vincle/

## Seguridad

Quien maneja el teclado de una PC puede escribir comandos, así que la conexión tiene varias capas:

- El PIN vence a los 2 minutos y deja de servir apenas alguien lo reclama.
- Cada usuario tiene 10 intentos de PIN cada 10 minutos.
- El canal es privado y lo protegen políticas RLS: nadie fuera de la sala puede unirse, escuchar ni enviar.
- Hasta que alguien acepta en la ventana de la PC, las órdenes se descartan.
- Los movimientos tienen tope, el texto se corta a 2000 caracteres y los eventos desconocidos o mal formados se ignoran.

Límite conocido: Windows no deja que un programa sin permisos de administrador controle ventanas que sí los tienen (por ejemplo, el aviso de UAC). En esas ventanas Vincle no funciona.
