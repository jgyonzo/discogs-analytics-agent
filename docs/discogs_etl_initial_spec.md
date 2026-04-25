# Spec: Discogs Offline ETL for Agentic Analytics

## 1. Contexto general

El trabajo final del curso consiste en construir un sistema conversacional de analytics que reciba preguntas en lenguaje natural, genere código Python ejecutable, consulte un dataset y devuelva visualizaciones.

El dataset elegido es Discogs, específicamente el dump de releases, complementable luego con dumps de masters y artists. El dump principal de releases es un XML grande, de aproximadamente 60 GB, con una estructura anidada que incluye información de artistas, labels, formatos, géneros, estilos, tracklist, compañías, identificadores y videos.

Dado el tamaño y complejidad del XML, se decidió **no usar el XML crudo en tiempo de consulta del agente**. En su lugar, se construirá un ETL offline que transforme los dumps XML en una capa analítica limpia, persistida como **Parquet + DuckDB**. El agente consultará DuckDB mediante código Python generado, trayendo subconjuntos manejables a pandas para crear plots.

---

## 2. Objetivo del ETL

Construir un pipeline offline, reanudable e incrementalmente extensible que transforme los dumps Discogs en tablas analíticas limpias para ser consumidas por un agente de analytics.

El ETL debe:

- leer archivos XML locales en una primera versión;
- soportar en el futuro descarga automática desde Discogs;
- parsear XML en streaming, sin cargar el archivo completo en memoria;
- generar una capa staging relacional completa;
- generar una capa clean normalizada;
- generar una capa analytics simple y estable para el agente;
- publicar los datos en Parquet y DuckDB;
- emitir manifest, logs y data quality checks;
- dejar la arquitectura preparada para sumar masters y artists luego.

---

## 3. Decisiones de alto nivel

### 3.1 El XML no se consulta online

El XML de Discogs es demasiado grande y anidado para ser usado directamente por el agente.

**Decisión:**

```text
El XML se usará solo como fuente offline de ingestión.
El agente nunca consultará el XML crudo.
```

**Justificación:**

- 60 GB es inviable para pandas en memoria.
- XML nested genera mucho código frágil.
- El agente debe operar sobre un schema estable.
- La consulta debe ser rápida y repetible.

---

### 3.2 Output canónico: Parquet + DuckDB

**Decisión:**

```text
El ETL publicará outputs en Parquet y en DuckDB.
```

**Uso esperado:**

- Parquet: output canónico, portable, reconstruible.
- DuckDB: motor analítico local para consultas del agente.

**Justificación:**

- Parquet permite almacenar tablas intermedias y finales de forma eficiente.
- DuckDB es liviano, embebido y adecuado para analytics local.
- El agente puede generar Python que ejecuta SQL contra DuckDB y luego plottea con pandas/plotly.

---

### 3.3 Staging relacional completo

**Decisión:**

```text
La capa staging conservará la estructura relacional del XML.
No se simplificará prematuramente.
```

Ejemplo:

- `stg_releases`
- `stg_release_artists`
- `stg_release_labels`
- `stg_release_formats`
- `stg_release_format_descriptions`
- `stg_release_genres`
- `stg_release_styles`
- `stg_release_tracks`

**Justificación:**

- Permite preservar riqueza del XML.
- Evita perder información útil para futuras fases.
- Permite reconstruir nuevas vistas analíticas sin reparsear el XML.
- Mantiene separada la extracción de la modelización analítica.

---

### 3.4 Analytics v1 simple: una tabla principal + dos auxiliares

**Decisión:**

```text
La primera versión expone al agente:
- release_fact
- release_artist_bridge
- release_label_bridge
- release_unique_view en DuckDB
```

**Justificación:**

- Evita exponer demasiadas tablas al LLM.
- Reduce errores en código generado.
- Permite cubrir muchas queries útiles desde v1.
- Mantiene la puerta abierta para sumar `master_fact`, `artist_dim` y otras tablas luego.

---

### 3.5 Grano principal: release x style

**Decisión:**

```text
release_fact tendrá grano: una fila por release x style.
```

**Reglas:**

- Si un release tiene N styles, se generan N filas.
- Si un release no tiene styles, se genera una fila con `style = NULL` y `style_order = 0`.
- `primary_genre` será el primer género del XML.
- No se hará producto cartesiano entre géneros y estilos.

**Justificación:**

- Discogs no define explícitamente qué style pertenece a qué genre.
- El producto cartesiano `release x genre x style` inflaría artificialmente los datos.
- `release x style` permite análisis naturales por estilo sin listas anidadas.
- El agente evita tener que hacer `explode` en runtime.

