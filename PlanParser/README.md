# PlanParser

**PlanParser** è il modulo per il parsing e l'analisi di planimetrie in formato PDF, DWG e DXF.

## 🎯 Obiettivo Principale

Riconoscere automaticamente **piani** e **stanze** presenti in un PDF di planimetria, estraendo dati strutturati in formato JSON.

## ✅ Features

- **PDF Parsing**: Rendering ad alta risoluzione dei PDF
- **Floor Detection**: Rilevamento automatico delle etichette dei piani (Piano Terra, Primo Piano, etc.)
- **Room Detection**: Riconoscimento delle stanze (bagno, camera, cucina, soggiorno, etc.)
- **Multi-OCR**: Supporto per Tesseract e EasyOCR con fallback automatico
- **Structured Output**: Output JSON strutturato con coordinate e confidenza
- **Debug Images**: Generazione di immagini di debug per ogni fase

## 📁 Struttura del Progetto

```
PlanParser/
├── data/                    # File PDF di esempio
├── debug_image/             # Output immagini di debug
├── planimetry_output/       # Output JSON risultati
├── __init__.py              # Package exports
├── __main__.py              # CLI entry point
├── cli.py                   # Command-line interface
├── config.py                # Configurazione centralizzata
├── parser.py                # Pipeline principale
├── pdf_reader.py            # Lettura PDF
├── image_processing.py      # Computer vision utilities
├── ocr_engine.py            # Motori OCR (Tesseract/EasyOCR)
├── floor_detection.py       # Rilevamento piani
├── room_detection.py        # Rilevamento stanze
├── geometry.py              # Entità geometriche
└── requirements.txt         # Dipendenze Python
```

## 🚀 Installazione

1. **Crea e attiva l'ambiente virtuale:**
   ```bash
   python -m venv .venv
   
   # Windows
   .\.venv\Scripts\Activate.ps1
   
   # Linux/Mac
   source .venv/bin/activate
   ```

2. **Installa le dipendenze:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Opzionale - Installa EasyOCR per OCR senza dipendenze esterne:**
   ```bash
   pip install easyocr
   ```

## 🔍 Utilizzo

### CLI - Parsing di un PDF

```bash
# Parsing base
python -m PlanParser parse --pdf data/scheda_catastale.pdf

# Con output verbose
python -m PlanParser parse --pdf data/scheda_catastale.pdf --verbose

# Specifica directory di output
python -m PlanParser parse --pdf data/scheda_catastale.pdf -o ./results/

# Output JSON diretto
python -m PlanParser parse --pdf data/scheda_catastale.pdf --json
```

### Python API

```python
from PlanParser import parse_planimetry, PlanParser, PlanParserConfig

# Modo semplice
result = parse_planimetry("data/scheda_catastale.pdf")
print(f"Floors: {len(result.floors)}")

for floor in result.floors:
    print(f"\n{floor.floor_label}:")
    for room in floor.rooms:
        print(f"  - {room['label']}: {room['bbox']}")

# Con configurazione custom
config = PlanParserConfig()
config.pdf_zoom = 3.0  # Risoluzione più alta

parser = PlanParser(config)
result = parser.parse("data/scheda_catastale.pdf", floor_anchor="down")

# Esporta in JSON
print(result.to_json())
```

### Info su un PDF

```bash
python -m PlanParser info data/scheda_catastale.pdf
```

## 📊 Output

Il programma genera:

### Debug Images (in `debug_image/`)
- `01_original.png` - Immagine originale del PDF
- `02_rectangle.png` - Rettangolo principale evidenziato
- `03_base.png` - Immagine ritagliata
- `04_floors.png` - Linee di separazione piani
- `05_section_N_*.png` - Sezioni per piano
- `06_section_N_*_rooms.png` - Stanze rilevate per piano

### Risultato JSON (in `planimetry_output/result.json`)
```json
{
  "success": true,
  "source_file": "data/scheda_catastale.pdf",
  "floors": [
    {
      "floor_label": "Piano Terra",
      "floor_number": 0,
      "rooms": [
        {
          "label": "soggiorno",
          "bbox": [100, 200, 150, 80],
          "center": [175, 240],
          "confidence": 0.95
        }
      ]
    }
  ]
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
