# Madrid Transit Graph Explorer — v0.1.0

Demostrador geoespacial de la red de **Metro de Madrid** (L1–L12 y Ramal) como grafo **topológico**, construido
con [City2Graph](https://github.com/c2g-dev/city2graph) 1.1.0 a partir de **OpenStreetMap** y visualizado con Leaflet.
Es un experimento reproducible, no una herramienta de planificación. El grafo v0.1.0 es topológico (sin horarios,
frecuencias ni tiempos de viaje). Sobre él, la página incluye un **explorador de perturbaciones estructural/programado**
(v0.5, estado **NEEDS_VALIDATION**, ver más abajo). Conectividad topológica **no** es accesibilidad efectiva,
funcionamiento operativo, demanda ni resiliencia observada, y la simulación **no** es tiempo real ni demanda.

Demo estática: <https://soroushkarahrodi79-oss.github.io/madrid-transit-graph/> (teselas OSM; ver [NOTICE.md](NOTICE.md)).

| Resultado del snapshot publicado | |
|---|---|
| Estaciones agregadas (nodos) | 242 |
| Conexiones (aristas) | 277 (3 compartidas por varias líneas) |
| Componentes conexos | 1 |
| Estaciones de correspondencia (>1 línea, inferidas) | 38 |
| Estaciones-línea (suma por línea) | 291 |
| Relaciones OSM | 28 (`route=subway`, `network=Metro de Madrid`, PTv2) |

## Definiciones

- **Unidad de análisis: estación agregada.** Una *estación-línea* es el par (estación, línea) tal como aparece en OSM
  (291; CRTM publica también un registro por estación-línea). Una *estación física* agrega las estaciones-línea de un
  mismo lugar (242 nodos). Un *intercambiador* oficial de CRTM es un grupo de estaciones-línea que puede incluir
  estaciones de nombre distinto; aquí no es un nodo, solo se usa para auditar.
- **Nodo** = estación agregada. **Arista** = par de estaciones agregadas consecutivas en al menos una línea,
  **sin dirección**; si varias líneas comparten el tramo es una sola arista con la lista `lines`. Es una conexión
  topológica, no la geometría real del túnel (se dibuja un segmento recto).
- **Fusión de estaciones (derivada, no es un hecho de OSM):** OSM define las áreas de parada *por línea* y City2Graph
  por sí solo da 13 componentes. Se fusionan paradas con el mismo **nombre normalizado** (sin sufijo de línea, tildes ni
  mayúsculas) cuyos miembros estén a **≤ 300 m** (máximo observado: 290 m). Después se **validó contra CRTM**.
- **Grado** = nº de estaciones adyacentes distintas (no es volumen de viajeros, importancia ni accesibilidad).
  **Componentes** = piezas conexas del grafo no dirigido; 1 indica conectividad topológica tras la fusión, no
  funcionamiento real. **Correspondencia** = estación con más de una línea.

## Procedencia y fechas

| Fuente | Fecha / versión | Uso |
|---|---|---|
| OpenStreetMap vía Overpass | estado OSM **2026-11-19T18:17:06Z**, descargado 18:19Z | Único origen del grafo |
| CRTM datos abiertos ([datos.crtm.es](https://datos.crtm.es/), «Elementos de la Red de Metro») | registros 2026-05-29; capa editada 2026-06-04 | Solo auditoría, no entra en el grafo |
| City2Graph / NetworkX / GeoPandas | 1.1.0 / 3.7 / 1.2.0 (entorno completo en `data/manifest.json`) | Construcción del grafo |
| Teselas y Leaflet | OSM estándar; Leaflet 1.9.4 | Solo visualización |

OSM y CRTM **no son necesariamente independientes**: la wiki de OSM documenta una importación de datos del CRTM;
su alcance no se analizó.

## Cómo usarlo

Python 3.12–3.14 (City2Graph exige `>=3.12,<3.15`; probado solo con 3.14.5 en Windows 11).

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python validate.py          # validación offline del snapshot publicado
.venv\Scripts\python -m http.server 8000  # abrir http://localhost:8000/ (el mapa no depende de Overpass)
```

El mapa carga Leaflet (unpkg, con SRI) y teselas de OSM por Internet; el navegador no lee GeoJSON desde `file://`.

**Regenerar no es reproducir el snapshot.** `build_graph.py` descarga el estado *actual* de OSM (posterior al del
snapshot) y normalmente dará cifras distintas. Los archivos publicados en `data/` **son** el snapshot: no se
conservaron las respuestas crudas de Overpass, así que no puede rederivarse exactamente. Su identidad queda en
`data/manifest.json` (SHA-256, fecha OSM, versiones); `validate.py` avisa si los datos difieren.

```powershell
.venv\Scripts\python build_graph.py   # regenera data/ (Overpass suele dar 502/504: reintenta solo)
.venv\Scripts\python audit_crtm.py    # crea data/crtm_audit.json en local (no se distribuye)
.venv\Scripts\python validate.py
```

## Auditoría de correspondencias contra CRTM

`audit_crtm.py` empareja los registros oficiales con nuestras estaciones por nombre normalizado y línea (2 alias de
nombre manuales: «Vicente Aleixandre»=«Metropolitano», «Hospital del Henares»=«Hospital de Henares») y compara.
Resultado sobre el snapshot (291 de 291 estaciones-línea emparejadas):

| Estado | Nº | Detalle |
|---|---|---|
| Confirmadas | 38 | Mismo código de intercambiador oficial y mismo conjunto de líneas |
| Falsas | 0 | |
| No verificada | 1 | Noviciado (L2): el campo de líneas de CRTM cita L3 y L10, pero tiene código propio |
| Ausentes en el grafo | 2 | Transbordos entre nombres distintos: Embajadores (L3)–Acacias (L5) y Callao (L3, L5)–Santo Domingo (L2) |

No se modificó el grafo: no había correspondencias falsas y añadir esos transbordos exigiría un tipo nuevo de arista
(fuera de v0.1). **El archivo de resultados `data/crtm_audit.json` no se distribuye:** une códigos oficiales de CRTM
con ids derivados de OSM y los regímenes «compartir igual» de ODbL y CRTM no se pudieron conciliar sin criterio
jurídico. Las cifras de arriba son resultados procesados. Proyecto sin respaldo ni certificación del CRTM.
**Powered by CRTM** · <https://www.crtm.es/>.

## Explorador de perturbaciones (v0.5, NEEDS_VALIDATION)

`index.html` permite elegir una estación y ver qué pasa si **se cierra** o si **se desactiva su correspondencia**:
pares de estaciones que quedan desconectados, estaciones aisladas, aumento medio de saltos y alcance (isocronas) desde
la estación. **Modelo estructural/programado. No es tiempo real ni demanda.** Detalle en
[`research/time_weighted_v05/REPORT.md`](research/time_weighted_v05/REPORT.md) (inglés) y
[`PHASE3.md`](research/time_weighted_v05/PHASE3.md).

- **Capa pública (solo topología, ODbL):** `data/explorer/disruption_topology.json`, generada por `build_explorer.py`
  desde el snapshot v0.1.0 y sin datos del CRTM. Reproduce exactamente los recuentos de fragmentación de v0.4
  (84 cierres que fragmentan la red; 1 correspondencia con 1.410 pares desconectados).
- **Capa de tiempos (solo en local):** tiempos planificados derivados de datos del CRTM (longitud del tramo ÷ una
  velocidad por línea; Línea 3 imputada; esperas y transbordos **supuestos**). Une ids de OSM con valores del CRTM y,
  por la incertidumbre de licencias, **no se distribuye** (ver [NOTICE.md](NOTICE.md)). Para verla en tu equipo:

```powershell
.venv\Scripts\python gtfs_ingest.py fetch
.venv\Scripts\python gtfs_ingest.py build
.venv\Scripts\python build_explorer.py --time --workers 3
.venv\Scripts\python -m http.server 8000   # la página detecta la capa solo en localhost
```

- **Resultado y su límite:** el veredicto preregistrado (el aumento medio de tiempo no se explica con grado, líneas ni
  intermediación) **depende de que la medida ignora los pares desconectados**. Entre los cierres que no fragmentan la
  red, el orden sigue a la intermediación (ρ ≈ 0,9). No se concluye que la simulación aporte valor sobre métricas
  estructurales. Sin validación externa.
- **Se cierra una estación, no un tramo.** Sin demanda, aforo, tiempo real, caminata entre estaciones distintas ni
  autobuses de sustitución.

## Validación

`validate.py` (librería estándar, independiente de City2Graph; 28 comprobaciones sobre el snapshot publicado, más 4
de auditoría si existe `crtm_audit.json` en local): ids únicos, referencias de aristas, sin bucles ni duplicados, coordenadas,
grado y componentes recalculados, indicadores = datos exportados, conteos por línea, metadatos de procedencia, ausencia
de atributos de horario o tiempo, hashes del snapshot, y una **regresión del defecto L10** (la auditoría comparó una
vez listas de líneas ordenadas como texto, `L10 < L4`; ahora compara conjuntos). `build_graph.py` además audita cada
relación contra los miembros OSM crudos (588 posiciones, 0 fallos de orden, 2 diferencias solo de etiqueta). El mapa se
probó en navegador de escritorio y móvil. Esto prueba coherencia interna y fidelidad al snapshot, **no** una
validación científica de toda la red.

## Limitaciones

- Una relación OSM **no prueba un servicio operativo** en una fecha dada; no hay tiempos ni vigencia.
- Aristas rectas; sin accesibilidad, tiempos ni anchura de transbordos. Orden de paradas y adyacencia no contrastados con CRTM.
- 2 transbordos oficiales ausentes; Noviciado sin verificar; la fusión es una inferencia (validada 38/38).
- Solo Metro de Madrid (sin Metro Ligero, Cercanías ni autobús).
- Snapshot no re-derivable exactamente (ver arriba); probado solo en Windows con Python 3.14.5.

## Licencias, atribución y cita

Resumen: código **MIT** ([LICENSE](LICENSE)); `data/` (OSM) **ODbL 1.0**, © colaboradores de
[OpenStreetMap](https://www.openstreetmap.org/copyright); datos CRTM bajo su [licencia propia](https://www.crtm.es/licencia-de-uso)
(no incluidos); City2Graph BSD-3-Clause; teselas sujetas a su [política](https://operations.osmfoundation.org/policies/tiles/).
Detalle por artefacto en [NOTICE.md](NOTICE.md).

Si usas City2Graph: Sato et al. (2026), *City2Graph: A Python library for Heterogeneous Graph Neural Networks and
spatial analysis in urban systems*, Computers, Environment and Urban Systems, 130, 102492.
DOI: [10.1016/j.compenvurbsys.2026.102492](https://doi.org/10.1016/j.compenvurbsys.2026.102492).

## Estructura

```
build_graph.py   obtención (OSM) + grafo (City2Graph) + exportación
audit_crtm.py    auditoría contra CRTM (salida local, no distribuida)
validate.py      validación offline
index.html       mapa Leaflet y explorador de perturbaciones (lee data/)
gtfs_ingest.py   tiempos planificados y frecuencias desde el GTFS del CRTM (salida local)
build_explorer.py datos precalculados del explorador (público: topología; local: tiempos)
research/        estudios v0.2–v0.5 (informe, preregistro, código y pruebas)
data/            stations.geojson · connections.geojson · metadata.json (ODbL) · manifest.json · explorer/
LICENSE · NOTICE.md · requirements.txt
```