---

### 3.6 Múltiples géneros

**Decisión:**

```text
Para v1 se usará primary_genre = primer género del XML.
```

Ejemplo:

Input:

```text
genres = ["Electronic", "Jazz"]
styles = ["Future Jazz", "Downtempo"]
```

Output:

```text
release_id | primary_genre | style
X          | Electronic    | Future Jazz
X          | Electronic    | Downtempo
```

No se intentará inferir relación style → genre.

**Future work:**

```text
Agregar release_genre_bridge para análisis multi-género exacto.
```

---

### 3.7 Formatos: separar flags a nivel format y a nivel release

**Decisión corregida:**

```text
clean_release_formats tendrá flags a nivel format:
- is_vinyl_format
- is_cd_format
- is_cassette_format
- is_digital_format
- is_box_set_format

release_format_summary tendrá flags a nivel release:
- has_vinyl
- has_cd
- has_cassette
- has_digital
- has_box_set
```

**Justificación:**

- `clean_release_formats` tiene grano `release x format`.
- `has_*` sería ambiguo en esa tabla.
- `release_format_summary` resume todos los formatos de un release.
- `release_fact` consume `release_format_summary`, no `clean_release_formats`, para evitar multiplicación artificial.

---

### 3.8 Fechas normalizadas en ETL

**Decisión:**

```text
El ETL normaliza fechas y deriva year, month, day, decade y released_date_precision.
```

**Justificación:**

- Discogs puede tener fechas parciales como `1998-06-00`.
- No conviene que el agente parse fechas en cada query.
- Las queries temporales deben ser consistentes.

---

### 3.9 Masters y artists quedan preparados como expansión

**Decisión:**

```text
V1 se centra en releases.
Masters y artists se pueden parsear o dejar preparados, pero no son obligatorios para el primer release_fact.
```

**Future work:**

- `master_fact`
- `artist_dim`
- joins adicionales con releases

**Justificación:**

- Releases alcanza para una v1 potente.
- Masters permitirá luego análisis a nivel obra, evitando sesgo por reediciones.
- Artists permitirá enriquecer análisis por artista, alias, grupos y trayectoria.

---

## 4. Arquitectura del pipeline

```text
RAW XML
  ↓
STAGING
  ↓
CLEAN
  ↓
CLEAN-DERIVED / SUMMARY
  ↓
ANALYTICS
  ↓
DUCKDB
```

---

### 4.1 Raw

Contiene los archivos originales o descomprimidos.

```text
data/raw/discogs/{snapshot_id}/
  releases.xml
  masters.xml
  artists.xml
```

En v1, los archivos ya existen localmente.  
En una fase futura, se agregará un step de descarga desde Discogs y descompresión.

---

### 4.2 Staging

Parseo streaming del XML a tablas relacionales.  
Debe hacer mínima lógica de negocio.

Outputs:

```text
data/staging/{run_id}/
  stg_releases.parquet
  stg_release_artists.parquet
  stg_release_labels.parquet
  stg_release_formats.parquet
  stg_release_format_descriptions.parquet
  stg_release_genres.parquet
  stg_release_styles.parquet
  stg_release_tracks.parquet
  stg_masters.parquet
  stg_artists.parquet
```

---

### 4.3 Clean

Normalización, casteos, deduplicación y derivaciones básicas.

Outputs:

```text
data/clean/{run_id}/
  clean_releases.parquet
  clean_release_artists.parquet
  clean_release_labels.parquet
  clean_release_formats.parquet
  clean_release_genres.parquet
  clean_release_styles.parquet
  release_format_summary.parquet
```

---

### 4.4 Analytics

Tablas finales para el agente.

Outputs:

```text
data/analytics/{run_id}/
  release_fact.parquet
  release_artist_bridge.parquet
  release_label_bridge.parquet
```

---

### 4.5 Published DuckDB

```text
data/published/duckdb/
  discogs.duckdb
```

Tablas:

```text
release_fact
release_artist_bridge
release_label_bridge
release_unique_view
```

---

## 5. Steps del ETL

### Step 0 — Init run

Responsabilidades:

- generar `run_id`;
- cargar config;
- validar paths;
- crear carpetas de output;
- inicializar manifest;
- inicializar logging.

Inputs:

```text
configs/base.yml
.env
```

Outputs:

```text
data/manifests/{run_id}.json
data/logs/{run_id}.log
```

---

### Step 1 — Prepare sources

Responsabilidades v1:

- validar que los XML existen localmente;
- opcionalmente copiar/referenciar archivos a `data/raw`;
- descomprimir si vienen `.gz`;
- calcular checksum;
- registrar tamaño de archivo.

