# PlanParser - TODO & Roadmap

> **Obiettivo Finale**: Ricevere una planimetria (PDF/DWG/immagine) e produrre una comprensione completa dello spazio per generare automaticamente progetti HVAC.

---

## 📊 Stato Attuale

### ✅ Funzionante
- [x] Caricamento PDF e rendering ad alta risoluzione
- [x] Rilevamento rettangolo principale della planimetria
- [x] OCR per trovare etichette testuali (nomi stanze)
- [x] Matching fuzzy per classificare le stanze (bagno, camera, cucina, etc.)
- [x] Parametro `--source-type` per specificare tipo di input
- [x] Detection scala con fallback a prompt utente (`--scale`, `--noscale`)
- [x] Detection orientamento/bussola con fallback (`--compass`, `--nocompass`)
- [x] Output JSON strutturato

### ❌ Cosa Produce Oggi (Limitato)
```json
{
  "floors": [{
    "rooms": [{
      "label": "bagno",
      "bbox": [548, 180, 31, 10],  // ← Solo il bbox del TESTO, non della stanza!
      "confidence": 1.0
    }]
  }]
}
```

**Problema**: Il `bbox` è il rettangolo attorno alla parola "bagno", NON l'area effettiva della stanza.

---

## 🎯 Cosa Serve per HVAC

Per progettare un impianto HVAC servono queste informazioni:

| Dato | Necessità | Stato |
|------|-----------|-------|
| Area stanze in m² | 🔴 Critico | ❌ Manca |
| Forma reale stanze (poligoni) | 🔴 Critico | ❌ Manca |
| Posizione/geometria muri | 🔴 Critico | ❌ Manca |
| Spessore muri | 🟡 Importante | ❌ Manca |
| Porte (posizione, dimensioni) | 🔴 Critico | ❌ Manca |
| Finestre (posizione, dimensioni) | 🔴 Critico | ❌ Manca |
| Connessioni tra stanze (grafo) | 🟡 Importante | ❌ Manca |
| Zone funzionali (giorno/notte/servizi) | 🟡 Importante | ❌ Manca |
| Altezza soffitti | 🟡 Importante | ❌ Manca |
| Scala metrica | 🟢 Utile | ✅ OK (con prompt) |
| Orientamento (N/S/E/W) | 🟢 Utile | ✅ OK (con prompt) |
| Volume stanze | 🟡 Importante | ❌ Deriva da area + altezza |

---

## 📋 Roadmap per Fasi

### Fase 1: Estrazione Geometrica (PRIORITÀ MASSIMA)
> Senza geometria non possiamo calcolare nulla

- [x] **1.1 Estrazione segmenti/linee** ✅ FATTO
  - [x] Implementato `extraction/line_extraction.py`
  - [x] Hough Transform per linee rette
  - [x] Clustering e merge linee simili
  - [x] Comando CLI `extract-lines` per debug
  - [x] Visualizzazione con color coding (H=verde, V=blu, D=rosso)
  - [ ] Supporto per linee da PDF vettoriale (più preciso) - TODO

- [ ] **1.2 Rilevamento muri**
  - [ ] Implementare `wall_detection.py`
  - [ ] Identificare segmenti paralleli ravvicinati → muro
  - [ ] Calcolare spessore muri
  - [ ] Gestire intersezioni (angoli)

- [ ] **1.3 Costruzione poligoni stanza**
  - [ ] Implementare `room_polygon.py`
  - [ ] Algoritmo per trovare cicli chiusi nel grafo dei segmenti
  - [ ] Associare etichette OCR ai poligoni (testo dentro quale poligono?)
  - [ ] Calcolare area in pixel → convertire in m² usando scala

### Fase 2: Rilevamento Aperture
> Porte e finestre sono interruzioni nei muri

- [ ] **2.1 Rilevamento porte**
  - [ ] Implementare `door_detection.py`
  - [ ] Cercare gap nei muri
  - [ ] Riconoscere simboli porta (arco di apertura)
  - [ ] Classificare tipo porta (battente, scorrevole)

