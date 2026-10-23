# Vincle

Vincle convierte el celular en trackpad y teclado de la computadora. El emparejamiento pasa por internet (Supabase Realtime), así que el celular y la PC no tienen que estar en la misma red. Una vez aceptada la conexión, intentan hablar directo por WebRTC; si la red no lo permite, siguen por Supabase.

```
Celular (PWA)  ──Broadcast──▶  Supabase Realtime  ──Broadcast──▶  PC (Python)
web/                           canal privado room:<id>            desktop/vincle.py
      └───────────────── WebRTC directo (si se puede) ─────────────────┘
```

- `web/`: app del celular. Vite + TypeScript sin framework, publicada en GitHub Pages.
- `desktop/`: programa de la PC. Python con `pynput` (mouse y teclado), `tkinter` (ventana), `segno` (QR), `aiortc` (WebRTC) y `pystray` (ícono en la bandeja del sistema).
- `supabase/migrations/`: tablas, funciones y políticas de la base de datos.

## Cómo se usa

En el celular no se instala nada: Vincle se abre en el navegador desde https://fr4nckp.github.io/vincle/. En la PC hace falta un programa propio, porque ningún navegador deja que una página web mueva el mouse o escriba en otros programas. Ese programa es un solo archivo, `Vincle.exe`, que se descarga desde la misma página (al abrirla en una computadora) o desde [Releases](https://github.com/FR4NCKP/vincle/releases/latest). Se abre con doble clic y no se instala. Como no tiene firma digital, la primera vez Windows muestra «Windows protegió su PC»: hay que tocar «Más información» y luego «Ejecutar de todas formas».

1. En la PC abres Vincle. La ventana muestra un QR y un código de 6 dígitos que vence a los 2 minutos (luego aparece otro).
2. En el celular escaneas el QR con la cámara (abre la app con el código puesto) o abres la app y escribes el código.
3. La PC pregunta si permites la conexión, con el nombre del dispositivo. Mientras no aceptes, no se ejecuta nada de lo que llegue del celular. Si marcas **Recordar este dispositivo**, la próxima vez se conecta solo (ver «Dispositivos de confianza»).
4. Arriba están las pestañas **Trackpad**, **Diapositivas** y **Multimedia**. Trackpad:
   - un dedo mueve el cursor
   - tocar es clic, tocar con dos dedos es clic derecho y con tres, clic central (abre enlaces en otra pestaña)
   - mantener pulsado medio segundo y mover arrastra
   - dos dedos desplazan y, al soltarlos en movimiento, el desplazamiento sigue un momento y frena solo (inercia)
   - pellizcar con dos dedos hace zoom (Ctrl + rueda: navegador, documentos, imágenes)
   - deslizar tres dedos a los lados cambia de ventana (Alt + Tab), hacia arriba abre la vista de tareas y hacia abajo muestra el escritorio
5. Teclado, en la misma pantalla que el trackpad:
   - tocas «Toca aquí para escribir» (o el ícono de teclado de arriba) y se abre el teclado del celular; el trackpad sigue visible y se puede usar mientras escribes
   - cada letra llega a la PC al momento, igual que en un teclado real; borrar, el autocorrector y las sugerencias también se reflejan
   - mientras escribes aparece una fila con `esc`, `tab`, `ctrl`, las flechas, borrar y Enter
   - `ctrl` queda activo para la siguiente tecla: tocas `ctrl` y luego la `c` y se manda ctrl + c
   - para dejar de escribir, bajas el teclado del celular o tocas otra vez el ícono de teclado
   - el micrófono al lado del campo es el **dictado por voz**: hablas y el texto llega a la PC al terminar cada frase. Usa el reconocimiento del propio navegador (gratis, en el idioma del celular); si el navegador no lo tiene, el botón no aparece
6. Diapositivas:
   - **Siguiente** y **Anterior** pasan las diapositivas con AvPág y RePág, las mismas teclas que usan los presentadores inalámbricos; funcionan en PowerPoint, Google Slides, Canva y visores de PDF
   - **Iniciar presentación** manda F5 y **Salir** manda Esc
   - en la zona **Láser**, mientras mantienes el dedo y lo mueves, aparece un punto rojo en la pantalla de la PC donde está la presentación (también en un proyector), con una estela que se desvanece en medio segundo. Al soltar el punto se oculta y, al volver a tocar, sigue desde donde quedó. No mueve el mouse ni hace clic
   - mientras estás en esta pestaña, el celular no se apaga solo