Responsabilidades futuras:

- descargar dumps desde Discogs;
- verificar integridad;
- descomprimir;
- versionar snapshot.

---

### Step 2 — Parse releases XML

Responsabilidades:

- parsear `releases.xml` en streaming;
- generar staging tables de releases;
- escribir Parquet en batches;
- no cargar el XML completo en memoria.

Outputs principales:

```text
stg_releases
stg_release_artists
stg_release_labels
stg_release_formats
stg_release_format_descriptions
stg_release_genres
stg_release_styles
stg_release_tracks
```

---

### Step 3 — Parse masters XML

Responsabilidades:

- parsear `masters.xml` en streaming;
- generar `stg_masters`;
- dejar preparado el camino para `master_fact`.

En v1 puede ser opcional si se quiere reducir scope, pero el contrato ya lo contempla.

---

### Step 4 — Parse artists XML

Responsabilidades:

- parsear `artists.xml` en streaming;
- generar `stg_artists`;
- dejar preparado el camino para `artist_dim`.

En v1 puede ser opcional si se quiere reducir scope.

---

### Step 5 — Normalize releases

Responsabilidades:

- limpiar strings;
- normalizar nulls;
- castear IDs;
- parsear fechas;
- derivar `year`, `month`, `day`, `released_date`, `released_date_precision`, `decade`;
- derivar conteos por release:
  - `track_count`
  - `artist_count`
  - `label_count`
  - `genre_count`
  - `style_count`
  - `format_count`

Output:

```text
clean_releases
```

---

### Step 6 — Normalize dimensions / bridges

Responsabilidades:

- limpiar artistas;
- limpiar labels;
- limpiar genres;
- limpiar styles;
- limpiar formats;
- deduplicar registros exactos cuando corresponda;
- marcar primary artist, primary label, primary genre y primary format.

Outputs:

```text
clean_release_artists
clean_release_labels
clean_release_formats
clean_release_genres
clean_release_styles
```

---

### Step 7 — Build release_format_summary

Responsabilidades:

- agregar formatos a nivel release;
- derivar primary format;
- derivar flags `has_*`.

Input:

```text
clean_release_formats
```

Output:

```text
release_format_summary
```

---

### Step 8 — Build analytics tables

Responsabilidades:

- construir `release_fact`;
- construir `release_artist_bridge`;
- construir `release_label_bridge`.

Inputs:

```text
clean_releases
clean_release_artists
clean_release_labels
clean_release_genres
clean_release_styles
release_format_summary
```

Outputs:

```text
release_fact
release_artist_bridge
release_label_bridge
```

---

### Step 9 — Publish DuckDB

Responsabilidades:

- crear o reemplazar `discogs.duckdb`;
- cargar tablas analytics desde Parquet;
- crear vista `release_unique_view`.

Outputs:

```text
data/published/duckdb/discogs.duckdb
```

---

### Step 10 — Run data quality checks

Responsabilidades:

- validar integridad, completitud y consistencia;
- emitir warnings;
- fallar si hay errores críticos.

Outputs:

```text
quality_checks en manifest
logs
```

---

### Step 11 — Finalize manifest

Responsabilidades:

- registrar outputs finales;
- row counts;
- checksums;
- duración por step;
- status final;
- warnings.

Output:

```text
data/manifests/{run_id}.json
```

---

## 6. Contratos de tablas: Staging

### 6.1 `stg_releases`

Grano: 1 fila por release.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `title` | TEXT | sí |
| `country` | TEXT | sí |
| `released_raw` | TEXT | sí |
| `notes` | TEXT | sí |
| `data_quality` | TEXT | sí |
| `master_id` | BIGINT | sí |
| `master_is_main_release` | BOOLEAN | sí |
| `status` | TEXT | sí |
| `source_file` | TEXT | no |
| `parsed_at` | TIMESTAMP | no |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id
```

---

### 6.2 `stg_release_artists`

Grano: `release x main artist`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `artist_order` | INTEGER | no |
| `artist_id` | BIGINT | sí |
| `artist_name` | TEXT | sí |
| `artist_anv` | TEXT | sí |
| `artist_join` | TEXT | sí |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, artist_order
```

---

### 6.3 `stg_release_labels`

Grano: `release x label`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `label_order` | INTEGER | no |
| `label_id` | BIGINT | sí |
| `label_name` | TEXT | sí |
| `catno` | TEXT | sí |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, label_order
```

---

### 6.4 `stg_release_formats`

Grano: `release x format`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `format_order` | INTEGER | no |
| `format_name` | TEXT | sí |
| `format_qty_raw` | TEXT | sí |
| `format_text` | TEXT | sí |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, format_order
```