- [ ] **2.2 Rilevamento finestre**
  - [ ] Implementare `window_detection.py`
  - [ ] Cercare pattern tipici finestra sui muri esterni
  - [ ] Stimare dimensioni

### Fase 3: Topologia e Grafo
> Come sono connesse le stanze?

- [ ] **3.1 Grafo planare**
  - [ ] Implementare `topology.py`
  - [ ] Nodi = stanze (centroidi poligoni)
  - [ ] Archi = porte/aperture tra stanze
  - [ ] Calcolare adiacenze

- [ ] **3.2 Zonizzazione automatica**
  - [ ] Classificare zone: giorno, notte, servizi, distribuzione
  - [ ] Identificare percorsi di circolazione
  - [ ] Riconoscere pattern comuni (corridoio centrale, etc.)

### Fase 4: Supporto Multi-formato
> Il cliente può portare qualsiasi formato

- [ ] **4.1 DWG/DXF parsing**
  - [ ] Usare libreria ezdxf o simile
  - [ ] Estrarre entità native (linee, polilinee, testi)
  - [ ] Molto più preciso del parsing immagine

- [ ] **4.2 Miglioramento parsing immagine**
  - [ ] Gestire scan/foto (più rumore)
  - [ ] Correzione prospettiva
  - [ ] Deskewing avanzato

### Fase 5: Output per HVAC
> Produrre dati pronti per Plan2HVAC

- [ ] **5.1 Output strutturato completo**
  ```json
  {
    "scale": {"ratio": 100, "pixels_per_meter": 28.35},
    "orientation": {"north_angle": 0},
    "floors": [{
      "rooms": [{
        "label": "Bagno",
        "polygon": [[x1,y1], [x2,y2], ...],
        "area_m2": 4.5,
        "perimeter_m": 8.5,
        "adjacent_rooms": ["Corridoio", "Camera"],
        "doors": [{"to": "Corridoio", "width_m": 0.8}],
        "windows": [{"wall": "N", "width_m": 1.2, "height_m": 1.0}]
      }]
    }],
    "walls": [{
      "start": [x1, y1],
      "end": [x2, y2],
      "thickness_m": 0.3,
      "type": "external|internal"
    }]
  }
  ```

- [ ] **5.2 Calcoli derivati**
  - [ ] Volume stanze (area × altezza)
  - [ ] Superfici disperdenti (muri esterni)
  - [ ] Orientamento pareti (per esposizione solare)

---

## 🔧 Prossimi Step Immediati

1. **Creare `line_extraction.py`** - Estrarre tutti i segmenti dall'immagine
2. **Testare su scheda catastale** - Vedere quanti segmenti trova
3. **Visualizzare** - Debug image con segmenti trovati
4. **Iterare** - Affinare parametri fino a rilevare i muri

---

## 📁 Struttura Proposta per Nuovi Moduli

```
PlanParser/
├── extraction/           # Estrazione primitive geometriche
│   ├── __init__.py
│   ├── line_extraction.py
│   ├── pdf_vector.py     # Estrazione da PDF vettoriale
│   └── image_lines.py    # Estrazione da immagine raster
│
├── detection/            # Rilevamento entità semantiche
│   ├── __init__.py
│   ├── wall_detection.py
│   ├── door_detection.py
│   ├── window_detection.py
│   └── room_polygon.py
│
├── topology/             # Struttura relazionale
│   ├── __init__.py
│   ├── graph.py          # Grafo planare
│   └── zones.py          # Zonizzazione
│
└── output/               # Formati di output
    ├── __init__.py
    ├── hvac_ready.py     # Output per Plan2HVAC
    └── visualizer.py     # Visualizzazione debug
```

---

## 📝 Note

- La **teoria** in `theory/` è solida: partire da primitive → relazioni → entità semantiche
- Il codice attuale salta direttamente a OCR senza estrarre la geometria
- Per PDF vettoriali (schede catastali) le linee sono già definite, molto più facile
- Per immagini/scan serve computer vision più pesante

---

*Ultimo aggiornamento: 2026-01-08*
