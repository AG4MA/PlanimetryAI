# PlanParser

**PlanParser** è il modulo core della suite PlanimetryAI. Estrae un **Digital Twin** strutturato da planimetrie PDF, DWG e DXF.

## 🎯 Mission

PlanParser è la **Single Source of Truth** per i progetti downstream:
- **Plan2HVAC**: genera layout HVAC automaticamente
- **PlanNL**: query in linguaggio naturale sulla planimetria

I progetti downstream **non** ri-analizzano i file originali. Consumano solo l'output strutturato di PlanParser.

## 🏗️ Output: Digital Twin

L'output principale è un **DigitalTwin** che contiene:

```
DigitalTwin
├── Building
│   ├── floors: List[Floor]
│   ├── scale: Scale (1:100, pixels_per_meter)
│   └── compass: Compass (north_angle)
│
└── Floor
    ├── rooms: List[Room]           # Spazi con poligono, tipo, area
    ├── walls: List[Wall]           # Muri con spessore, tipo
    ├── doors: List[Door]           # Porte con direzione apertura
    ├── windows: List[Window]       # Finestre
    └── topology: TopologyGraph     # Grafo di adiacenza tra stanze
```

## 📁 Architettura (Clean Architecture)

```
PlanParser/
├── domain/                     # 🧠 CORE - Nessuna dipendenza esterna
│   ├── models/
│   │   ├── primitives.py       # Point2D, LineSegment, Polygon
│   │   ├── elements.py         # Wall, Door, Window
│   │   ├── spaces.py           # Room, RoomType, Stairwell
│   │   ├── building.py         # Floor, Building
│   │   └── digital_twin.py     # DigitalTwin (OUTPUT PRINCIPALE)
│   ├── value_objects/
│   │   ├── measurements.py     # Scale, Length, Area (con unità)
│   │   ├── orientation.py      # Compass, CardinalDirection
│   │   └── topology.py         # Adjacency, TopologyGraph
│   ├── protocols.py            # Interfacce astratte
│   └── config.py               # Configurazione
│
├── extraction/                 # 🔍 Pipeline di estrazione
│   ├── geometry/               # Line detection, polygon extraction
│   ├── floor/                  # Floor label detection
│   ├── room/                   # Room detection
│   ├── scale/                  # Scale detection
│   ├── semantic/               # Door/window/wall classification
│   └── topology/               # Adjacency graph construction
│
├── application/                # 🎯 Use cases e orchestrazione
│   ├── use_cases/
│   └── dto/
│
├── infrastructure/             # 🔌 Implementazioni concrete
│   ├── ocr/                    # Tesseract, EasyOCR
│   ├── readers/                # PDF, DWG, image readers
│   └── serializers/            # JSON output
│
├── tests/                      # ✅ Test suite
├── experimental/               # 🧪 Script sperimentali
└── docs/                       # 📚 Documentazione
```

## 🚀 Installazione

```bash
# 1. Crea ambiente virtuale
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1
# Linux/Mac
source .venv/bin/activate

# 2. Installa dipendenze
pip install -r requirements.txt
```

## 🔍 Utilizzo

### Python API (Nuovo - DigitalTwin)

```python
from PlanParser import DigitalTwin, Building, Floor, Room, RoomType

# Parsing (TODO: implementazione completa)
# twin = parse_planimetry("data/scheda_catastale.pdf")

# Esempio di struttura DigitalTwin
from PlanParser.domain.models import (
    DigitalTwin, Building, Floor, Room, RoomType,
    Wall, Door, Window, Point2D, Polygon
)
from PlanParser.domain.value_objects import Scale, Compass, TopologyGraph

# Creare un Room
room = Room(
    id="room_1",
    label="Soggiorno",
    room_type=RoomType.LIVING_ROOM,
    area_sqm=25.5,
    centroid=Point2D(100, 200),
    bbox=(50, 150, 100, 100),
)

print(f"Room: {room.label} ({room.room_type.value})")
print(f"  Habitable: {room.is_habitable}")
print(f"  Wet room: {room.is_wet_room}")

# Query rooms
# bathrooms = twin.query_rooms(room_type=RoomType.BATHROOM)
# wet_rooms = twin.query_rooms(is_wet_room=True)

# Esportare il Digital Twin per downstream
# twin.save_json("output/plan_twin.json")
```

### Downstream: Plan2HVAC

```python
# In Plan2HVAC, consumare il DigitalTwin
import json
from pathlib import Path

# Caricare l'output di PlanParser
data = json.loads(Path("output/plan_twin.json").read_text())

for floor in data["building"]["floors"]:
    for room in floor["rooms"]:
        if room["is_wet_room"]:
            print(f"Plan drainage for: {room['label']}")
        if room["room_type"] == "bedroom":
            print(f"Add radiator to: {room['label']}")
```

### CLI

```bash
# Parsing base
python -m PlanParser parse --pdf data/scheda_catastale.pdf

# Output JSON
python -m PlanParser parse --pdf data/scheda_catastale.pdf --json -o result.json

# Info PDF
python -m PlanParser info data/scheda_catastale.pdf
```

## 📊 Output JSON Schema

```json
{
  "schema_version": "1.0",
  "success": true,
  "metadata": {
    "parser_version": "0.3.0",
    "processed_at": "2026-01-08T15:00:00",
    "source": {"file": "plan.pdf", "type": "pdf"}
  },
  "building": {
    "id": "bld_1",
    "total_floors": 2,
    "total_rooms": 8,
    "scale": "1:100",
    "floors": [
      {
        "id": "floor_0",
        "label": "Piano Terra",
        "floor_number": 0,
        "rooms": [
          {
            "id": "room_1",
            "label": "Soggiorno",
            "room_type": "living_room",
            "area_sqm": 25.5,
            "is_habitable": true,
            "is_wet_room": false,
            "polygon": {"vertices": [...]},
            "adjacent_room_ids": ["room_2", "room_3"]
          }
        ],
        "walls": [...],
        "doors": [...],
        "windows": [...]
      }
    ]
  }
}
```

## 🔧 Dipendenze

### Core
- **opencv-python** - Computer vision e rilevamento contorni
- **PyMuPDF** - Lettura e rendering PDF
- **Pillow** - Manipolazione immagini
- **numpy** - Calcoli numerici

### OCR (almeno uno richiesto)
- **pytesseract** - Wrapper per Tesseract OCR (richiede installazione Tesseract)
- **easyocr** - OCR basato su deep learning (no dipendenze esterne, usa GPU se disponibile)

## 🏠 Stanze Riconosciute

Il parser riconosce le seguenti etichette italiane:

| Categoria | Labels |
|-----------|--------|
| Living | sala, soggiorno, soggiorno-pranzo, pranzo |
| Camere | camera, letto, stanza |
| Servizi | bagno, wc, servizio |
| Cucina | cucina, angolo cottura |
| Corridoi | ingresso, corridoio, disimpegno, dis |
| Storage | ripostiglio, rip, lavanderia |
| Esterni | balcone, terrazzo, loggia, portico, veranda |
| Altro | studio, ufficio, cantina, garage |

## 📐 Piani Riconosciuti

- Piano Terra (PT)
- Primo Piano - Decimo Piano
- Seminterrato, Interrato
- Sottotetto, Mansarda

- **Convessità**: Solo poligoni convessi
- **Numero vertici**: Esattamente 4 vertici

## 🐛 Debug

Se il rilevamento non funziona:
1. Controlla le immagini in `debug_output/`
2. Regola le soglie in `detect_rectangles()`
3. Prova diversi valori di zoom in `render_pdf_to_image()`
