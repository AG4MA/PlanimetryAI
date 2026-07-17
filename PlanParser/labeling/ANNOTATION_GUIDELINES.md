# Linee guida di annotazione atomica

## 1. Principio fondamentale

Annotare ciò che è osservabile nella pagina renderizzata, non ciò che “dovrebbe” esserci. Un segno grafico può ricevere più osservazioni su layer diversi: per esempio primitive `geometry`, un candidato `wall_region` e una relazione `candidate_part_of`. L'annotatore non crea entità canoniche, proprietà progettuali o conformità tecniche.

Ogni osservazione deve:

- usare una coppia `layer/class_id` presente in `taxonomy.v1.json`;
- avere geometria in pixel della pagina completa, dopo la rotazione dichiarata;
- includere un crop di evidenza che contenga l'intera evidenza e un piccolo contesto;
- riportare provenienza e review senza cancellare la storia;
- usare astensione/`unknown_*` quando la classe non è determinabile, senza forzare una label.

## 2. Convenzioni geometriche

| Tipo | Uso | Regola |
|---|---|---|
| `point` | marker puntuale o centro inequivocabile | Un punto sul centro visivo; non usarlo per oggetti estesi. |
| `bbox` | testo, simbolo o regione rettangolare | Rettangolo minimo assiale che include tutti i pixel dell'oggetto. |
| `polyline` | linea aperta, asse o faccia | Vertici sul centro del tratto; aggiungere un vertice a ogni cambio di direzione significativo. |
| `polygon` | area/contorno chiuso | Perimetro sul bordo visibile; almeno 3 punti, senza ripetere obbligatoriamente il primo. |
| `mask` | regione irregolare non rappresentabile fedelmente con pochi vertici | File esterno immutabile con hash; vietato per evitare un lavoro geometrico accurato. |

Coordinate: origine in alto a sinistra; `x` verso destra, `y` verso il basso; valori entro `width_px × height_px`. Non annotare in coordinate del crop. Non convertire in metri: scala e quote sono osservazioni `measurement`.

Occlusione: annotare solo il bordo osservabile. Un completamento inferito è ammesso soltanto come candidato separato e deve essere segnalato negli `attributes`, mai fuso silenziosamente con l'evidenza.

## 3. Unità annotabili per layer

### 3.1 `source_region`

Unità: una regione funzionale della pagina.

| Classe | Geometria preferita | Include / esclude |
|---|---|---|
| `drawing_area` | polygon/bbox | Area contenente il disegno tecnico; esclude cartiglio e note esterne. |
| `drawing_frame` | polyline/polygon | Cornice grafica della tavola, non il bordo fisico della pagina. |
| `title_block` | polygon/bbox | Cartiglio con metadati di tavola. |
| `legend` | polygon/bbox | Legenda simboli/materiali; non singoli simboli. |
| `schedule_table` | polygon/bbox | Abaco/tabella strutturata. |
| `general_notes` | polygon/bbox | Blocco di note generali. |
| `revision_block` | polygon/bbox | Tabella o area revisioni. |
| `image_region` | polygon/bbox | Immagine/foto inserita nella tavola. |
| `unknown_region` | polygon/bbox | Regione chiaramente distinta ma funzione incerta. |

Regola di annidamento: regioni interne possono sovrapporsi a `drawing_area` soltanto se lo sono realmente nella pagina. Collegare con `contains` quando l'inclusione è osservabile.

### 3.2 `geometry`

Unità: una primitiva grafica continua osservabile, indipendente dal significato.

- `line_segment`: tratto rettilineo tra due interruzioni/cambi direzione.
- `polyline`: sequenza continua di tratti con vertici osservabili.
- `arc`, `circle`, `ellipse`: curva completa o porzione chiaramente riconoscibile; usare polyline se la forma è incerta.
- `polygon_contour`: contorno chiuso; non implica automaticamente stanza o parete.
- `hatch_region`, `filled_region`: area retinata o piena delimitata.
- `point_marker`: punto/croce intenzionale, non rumore.
- `unknown_geometry`: segno geometrico reale non classificabile.

Non duplicare ogni segmento sia come `line_segment` sia come `polyline`, salvo task esplicitamente multi-risoluzione. Linee di testo e artefatti di scansione non sono geometria tecnica.

### 3.3 `text`

Unità: il più piccolo blocco leggibile con funzione uniforme. La trascrizione va in `attributes.transcription`; conservare maiuscole, segni, separatori decimali e simboli così come visibili. Non normalizzare nel valore annotato; un'eventuale forma normalizzata può essere un attributo separato.

- `room_label`: nome/destinazione di un ambiente candidata.
- `dimension_text`: valore associato a una quota.
- `scale_text`: indicazione testuale della scala.
- `level_text`, `elevation_text`: livelli/elevazioni scritti.
- `sheet_title`, `material_note`, `general_note`, `identifier_text` secondo funzione osservabile.
- `unknown_text`: testo leggibile o parzialmente leggibile senza funzione determinabile.

Testo illeggibile: non inventare la trascrizione. Usare `unknown_text`, `attributes.transcription=null`, `attributes.legibility="illegible|partial"` e note sui caratteri certi, se presenti.

### 3.4 `symbol`

Unità: un'istanza completa del simbolo, non i singoli tratti che lo compongono.

Classi: `north_arrow`, `section_marker`, `elevation_marker`, `level_marker`, `door_swing`, `window_marker`, `stair_direction`, `sanitary_fixture`, `electrical_symbol`, `plumbing_symbol`, `hvac_symbol` e `structural_symbol`. Usare `unknown_symbol` se la presenza del simbolo è certa ma il tipo no.

