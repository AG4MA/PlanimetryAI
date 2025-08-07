# PlanParser

**PlanParser** è il modulo per il parsing e l'analisi di planimetrie in formato PDF, DWG e DXF.

## 🎯 Obiettivo Principale

Riconoscere automaticamente il **rettangolo più grande** presente in un PDF di planimetria e evidenziarne il bordo con un colore distintivo.

## 📁 Struttura del Progetto

```
PlanParser/
├── data/                          # File PDF di esempio
│   └── scheda_catastale.pdf
├── detect_largest_rectangle.py    # Algoritmo originale
├── improved_rectangle_detector.py # Algoritmo migliorato
├── expand_from_center.py          # Algoritmo alternativo
├── pdf_parser.py                  # Parser PDF base
├── geometry.py                    # Utilità geometriche
├── test_simple.py                 # Test delle dipendenze
├── requirements.txt               # Dipendenze Python
└── README.md                     # Questo file
```

## 🚀 Installazione

1. **Crea l'ambiente virtuale:**
   ```bash
   python -m venv PlanParser_env
   ```

2. **Attiva l'ambiente:**
   ```bash
   # Windows
   .\PlanParser_env\Scripts\activate
   
   # Linux/Mac
   source PlanParser_env/bin/activate
   ```

3. **Installa le dipendenze:**
   ```bash
   pip install -r requirements.txt
   ```

## 🧪 Test

Verifica che tutto funzioni:
```bash
python test_simple.py
```

## 🔍 Utilizzo

### Rilevamento Rettangolo Migliorato
```bash
python improved_rectangle_detector.py
```

### Rilevamento Originale
```bash
python detect_largest_rectangle.py
```

## 📊 Output

Il programma genera:
- **debug_output/01_original.png** - Immagine originale del PDF
- **debug_output/02_processed.png** - Immagine dopo preprocessing
- **debug_output/03_result.png** - Risultato finale con rettangolo evidenziato

## 🎨 Algoritmi Implementati

### 1. Algoritmo Migliorato (`improved_rectangle_detector.py`)
- **Preprocessing avanzato** con threshold adattivo
- **Filtri morfologici** per pulire l'immagine
- **Rilevamento contorni** con approssimazione poligonale
- **Filtri di qualità** (area minima, aspect ratio)
- **Debug completo** con immagini intermedie

### 2. Algoritmo Originale (`detect_largest_rectangle.py`)
- Rilevamento base con Canny edge detection
- Approssimazione semplice dei contorni

### 3. Algoritmo Espansione (`expand_from_center.py`)
- Rilevamento linee con Hough transform
- Espansione dal centro verso i bordi

## 🔧 Dipendenze

- **opencv-python** - Computer vision e rilevamento contorni
- **PyMuPDF** - Lettura e rendering PDF
- **Pillow** - Manipolazione immagini
- **numpy** - Calcoli numerici

## 📈 Metriche di Qualità

L'algoritmo migliorato filtra i rettangoli basandosi su:
- **Area minima**: 1000 pixel²
- **Aspect ratio**: < 10 (evita rettangoli troppo stretti)
- **Convessità**: Solo poligoni convessi
- **Numero vertici**: Esattamente 4 vertici

## 🐛 Debug

Se il rilevamento non funziona:
1. Controlla le immagini in `debug_output/`
2. Regola le soglie in `detect_rectangles()`
3. Prova diversi valori di zoom in `render_pdf_to_image()`