---

### 6.5 `stg_release_format_descriptions`

Grano: `release x format x description`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `format_order` | INTEGER | no |
| `description_order` | INTEGER | no |
| `description` | TEXT | sí |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, format_order, description_order
```

---

### 6.6 `stg_release_genres`

Grano: `release x genre`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `genre_order` | INTEGER | no |
| `genre` | TEXT | sí |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, genre_order
```

---

### 6.7 `stg_release_styles`

Grano: `release x style`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `style_order` | INTEGER | no |
| `style` | TEXT | sí |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, style_order
```

---

### 6.8 `stg_release_tracks`

Grano: `release x track`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `track_order` | INTEGER | no |
| `position` | TEXT | sí |
| `title` | TEXT | sí |
| `duration_raw` | TEXT | sí |
| `track_type` | TEXT | sí |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, track_order
```

---

### 6.9 `stg_masters`

Grano: 1 fila por master.

| columna | tipo | nullable |
|---|---:|---:|
| `master_id` | BIGINT | no |
| `title` | TEXT | sí |
| `main_release_id` | BIGINT | sí |
| `year_raw` | TEXT | sí |
| `run_id` | TEXT | no |

---

### 6.10 `stg_artists`

Grano: 1 fila por artist.

| columna | tipo | nullable |
|---|---:|---:|
| `artist_id` | BIGINT | no |
| `artist_name` | TEXT | sí |
| `realname` | TEXT | sí |
| `profile` | TEXT | sí |
| `run_id` | TEXT | no |

---

## 7. Contratos de tablas: Clean

### 7.1 `clean_releases`

Grano: 1 fila por release.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `title` | TEXT | sí |
| `country` | TEXT | sí |
| `released_raw` | TEXT | sí |
| `year` | INTEGER | sí |
| `month` | INTEGER | sí |
| `day` | INTEGER | sí |
| `released_date` | DATE | sí |
| `released_date_precision` | TEXT | no |
| `decade` | INTEGER | sí |
| `data_quality` | TEXT | sí |
| `master_id` | BIGINT | sí |
| `master_is_main_release` | BOOLEAN | sí |
| `track_count` | INTEGER | no |
| `artist_count` | INTEGER | no |
| `label_count` | INTEGER | no |
| `genre_count` | INTEGER | no |
| `style_count` | INTEGER | no |
| `format_count` | INTEGER | no |
| `has_videos` | BOOLEAN | no |
| `has_extraartists` | BOOLEAN | no |
| `run_id` | TEXT | no |

Valores permitidos para `released_date_precision`:

```text
day
month
year
unknown
invalid
```

---

### 7.2 `clean_release_artists`

Grano: `release x main artist`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `artist_order` | INTEGER | no |
| `artist_id` | BIGINT | sí |
| `artist_name` | TEXT | sí |
| `artist_anv` | TEXT | sí |
| `artist_join` | TEXT | sí |
| `is_primary_artist` | BOOLEAN | no |
| `run_id` | TEXT | no |

Regla:

```text
is_primary_artist = artist_order = 1
```

---

### 7.3 `clean_release_labels`

Grano: `release x label`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `label_order` | INTEGER | no |
| `label_id` | BIGINT | sí |
| `label_name` | TEXT | sí |
| `catno` | TEXT | sí |
| `is_primary_label` | BOOLEAN | no |
| `run_id` | TEXT | no |

Regla:

```text
is_primary_label = label_order = 1
```

Deduplicación:

```text
Si hay duplicado exacto release_id + label_id + label_name + catno, dejar uno solo.
Si cambia catno, conservar ambos.
```

---

### 7.4 `clean_release_formats`

Grano: `release x format`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `format_order` | INTEGER | no |
| `format_name_raw` | TEXT | sí |
| `format_group` | TEXT | no |
| `format_quantity` | INTEGER | sí |
| `format_text` | TEXT | sí |
| `format_description_summary` | TEXT | sí |
| `is_primary_format` | BOOLEAN | no |
| `is_vinyl_format` | BOOLEAN | no |
| `is_cd_format` | BOOLEAN | no |
| `is_cassette_format` | BOOLEAN | no |
| `is_digital_format` | BOOLEAN | no |
| `is_box_set_format` | BOOLEAN | no |
| `run_id` | TEXT | no |

Valores permitidos para `format_group`:

```text
Vinyl
CD
Cassette
Digital
DVD/Blu-ray
Shellac
Box Set
Other
Unknown
```

Regla:

```text
is_primary_format = format_order = 1
```