7. Multimedia: reproducir/pausar, pista anterior y siguiente, bajar, silenciar y subir el volumen. Son las teclas multimedia de Windows, así que funcionan con Spotify, YouTube en el navegador, VLC y el volumen del sistema. Los botones de volumen se repiten mientras los mantienes.
8. Arriba se ve el nombre de la PC, «Conexión directa» o «Conectado» (por Supabase) y la **latencia**: lo que tarda un mensaje en ir a la PC y volver. Por la conexión directa se mide por el mismo canal que el cursor (si se pierde un paquete no se espera el reenvío), cada 0,5 s mientras usas el control y cada 2 s en reposo; la cifra solo se actualiza con lo medido en uso, porque en reposo el celular apaga la antena Wi-Fi entre envíos y daría valores más altos que los que se sienten. Por Supabase se mide cada 5 s. El punto se pone ámbar si pasa de 150 ms.
9. Si recargas la app del celular, vuelve a la misma sesión sin pedir el código. **Desconectar** (en Ajustes del celular o en la ventana de la PC) cierra la sesión.
10. En **Ajustes** del celular: sensibilidad del cursor, tema (automático, claro u oscuro), idioma (español o inglés) y las computadoras de confianza, con **Olvidar** para cada una.

### Dispositivos de confianza

Al permitir una conexión en la PC puedes marcar **Recordar este dispositivo**. Desde entonces, cuando ese celular está en la pantalla de conexión, pregunta cada 3 s si esa PC abrió Vincle y, en cuanto la abre, entra solo, sin QR ni código, y la PC lo acepta sin preguntar. La pantalla de conexión lo avisa («Se conectará solo a …»). Lo decide la base de datos, no lo que diga el celular: la PC confía en la cuenta anónima del celular, que se guarda en su navegador (si se borran los datos del navegador, hay que volver a aceptarlo). Para dejar de confiar: **Olvidar** en Ajustes del celular o en «Dispositivos de confianza» en la ventana de la PC.

### Bandeja del sistema, tema e idioma de la PC

Cerrar la ventana de Vincle no lo cierra: queda en la bandeja del sistema, junto al reloj (la primera vez lo avisa). Desde el ícono se vuelve a abrir la ventana, se activa **Iniciar con Windows** (solo con el `.exe`; arranca directo en la bandeja) o se sale del todo con **Salir**. Si llega un pedido de conexión con la ventana oculta, la ventana aparece sola.

La ventana sigue el tema de las apps de Windows (claro u oscuro, en Configuración → Personalización → Colores) y el idioma de Windows: español si Windows está en español, inglés en cualquier otro caso.

La interfaz tiene animaciones en las dos partes (botones, cambio de pantalla, escaneo del QR, código, conexión, láser). Si el sistema tiene activado «reducir movimiento» (o en Windows, «Mostrar animaciones» apagado), se omiten.

## Configuración de Supabase

El proyecto `vincle` ya está creado (plan Free, región `sa-east-1`, São Paulo) y la migración ya se aplicó. Si hay que recrearlo:

1. Crea un proyecto en el plan **Free**. Conviene la región más cercana a quienes lo usan.
2. Aplica las migraciones de `supabase/migrations/`, en orden (en el SQL Editor o con `supabase db push`).
3. En **Authentication → Sign In / Providers**, activa **Allow anonymous sign-ins**.
4. Opcional, para más seguridad: en **Realtime → Settings**, desactiva **Allow public access**, así solo se permiten canales privados.
5. Copia la URL del proyecto y la clave publicable (`sb_publishable_…`) en `web/src/net.ts` y en `desktop/vincle.py`. Ambas son públicas por diseño; lo que protege los datos son las políticas RLS.

### Qué crea la migración

