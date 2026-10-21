# Pythia

[English](../../README.md) · [Deutsch](README.de.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · Español · [Français](README.fr.md) · [Português](README.pt-BR.md)

Pythia es una cabina de trading que empieza en papel y se queda ahí hasta que una estrategia se gana algo más. Tiene un motor en Rust, una aplicación de escritorio y una interfaz web encima, y un laboratorio de investigación en Python que decide qué puede operar el motor. El laboratorio cuenta cada idea que ha probado, así que un backtest con suerte no se cuela.

Ninguna estrategia de aquí ha demostrado ser rentable. Lee [SAFETY.md](../../SAFETY.md) (en inglés) antes de conectar una cuenta real.

<table>
  <tr>
    <td width="50%"><img src="../img/app-home.png" alt="Pantalla de inicio"></td>
    <td width="50%"><img src="../img/app-autopilot.png" alt="Pantalla de autopiloto"></td>
  </tr>
</table>

Capturas de una versión de desarrollo con datos de ejemplo.

## Descarga

La [última versión](https://github.com/SenseiIssei/Pythia/releases/latest) incluye:

| Plataforma | Archivo |
|---|---|
| Windows | `Pythia_<version>_x64-setup.exe` |
| macOS (Apple silicon e Intel) | `Pythia_<version>_universal.dmg` |
| Linux | `.AppImage`, `.deb` o `.rpm` |
| Línea de comandos | `pythia-cli-<version>-<plataforma>`: `pythia` y el motor sin ventana `pythia-server`, ver [cli/README.md](../../cli/README.md) (en inglés) |

Las versiones aún no están firmadas. Windows pregunta una vez (Más información, luego Ejecutar de todas formas); en macOS, la primera vez haz clic derecho en la app y elige Abrir.

## Qué hace

- Un autopiloto es una cantidad de dinero que opera una estrategia por su cuenta hasta que lo detienes o salta una regla de parada. Varios funcionan en paralelo y cada uno se mide contra BTC.
- Cripto, acciones de EE. UU. y ETF operan en la cuenta de papel de Alpaca. Los libros largo/corto operan perpetuos en papel, o en una cuenta demo de Bybit si añades claves de demo.
- Delante de cada orden está el gestor de riesgo: interruptor de emergencia, límites de pérdida diaria y de drawdown, topes de exposición, objetivo de volatilidad. Si algo no está claro, rechaza la orden.
- Cada estudio del laboratorio se registra antes de su primera ejecución, se prueba fuera de muestra después de costes y su Sharpe se deflacta según el número de pruebas hechas hasta ahora.
- Los modelos (volatilidad, ranking de monedas, cuantiles de rentabilidad) se entrenan en el laboratorio y los ejecuta el motor. Primero funcionan en modo sombra antes de poder influir en una operación.
- Las alertas llegan por Telegram o cualquier webhook, en inglés o alemán.

## Arquitectura

<img src="../img/architecture.svg" alt="Pythia: arriba la interfaz, debajo el motor en Rust, luego el laboratorio y el grabador, abajo los mercados" width="100%">

Un libro del laboratorio solo llega a un autopiloto junto con su evidencia. La selección automática ordena los libros por esa evidencia y por su historial real, y un libro experimental solo corre donde un autopiloto lo pide por su nombre.

## Resultados hasta ahora

Todos los números vienen de los ficheros de resultados del laboratorio o de los registros del propio motor. [`scripts/readme_charts.py`](../../scripts/readme_charts.py) dibuja cada gráfico de abajo e indica sus fuentes.

<img src="../img/scoreboard.png" alt="Sharpe fuera de muestra de las estrategias probadas" width="100%">

El mejor libro es una ruptura de Donchian sobre las diez monedas más líquidas: Sharpe 1,17 desde 2024, frente a 0,74 por mantener BTC. Aun así no supera la deflación. Con 1.836 pruebas contadas, la mejor de otras tantas estrategias de puro ruido mostraría alrededor de 2,69.

Dos estudios largo/corto con perpetuos superaron sus pruebas registradas (el residuo M4 y un carry de funding). Ninguno sobrevive a la deflación, así que ambos funcionan solo como experimentos. La mayoría de los libros de momentum resultan ser el filtro de 200 días de BTC disfrazado: los días en que el filtro está apagado, todos pierden dinero.

<img src="../img/forward.png" alt="Historial real de los autopilotos en papel desde el 15 de octubre de 2026" width="100%">

Los autopilotos en papel empezaron el 15 de octubre de 2026. Después de seis días, la selección automática principal gana un 0,48 % y BTC un 3,22 %. Es demasiado poco tiempo para significar algo; el gráfico está aquí para que el historial sea público desde el primer día.

<img src="../img/research_funnel.png" alt="Crecimiento del número de pruebas y el veredicto de cada estudio" width="100%">

69 estudios hasta ahora: 43 fallaron o se detuvieron, 7 funcionan en papel como experimentos marcados, 2 pasaron lo registrado sin confirmación, 5 produjeron un modelo que supera a su referencia. Cada veredicto está en [`research/lab/README.md`](../../research/lab/README.md).

<img src="../img/by_year.png" alt="Sharpe por año de los libros que siguen activos" width="100%">

Para volver a dibujar los gráficos:

```bash
pip install matplotlib
PYTHIA_DATA=/path/to/lab/data python scripts/readme_charts.py
```

Sin `PYTHIA_DATA` se omite el gráfico del historial real.

## Primeros pasos

Necesitas Node.js (LTS actual), Rust 1.85 o más reciente y, para el laboratorio, Python 3.

Aplicación de escritorio:

```bash
npm install
npm run tauri dev
npm run tauri build
```

Servidor e interfaz web:

```bash
cp .env.example .env
npm run server
```

```bash
echo "VITE_PYTHIA_SERVER=http://localhost:8787" > .env.local
npm run dev
```

El servidor escucha en `127.0.0.1:8787` (`PYTHIA_BIND` lo cambia). Las claves en `.env` son opcionales; sin ellas todo se queda en papel. Sin `VITE_PYTHIA_SERVER`, la interfaz web usa un pequeño motor de papel en el navegador.

Laboratorio:

```bash
cd research/lab
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests
```

Los datos vienen del grabador en `research/recorder` y de su carga histórica. [`research/lab/README.md`](../../research/lab/README.md) lista cada estudio y [`research/ops/README.md`](../../research/ops/README.md) las tareas programadas.

Comprobaciones:

```bash
npm run check
npm run preflight
npm run security:scan
```

En Windows, los scripts de npm quitan `CC` y `CXX` del entorno, porque las rutas con espacios rompen las compilaciones nativas de Rust.

## Estructura

| Ruta | Contenido |
|---|---|
| [`crates/pythia-core`](../../crates/pythia-core) | Motor: estrategias, riesgo, autopilotos, ejecución, mercados, previsiones, alertas |
| [`crates/pythia-ml`](../../crates/pythia-ml) | Inferencia de modelos (LightGBM, ONNX) con pruebas de paridad frente al laboratorio |
| [`server`](../../server) | Servidor HTTP y WebSocket sobre el motor |
| [`cli`](../../cli/README.md) | Línea de comandos `pythia` |
| [`src-tauri`](../../src-tauri) | Aplicación de escritorio |
| [`src`](../../src) | Interfaz React |
| [`research/lab`](../../research/lab/README.md) | Estudios, modelos, libros en papel, fábrica de estrategias |
| [`research/recorder`](../../research/recorder/README.md) | Grabador de datos de mercado y carga histórica |
| [`research/ops`](../../research/ops/README.md) | Tabla de tareas, comprobaciones de estado, scripts de despliegue |
| [`docs`](..) | Guías de [trading demo](../DEMO.md), [operación real](../LIVE-RUN.md), [alertas](../ALERTS.md), [modelos](../MODELS.md), [la API de Claude](../AI.md) y la [regla de preparación](../LIVE-READINESS.md) (en inglés) |

## Seguridad

- Una instalación nueva no opera nada real. Los autopilotos empiezan en papel o en la cuenta demo de un mercado.
- Operar en real requiere tus propias claves y una confirmación escrita por cada mercado. Nada se activa solo.
- Las claves se guardan en el llavero del sistema o en el entorno del servidor, nunca se registran ni se envían a la interfaz.
- Pythia no tiene funciones de retirada, depósito ni transferencia. Da a las claves de API solo permiso de trading.
- El spot de cripto es solo largo, los cortos existen solo en perpetuos y Polymarket es de solo lectura.

La lista completa está en [SAFETY.md](../../SAFETY.md). Los problemas de seguridad se reportan según [SECURITY.md](../../SECURITY.md).

## Licencia

[MIT](../../LICENSE). Datos de mercado de Alpaca, Binance, Kraken, Bybit, OKX, Coinbase, Deribit, DefiLlama, Polymarket y SEC EDGAR; a cada dato se le aplican los términos de su fuente. Si Pythia te resulta útil, puedes [apoyarlo en Ko-fi](https://ko-fi.com/senseiissei).