---

### 7.5 `clean_release_genres`

Grano: `release x genre`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `genre_order` | INTEGER | no |
| `genre` | TEXT | sí |
| `is_primary_genre` | BOOLEAN | no |
| `run_id` | TEXT | no |

Regla:

```text
is_primary_genre = genre_order = 1
```

---

### 7.6 `clean_release_styles`

Grano: `release x style`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `style_order` | INTEGER | no |
| `style` | TEXT | sí |
| `run_id` | TEXT | no |

---

## 8. Contrato de tabla Summary

### 8.1 `release_format_summary`

Grano: 1 fila por release.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `primary_format_raw` | TEXT | sí |
| `primary_format_group` | TEXT | no |
| `format_quantity` | INTEGER | sí |
| `format_description_summary` | TEXT | sí |
| `format_count` | INTEGER | no |
| `has_vinyl` | BOOLEAN | no |
| `has_cd` | BOOLEAN | no |
| `has_cassette` | BOOLEAN | no |
| `has_digital` | BOOLEAN | no |
| `has_box_set` | BOOLEAN | no |
| `run_id` | TEXT | no |

Derivación:

```text
primary_format_* = valores del row donde is_primary_format = true
has_vinyl = any(is_vinyl_format)
has_cd = any(is_cd_format)
has_cassette = any(is_cassette_format)
has_digital = any(is_digital_format)
has_box_set = any(is_box_set_format)
format_count = count(rows in clean_release_formats for release_id)
```

---

## 9. Contratos de tablas Analytics

### 9.1 `release_fact`

Grano: `release x style`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `master_id` | BIGINT | sí |
| `title` | TEXT | sí |
| `primary_artist_id` | BIGINT | sí |
| `primary_artist_name` | TEXT | sí |
| `country` | TEXT | sí |
| `released_raw` | TEXT | sí |
| `year` | INTEGER | sí |
| `month` | INTEGER | sí |
| `day` | INTEGER | sí |
| `released_date` | DATE | sí |
| `released_date_precision` | TEXT | no |
| `decade` | INTEGER | sí |
| `data_quality` | TEXT | sí |
| `track_count` | INTEGER | no |
| `artist_count` | INTEGER | no |
| `label_count` | INTEGER | no |
| `genre_count` | INTEGER | no |
| `style_count` | INTEGER | no |
| `format_count` | INTEGER | no |
| `primary_label_id` | BIGINT | sí |
| `primary_label_name` | TEXT | sí |
| `primary_format_raw` | TEXT | sí |
| `primary_format_group` | TEXT | no |
| `format_quantity` | INTEGER | sí |
| `format_description_summary` | TEXT | sí |
| `has_vinyl` | BOOLEAN | no |
| `has_cd` | BOOLEAN | no |
| `has_cassette` | BOOLEAN | no |
| `has_digital` | BOOLEAN | no |
| `has_box_set` | BOOLEAN | no |
| `primary_genre` | TEXT | sí |
| `style` | TEXT | sí |
| `style_order` | INTEGER | no |
| `run_id` | TEXT | no |

Clave lógica:

```text
release_id, style_order
```

Regla para releases sin style:

```text
style_order = 0
style = NULL
```

Construcción:

```text
clean_releases
LEFT JOIN primary artist
LEFT JOIN primary label
LEFT JOIN primary genre
LEFT JOIN release_format_summary
LEFT JOIN clean_release_styles
```

No debe joinear directo contra `clean_release_formats`.

---

### 9.2 `release_artist_bridge`

Grano: `release x main artist`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `artist_id` | BIGINT | sí |
| `artist_name` | TEXT | sí |
| `artist_order` | INTEGER | no |
| `artist_anv` | TEXT | sí |
| `artist_join` | TEXT | sí |
| `is_primary_artist` | BOOLEAN | no |
| `run_id` | TEXT | no |

---

### 9.3 `release_label_bridge`

Grano: `release x label`.

| columna | tipo | nullable |
|---|---:|---:|
| `release_id` | BIGINT | no |
| `label_id` | BIGINT | sí |
| `label_name` | TEXT | sí |
| `label_order` | INTEGER | no |
| `catno` | TEXT | sí |
| `is_primary_label` | BOOLEAN | no |
| `run_id` | TEXT | no |

---

## 10. DuckDB contract

### Tablas físicas

```text
release_fact
release_artist_bridge
release_label_bridge
```

### Vista requerida