Un simbolo può anche avere primitive `geometry`; collegarle con `candidate_part_of`. Non assegnare funzione impiantistica specifica oltre la classe disponibile.

### 3.5 `architectural_candidate`

Unità: un'aggregazione candidata sostenuta da evidenza grafica. Il suffisso concettuale “candidate” vale per tutte le classi del layer.

| Classe | Geometria preferita | Regola di bordo |
|---|---|---|
| `floor_plan` | polygon/bbox | Ingombro della rappresentazione del piano, non il foglio. |
| `room_region` | polygon | Faccia libera interna osservabile; non attraversare pareti/aperture. |
| `wall_axis` | polyline | Mezzeria candidata del muro. |
| `wall_face` | polyline | Singola faccia visibile del muro. |
| `wall_region` | polygon/mask | Area materiale tra facce osservabili. |
| `door`, `window`, `passage` | bbox/polygon | Intera apertura/simbolo associato, non sola linea d'anta. |
| `stair`, `column`, `beam`, `balcony`, `shaft`, `fixture` | polygon/bbox | Ingombro osservabile dell'elemento candidato. |
| `unknown_architectural` | polygon/bbox | Oggetto architettonico plausibile ma non classificabile. |

Non classificare muro interno/esterno: questa proprietà non è nella tassonomia v1. Non chiudere una `room_region` attraverso zone invisibili senza segnalarne l'inferenza.

### 3.6 `measurement`

Unità: una misura candidata completa, con valore e unità solo se osservabili.

- `linear_dimension`, `angular_dimension`, `drawing_scale`, `elevation_level`, `slope`, `area_value`; usare `unknown_measurement` quando la presenza di una misura è certa ma il tipo non è determinabile.
- Collegare testo e oggetto misurato con `dimensions`; scala alla regione/piano con `references` o `dimensions` secondo il task.
- Attributi consigliati: `raw_text`, `parsed_value`, `unit`, `parse_status` (`exact|ambiguous|unparsed`).
- Non derivare metri dai pixel durante il labeling; eventuali derivazioni deterministiche sono osservazioni con provenance `derived` e riferimenti completi.

## 4. Relazioni annotabili

Creare una relazione soltanto se entrambi gli endpoint esistono e la relazione è osservabile.

| Relazione | Direzione / uso |
|---|---|
| `contains` | contenitore → contenuto; inclusione spaziale chiara. |
| `candidate_part_of` | parte osservata → aggregazione candidata. |
| `touches`, `intersects`, `overlaps` | prima entità → seconda; relazione geometrica osservabile. |
| `parallel_to`, `perpendicular_to`, `collinear_with` | fra primitive/assi con evidenza sufficiente. |
| `labels` | testo → candidato/regione nominata. |
| `dimensions` | misura/testo quota → elemento misurato. |
| `bounds` | geometria/contorno → regione delimitata. |
| `references` | marker/nota → oggetto richiamato. |
| `adjacent_candidate` | candidato → candidato; adiacenza plausibile, non topologia canonica. |

Non creare relazioni transitive per convenienza. Le relazioni simmetriche possono essere rappresentate una sola volta secondo l'ordine stabile degli ID; il benchmark deve adottare la stessa convenzione.

## 5. Attributi minimi consigliati

Lo schema lascia `attributes` aperto, ma il progetto di labeling deve pubblicare un profilo versionato. Per la baseline:

- tutti: `annotation_task_id`, `guideline_version`, `ambiguity_codes` (array);
- testo: `transcription`, `language`, `legibility`;
- candidate: `visible_fraction`, `completion` (`observed|partially_inferred`);
- measurement: `raw_text`, `parsed_value`, `unit`, `parse_status`;
- unknown/astensione: `unknown_reason` o `abstention_reason`.

Non inserire valori tecnici non osservati, nomi di classi alternativi o proprietà del Punto 2.

## 6. Casi ambigui e astensione

Codici baseline:

- `LOW_RESOLUTION`, `BLUR`, `COMPRESSION`, `OCCLUDED`, `CROPPED_BY_PAGE`;
- `OVERPRINT`, `HATCH_INTERFERENCE`, `TEXT_GEOMETRY_COLLISION`;
- `MULTIPLE_PLAUSIBLE_CLASSES`, `BOUNDARY_NOT_VISIBLE`, `SYMBOL_NOT_IN_TAXONOMY`;
- `SCALE_CONFLICT`, `DIMENSION_CONFLICT`, `OUT_OF_DOMAIN`.

Procedura:

1. localizzare l'evidenza con la geometria più onesta possibile;
2. usare la classe specifica solo se sostenuta dalle linee guida;
3. altrimenti usare `unknown_*` del layer corretto;
4. se anche il layer non è affidabile, registrare astensione nel task e non creare una falsa osservazione;
5. per pre-label di modello localizzato ma non classificato, usare `confidence.abstained=true` e motivi;
6. inoltrare a review senior; il professionista interviene solo sui significati tecnici previsti dal piano QA.

## 7. Errori vietati

- annotare dal crop senza riportare le coordinate alla pagina;
- usare il nome della stanza per inventarne il perimetro;
- fondere porta, arco di apertura e varco in un'unica primitiva non tracciata;
- correggere quote incoerenti scegliendo quella “probabile”;
- etichettare rumore/scansione come segno tecnico;
- trasformare candidati P1 in entità canoniche P2;
- accettare un pre-label senza ispezionare evidenza e confini;
- sovrascrivere una review o una versione precedente.
