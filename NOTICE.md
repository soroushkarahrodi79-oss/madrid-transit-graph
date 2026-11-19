# Licencias, atribuciones y condiciones por artefacto

Cada componente tiene su propio régimen; **no se aplica una única licencia a todo el repositorio**.
Este documento es una lectura técnica de las condiciones publicadas, no asesoramiento jurídico.

| Artefacto | Régimen | Condiciones y notas |
|---|---|---|
| Código y documentación originales (`build_graph.py`, `audit_crtm.py`, `validate.py`, `index.html`, `README.md`, `NOTICE.md`) | **MIT** ([LICENSE](LICENSE)) | Conservar el aviso de copyright. |
| `data/stations.geojson`, `data/connections.geojson`, `data/metadata.json` | **ODbL 1.0** (base de datos derivada de OpenStreetMap) | © colaboradores de OpenStreetMap, <https://www.openstreetmap.org/copyright>. Atribución obligatoria; si se publica una base derivada o adaptada, debe ofrecerse también bajo ODbL y mantenerse abierta. Estos archivos **no** son MIT. |
| `data/manifest.json` | MIT | Metadatos del proyecto (hashes, versiones, fechas); no contiene datos de OSM ni de CRTM. |
| Auditoría CRTM (`data/crtm_audit.json`) | **No se distribuye** | Mezcla ids derivados de OSM (ODbL) con códigos oficiales de CRTM (licencia CRTM). Al exigir ambos regímenes «compartir igual», no se resolvió su combinación en un solo archivo, por lo que se excluye (`.gitignore`). Se crea en local con `audit_crtm.py`. |
| Datos del CRTM (consultados en tiempo de ejecución por `audit_crtm.py`; **no incluidos**) | [Licencia de datos abiertos y estáticos del CRTM](https://www.crtm.es/licencia-de-uso) | Citar al CRTM como fuente e indicar si el dato es bruto o procesado; mantener metadatos de fecha y condiciones; no distorsionar la información ni sugerir respaldo del CRTM; los datos originales deben compartirse con el mismo tipo de licencia. **Powered by CRTM**: <https://www.crtm.es/>. Este proyecto **no cuenta con respaldo, patrocinio ni certificación del CRTM**. Las cifras de la auditoría que aparecen en el README son resultados procesados. |
| City2Graph 1.1.0 (dependencia instalada con pip, no redistribuida) | BSD-3-Clause (verificado en los metadatos del paquete instalado) | Ver referencia académica abajo. |
| NetworkX, GeoPandas, Shapely, pandas | BSD-3-Clause (metadatos de los paquetes instalados) | No redistribuidos. |
| DuckDB | MIT (clasificador del paquete instalado) | No redistribuido. |
| certifi | MPL-2.0 (metadatos del paquete instalado) | No redistribuido; solo aporta el bundle de certificados. |
| Leaflet 1.9.4 | BSD-2-Clause (LICENSE de la versión 1.9.4) | Cargado desde unpkg con SRI; no se redistribuye. |
| Teselas del mapa base | Teselas estándar de OpenStreetMap, [política de uso](https://operations.osmfoundation.org/policies/tiles/) | Atribución visible en el mapa; URL `https://tile.openstreetmap.org/{z}/{x}/{y}.png`; sin prefetch, descarga masiva ni uso sin conexión; servicio «best-effort» sin SLA y bloqueable sin aviso en caso de uso excesivo. Quien reutilice la página debe cumplir esa política. |

## Referencia académica

Sato et al. (2026). *City2Graph: A Python library for Heterogeneous Graph Neural Networks and spatial analysis
in urban systems*. Computers, Environment and Urban Systems, 130, 102492.
DOI: [10.1016/j.compenvurbsys.2026.102492](https://doi.org/10.1016/j.compenvurbsys.2026.102492).

## Atribución visible

- Mapa e interfaz: «© OpenStreetMap contributors» (control de atribución de Leaflet) y «Powered by CRTM» con enlace a <https://www.crtm.es/>.