```sql
CREATE OR REPLACE VIEW release_unique_view AS
SELECT DISTINCT
  release_id,
  master_id,
  title,
  primary_artist_id,
  primary_artist_name,
  country,
  released_raw,
  year,
  month,
  day,
  released_date,
  released_date_precision,
  decade,
  data_quality,
  track_count,
  artist_count,
  label_count,
  genre_count,
  style_count,
  format_count,
  primary_label_id,
  primary_label_name,
  primary_format_raw,
  primary_format_group,
  format_quantity,
  format_description_summary,
  has_vinyl,
  has_cd,
  has_cassette,
  has_digital,
  has_box_set,
  primary_genre,
  run_id
FROM release_fact;
```

Regla crítica para el agente:

```text
release_fact has one row per release-style combination.
For release counts, use COUNT(DISTINCT release_id) or release_unique_view.
Do not use COUNT(*) unless the question explicitly asks for release-style rows.
```

---

## 11. Reglas de normalización

### 11.1 Fecha de release

Input posible:

```text
1999-07-13
1998-06-00
1987
0000
Unknown
```

Output esperado:

```text
released_raw
year
month
day
released_date
released_date_precision
decade
```

Reglas:

```text
YYYY-MM-DD válido → precision = day
YYYY-MM-00 → precision = month, day = NULL, released_date = YYYY-MM-01
YYYY-MM → precision = month, released_date = YYYY-MM-01
YYYY → precision = year, released_date = YYYY-01-01
0000 / Unknown / vacío → precision = unknown
no parseable → precision = invalid
```

Validación de año:

```text
1850 <= year <= current_year + 1
```

Década:

```text
decade = (year // 10) * 10
```

---

### 11.2 Formatos

Mapping base:

```text
vinyl              -> Vinyl
lathe cut          -> Vinyl
acetate            -> Vinyl
flexi-disc         -> Vinyl
cd                 -> CD
cassette           -> Cassette
file               -> Digital
dvd                -> DVD/Blu-ray
blu-ray            -> DVD/Blu-ray
shellac            -> Shellac
box set            -> Box Set
other / unknown    -> Other / Unknown
```

Reglas:

```text
format_group se deriva de format_name_raw.
format_description_summary concatena descriptions del format con "; ".
is_vinyl_format puede considerar format_group = Vinyl o descriptions como LP, 12", 10", 7".
is_cd_format se deriva de format_group = CD.
is_cassette_format se deriva de format_group = Cassette.
is_digital_format se deriva de format_group = Digital.
is_box_set_format se deriva de format_group = Box Set o description = Box Set.
```

---

## 12. Data quality checks

### 12.1 `stg_releases`

```text
release_id not null
release_id unique
row_count > 0
```

### 12.2 `clean_releases`

```text
release_id unique
year null or 1850 <= year <= current_year + 1
decade = floor(year / 10) * 10 when year is not null
track_count >= 0
artist_count >= 0
label_count >= 0
genre_count >= 0
style_count >= 0
format_count >= 0
released_date_precision in ('day', 'month', 'year', 'unknown', 'invalid')
```

### 12.3 `clean_release_formats`

```text
release_id not null
no duplicate (release_id, format_order)
format_group in ('Vinyl', 'CD', 'Cassette', 'Digital', 'DVD/Blu-ray', 'Shellac', 'Box Set', 'Other', 'Unknown')
is_primary_format not null
is_vinyl_format not null
is_cd_format not null
is_cassette_format not null
is_digital_format not null
is_box_set_format not null
each release has at most one is_primary_format = true
```

### 12.4 `release_format_summary`

```text
release_id unique
format_count >= 0
primary_format_group valid
has_vinyl not null
has_cd not null
has_cassette not null
has_digital not null
has_box_set not null
has_vinyl = any clean_release_formats.is_vinyl_format for release_id
has_cd = any clean_release_formats.is_cd_format for release_id
has_cassette = any clean_release_formats.is_cassette_format for release_id
has_digital = any clean_release_formats.is_digital_format for release_id
has_box_set = any clean_release_formats.is_box_set_format for release_id
```

### 12.5 `release_fact`

```text
release_id not null
no duplicate (release_id, style_order)
primary_format_group valid
has_vinyl not null
has_cd not null
has_cassette not null
has_digital not null
has_box_set not null
COUNT(DISTINCT release_id) == COUNT(clean_releases.release_id)
```

### 12.6 `release_artist_bridge`

```text
release_id not null
no duplicate (release_id, artist_order)
each release has at most one is_primary_artist = true
```

### 12.7 `release_label_bridge`

```text
release_id not null
no duplicate (release_id, label_order)
each release has at most one is_primary_label = true
```

---

## 13. Manifest contract

Archivo:

```text
data/manifests/{run_id}.json
```

Contenido mínimo:

```json
{
  "run_id": "2026-04-25T10-30-00",
  "snapshot_id": "discogs-2026-04",
  "source_files": {
    "releases": {
      "path": "data/raw/discogs/discogs-2026-04/releases.xml",
      "size_bytes": 0,
      "checksum": "..."
    },
    "masters": {
      "path": "data/raw/discogs/discogs-2026-04/masters.xml",
      "size_bytes": 0,
      "checksum": "..."
    },
    "artists": {
      "path": "data/raw/discogs/discogs-2026-04/artists.xml",
      "size_bytes": 0,
      "checksum": "..."
    }
  },
  "outputs": {
    "release_fact": {
      "path": "data/analytics/2026-04-25T10-30-00/release_fact.parquet",
      "row_count": 0,
      "distinct_release_count": 0
    },
    "release_format_summary": {
      "path": "data/clean/2026-04-25T10-30-00/release_format_summary.parquet",
      "row_count": 0
    }
  },
  "quality_checks": {
    "status": "passed",
    "warnings": []
  }
}
```

---

## 14. Estructura de proyecto sugerida

```text
etl/
  configs/
    base.yml

  src/
    discogs_etl/
      __init__.py

      cli.py

      pipeline/
        runner.py
        context.py
        manifest.py

      steps/
        init_run.py
        prepare_sources.py
        parse_releases.py
        parse_masters.py
        parse_artists.py
        normalize_releases.py
        normalize_release_entities.py
        build_release_format_summary.py
        build_release_fact.py
        publish_duckdb.py
        quality_checks.py
        finalize_manifest.py

      parsers/
        releases_parser.py
        masters_parser.py
        artists_parser.py

      transforms/
        date_normalization.py
        format_normalization.py
        text_normalization.py

      io/
        parquet_writer.py
        duckdb_publisher.py
        file_utils.py

      quality/
        checks.py
        report.py

  tests/
    unit/
      test_date_normalization.py
      test_format_normalization.py
      test_release_fact_builder.py
    integration/
      test_sample_releases_pipeline.py

data/
  raw/
  staging/
  clean/
  analytics/
  published/
    duckdb/
  manifests/
  logs/
```

---

## 15. CLI esperado

Mínimo:

```bash
python -m discogs_etl.cli run --config etl/configs/base.yml
```

Steps individuales:

```bash
python -m discogs_etl.cli step prepare-sources --config etl/configs/base.yml
python -m discogs_etl.cli step parse-releases --config etl/configs/base.yml
python -m discogs_etl.cli step normalize-releases --config etl/configs/base.yml
python -m discogs_etl.cli step build-release-fact --config etl/configs/base.yml
python -m discogs_etl.cli step publish-duckdb --config etl/configs/base.yml
python -m discogs_etl.cli step quality-checks --config etl/configs/base.yml
```

Flags útiles:

```bash
--run-id
--snapshot-id
--limit-releases
--force
--skip-existing
```

`--limit-releases` es importante para testear rápido con samples.

---

## 16. Implementación incremental sugerida

### Fase 1 — Minimal vertical slice

Objetivo: correr de XML sample a DuckDB con `release_fact`.

Tareas:

1. crear estructura del proyecto;
2. implementar config;
3. implementar parser streaming de releases;
4. generar staging mínimo:
   - releases
   - artists
   - labels
   - formats
   - format descriptions
   - genres
   - styles
   - tracks
5. normalizar releases;
6. normalizar formatos;
7. construir `release_format_summary`;
8. construir `release_fact`;
9. publicar DuckDB;
10. correr checks mínimos.

Done:

```text
Dado un sample XML, el pipeline genera:
- release_fact.parquet
- release_artist_bridge.parquet
- release_label_bridge.parquet
- discogs.duckdb
- release_unique_view
```

---

### Fase 2 — Robustez

Objetivo: soportar más variaciones reales del XML.

Tareas:

- manejar campos faltantes;
- manejar releases sin styles;
- manejar releases sin formats;
- manejar fechas inválidas;
- agregar manifest real;
- agregar logs por step;
- agregar batch writing.

---

### Fase 3 — Dataset grande

Objetivo: correr contra XML grande.

Tareas:

- parseo streaming real con limpieza de memoria;
- escritura incremental a parquet;
- control de memoria;
- progress logs;
- checks de row counts;
- `--limit-releases` para dry-runs;
- benchmark simple.

---

### Fase 4 — Masters / Artists

Objetivo: expandir sin romper v1.

Tareas:

- parsear `masters.xml`;
- parsear `artists.xml`;
- crear `clean_masters`;
- crear `clean_artists`;
- diseñar `master_fact`;
- documentar joins futuros.