| Objeto | Para qué |
| --- | --- |
| `rooms` | Una sala por PC: PIN, quién la creó (`host_id`), quién la reclamó (`guest_id`) y cuándo vence el PIN. Cada miembro solo puede leer su propia sala. |
| `claim_attempts` | Intentos fallidos de reclamar un PIN. Con 10 fallos en 10 minutos, el usuario queda bloqueado un rato. |
| `create_room(nombre)` | La llama la PC. Borra su sala anterior y crea otra con un PIN aleatorio que no esté en uso. |
| `claim_room(pin)` | La llama el celular. Si el PIN existe, está vigente y nadie lo usó, lo asigna a quien llama. Después de eso el PIN ya no sirve. |
| `trusted_devices` | Qué PC (`host_id`) confía en qué celular (`guest_id`), con los nombres de los dos. Cada lado ve y puede borrar solo las suyas. |
| `trust_guest(sala, nombre)` | La llama la PC al marcar «Recordar este dispositivo»: guarda al invitado de su sala actual. |
| `claim_trusted()` | La llama el celular: toma, sin PIN, la sala libre más reciente de una PC que confía en él. |
| `room_guest_trusted(sala)` | La llama la PC al recibir `hello`: si el invitado es de confianza, acepta sin preguntar. |
| Políticas en `realtime.messages` | En el canal `room:<id>` solo el host y el guest de esa sala pueden unirse, enviar y recibir Broadcast y Presence. |

`create_room`, `claim_room`, `trust_guest` y `claim_trusted` son `SECURITY DEFINER` a propósito: son la única forma de crear o reclamar salas, porque la tabla no tiene políticas de inserción ni de actualización. El aviso del linter de Supabase sobre ellas es esperado.

## Protocolo

El emparejamiento y el permiso viajan como Broadcast en el canal privado `room:<id>`. Las órdenes también, hasta que se abre la conexión directa (ver más abajo).

Del celular a la PC:

| Evento | Datos | Efecto en la PC |
| --- | --- | --- |
| `hello` | `{name}` | El celular entró al canal y dice cómo se llama (por ejemplo «Celular Android (SM-A515F)»). La PC pide permiso, acepta sola si es de confianza o, si ya lo dio, responde `accepted`. |
| `move` | `{x, y}` en píxeles | Mueve el cursor de forma relativa. |
| `scroll` | `{x, y}` en píxeles de dedo | Rueda del mouse, con desplazamiento natural (unos 40 px por clic de rueda). |
| `click` | `{button: "left" \| "right" \| "middle"}` | Clic. |
| `drag` | `{down: true \| false}` | Mantiene o suelta el botón izquierdo. |
| `text` | `{text}` | Escribe el texto (admite tildes y ñ). |
| `key` | `{key, ctrl}` | `esc`, `tab`, `left`, `right`, `enter`, `backspace`, `pagedown`, `pageup`, `f5`, las multimedia `play`, `prev`, `next`, `volup`, `voldown`, `mute`, o un solo carácter. |
| `zoom` | `{steps}` | Ctrl + rueda, `steps` clics (positivo agranda). |
| `gesture` | `{name: "left" \| "right" \| "up" \| "down"}` | Alt + Shift + Tab, Alt + Tab, Win + Tab y Win + D. |
| `ping` | `{t}` | La PC responde `pong` con el mismo `t` (no lleva `n` ni pasa por el orden). |
| `laser` | `{on: true \| false}` | Muestra u oculta el punto láser. Sigue donde quedó; solo empieza al centro la primera vez o si la ventana activa pasó a otra pantalla. |
| `laser_move` | `{x, y}` en píxeles | Mueve el punto láser (sin tocar el mouse). |

Todos los eventos menos `hello` y `ping` llevan además un número `n` que empieza en 1 con cada `hello`. Realtime puede entregar desordenados dos mensajes enviados casi juntos, así que la PC ejecuta clics, arrastres y teclas según ese número. Si falta uno, espera hasta 150 ms y, si no llega, sigue sin él (Broadcast no reintenta). `move` y `scroll` se aplican apenas llegan, porque sumar desplazamientos da lo mismo en cualquier orden; así el cursor nunca se frena esperando otro mensaje. Antes de un clic o una tecla, la PC termina de aplicar el movimiento pendiente. El celular no envía órdenes hasta recibir `accepted`.