---

### Fase 5 — Downloader Discogs

Objetivo: automatizar source acquisition.

Tareas:

- descargar dumps;
- guardar en raw;
- verificar checksum si Discogs lo provee;
- descomprimir;
- registrar snapshot.

---

## 17. Non-goals v1

No implementar en v1:

- análisis exacto multi-género;
- `master_fact`;
- `artist_dim` completo;
- parsing completo de videos, companies, identifiers y extraartists;
- RAG;
- descarga automática desde Discogs;
- ejecución del ETL en AWS;
- optimización avanzada de particionamiento;
- dashboards;
- UI.

---

## 18. Áreas de trabajo futuro

### 18.1 `master_fact`

Objetivo:

```text
Analítica a nivel obra/master, no release físico.
```

Queries futuras:

- “Which works have the most versions?”
- “Top genres by unique works”
- “Compare releases vs unique masters by decade”

---

### 18.2 `release_genre_bridge`

Objetivo:

```text
Soportar análisis multi-género exacto.
```

Motivo:

`release_fact` usa `primary_genre`, lo cual es intencionalmente simple.

---

### 18.3 `artist_dim`

Objetivo:

```text
Enriquecer análisis por artista.
```

Columnas potenciales:

```text
artist_id
artist_name
realname
alias_count
group_count
member_count
```

Evitar inicialmente:

```text
profile
```

Motivo:

Es texto largo, ruidoso y poco útil para analytics tabular v1.

---

### 18.4 `company_bridge`

Objetivo:

```text
Analizar Pressed By, Recorded At, Mastered At, Distributed By, etc.
```

Potencial:

- análisis de plantas de prensado;
- estudios de mastering;
- evolución por país/compañía.

---

## 19. Relación con el agente final

El ETL no es el agente, pero define su capa de datos.

Contrato esperado para el agente:

- El agente consulta DuckDB.
- El agente genera Python con SQL embebido.
- El SQL debe consultar preferentemente:
  - `release_unique_view` para conteos de releases;
  - `release_fact` para análisis por style;
  - `release_artist_bridge` para análisis multi-artista;
  - `release_label_bridge` para análisis multi-label.
- El resultado SQL se convierte a pandas.
- pandas/plotly genera el gráfico.

Ejemplo esperado de código generado:

```python
sql = """
SELECT decade, COUNT(DISTINCT release_id) AS releases
FROM release_fact
WHERE style = 'Techno' AND decade IS NOT NULL
GROUP BY decade
ORDER BY decade
"""
df = con.execute(sql).df()
fig = px.line(df, x="decade", y="releases")
```

Regla crítica:

```text
No usar COUNT(*) sobre release_fact para contar releases.
Usar COUNT(DISTINCT release_id) o release_unique_view.
```

---

## 20. Acceptance criteria del ETL

### Functional

- Puede leer un XML sample de releases.
- Genera staging parquet.
- Genera clean parquet.
- Genera `release_format_summary`.
- Genera `release_fact`.
- Genera `release_artist_bridge`.
- Genera `release_label_bridge`.
- Genera DuckDB con tablas publicadas.
- Genera `release_unique_view`.
- Genera manifest del run.

### Data correctness

- No pierde releases al explotar styles.
- Releases sin style siguen apareciendo en `release_fact`.
- Fechas parciales se normalizan correctamente.
- Formatos se clasifican correctamente.
- `has_*` se deriva a nivel release, no format.
- `primary_format_group` se deriva del primer format.
- `release_fact` no se multiplica por formatos.

### Operational

- Corre desde CLI.
- Permite usar sample pequeño.
- Loguea progreso.
- Es re-ejecutable con `run_id`.
- No carga el XML completo en memoria.

### Quality

- Ejecuta checks mínimos.
- Falla si hay errores críticos.
- Reporta warnings en manifest.

---

## 21. Resumen ejecutivo para pasarle al agente de código

Implementar un ETL offline para Discogs con arquitectura por capas. El input inicial será XML local descomprimido. El pipeline debe parsear releases XML en streaming hacia staging parquet, normalizar datos a clean parquet, construir una tabla analítica `release_fact` con grano `release x style`, dos tablas auxiliares (`release_artist_bridge`, `release_label_bridge`) y publicar todo en DuckDB. Debe existir una tabla intermedia `release_format_summary` que resume formatos por release. Los flags a nivel format se llaman `is_*_format`; los flags a nivel release se llaman `has_*`. El agente final consultará DuckDB, no XML ni staging. La v1 se enfoca en releases; masters y artists quedan como trabajo futuro extensible.