La PC no mueve el cursor de golpe con cada `move`: lo reparte en pasos de 4 ms a lo largo del intervalo con que suelen llegar (lo mide sobre la marcha), para que se vea fluido.

### Conexión directa (WebRTC)

Por Supabase cada movimiento tarda unos 100 ms, porque va a São Paulo y vuelve. Por eso, en cuanto recibe `accepted`, el celular propone una conexión directa:

1. Crea dos canales de datos: `fast` (sin orden ni reenvíos, para `move`, `scroll` y `laser_move`) y `sure` (en orden y sin pérdidas, para todo lo demás).
2. Junta sus candidatos de red, con ayuda del STUN público y gratuito de Google, y manda la oferta completa como `rtc-offer` `{sdp}` por el canal privado.
3. La PC (`aiortc`) responde con `rtc-answer` `{sdp}`. Solo atiende ofertas después de haber dado permiso.
4. Cuando los dos canales abren, el celular manda las órdenes por ahí como JSON `{event, payload}`, sin el número `n` (el canal `sure` ya garantiza el orden), y envía el movimiento cada 8 ms en lugar de cada 33 ms.

Si en 8 segundos no se abre, o la conexión se cae, el celular vuelve a Supabase sin cortar nada y lo reintenta hasta 3 veces. No hay servidor TURN (que tiene costo), así que en redes que bloquean las conexiones directas se queda en Supabase. Una PC con una versión anterior a la 0.3.0 ignora `rtc-offer` y todo sigue por Supabase.

Medido en la misma computadora: de 100 ms por Supabase a unos 6 ms por la conexión directa. Por Wi-Fi se suman algunos milisegundos.

De la PC al celular: `status` con `{state: "pending" | "accepted" | "rejected" | "closed"}`, y `pong` `{t}` (por Broadcast o por el mismo canal directo por el que llegó el `ping`).

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

Desde la v0.2.0, al abrirse, `Vincle.exe` pregunta a GitHub cuál es la última versión. Si hay una más nueva, muestra un aviso con el botón **Actualizar**. Al tocarlo, descarga el `.exe` nuevo junto al actual, comprueba su tamaño y su huella SHA-256 contra la que publica GitHub, renombra el actual a `Vincle.old.exe` (Windows permite renombrar un programa abierto, pero no borrarlo), pone el nuevo en su lugar y lo abre. La versión nueva borra `Vincle.old.exe` al arrancar.

Para publicar una versión nueva del `.exe`, cambia `VERSION` en `desktop/vincle.py` y sube una etiqueta `v*` con el mismo número (el workflow se detiene si no coinciden). El workflow `.github/workflows/release.yml` lo compila en Windows con PyInstaller y lo adjunta a la versión en Releases:

```bash
git tag v0.2.0
```

```bash
git push origin v0.2.0
```

Para compilarlo en tu PC, usa el mismo comando de PyInstaller que está en ese workflow.

La sesión anónima de la PC se guarda en `%APPDATA%\Vincle\session.json`. Gracias a eso la PC sigue siendo el mismo usuario cada vez que se abre.

### Publicación

Cada push a `main` que toque `web/` compila la app y la publica en GitHub Pages (`.github/workflows/pages.yml`). Dirección: https://fr4nckp.github.io/vincle/

## Seguridad

Quien maneja el teclado de una PC puede escribir comandos, así que la conexión tiene varias capas:

- El PIN vence a los 2 minutos y deja de servir apenas alguien lo reclama.
- Con 10 PIN equivocados en 10 minutos, el usuario queda bloqueado un rato.
- El canal es privado y lo protegen políticas RLS: nadie fuera de la sala puede unirse, escuchar ni enviar.
- Hasta que alguien acepta en la ventana de la PC, las órdenes se descartan. El aviso de permiso no tiene botón por defecto: hay que hacer clic en «Permitir», así un Enter escrito por accidente en otro programa no da el control.
- Los movimientos tienen tope, el texto se corta a 2000 caracteres y los eventos desconocidos o mal formados se ignoran.

Límite conocido: Windows no deja que un programa sin permisos de administrador controle ventanas que sí los tienen (por ejemplo, el aviso de UAC). En esas ventanas Vincle no funciona.
