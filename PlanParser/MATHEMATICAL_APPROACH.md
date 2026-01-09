# Approccio Matematico al Riconoscimento Planimetrico

**Il problema:** Estrarre conoscenza strutturata da una planimetria non è un problema di "image processing" ma un problema di **topologia computazionale** e **geometria algebrica**.

---

## 🎯 Riformulazione del Problema

### Cosa NON è il problema:
- NON è "trovare rettangoli in un'immagine"
- NON è "fare OCR e sperare"
- NON è "machine learning su pixel"

### Cosa È il problema:
> **Data una suddivisione planare del piano 2D in regioni delimitate da segmenti, ricostruire la struttura topologica e semantica dello spazio.**

Questo è un problema classico di **geometria computazionale** con una teoria matematica ricca.

---

## 📐 Fondamenti Matematici

### 1. Suddivisione Planare (Planar Subdivision)

Una planimetria è matematicamente una **suddivisione planare**: una partizione del piano in:
- **Vertici (V)**: punti di intersezione delle pareti
- **Archi (E)**: segmenti di parete tra due vertici
- **Facce (F)**: regioni chiuse (stanze) + la faccia esterna infinita

**Formula di Eulero** (invariante topologico):
$$V - E + F = 2$$

Questo ci dà un **vincolo di validazione**: se dopo l'estrazione $V - E + F \neq 2$, c'è un errore.

---

### 2. Doubly Connected Edge List (DCEL)

La struttura dati corretta per rappresentare una suddivisione planare è la **DCEL** (o Half-Edge Data Structure).

```
Per ogni half-edge e:
    - origin(e): vertice di partenza
    - twin(e): half-edge opposto (stessa linea, direzione opposta)
    - face(e): faccia alla sinistra di e
    - next(e): prossimo half-edge lungo il bordo della faccia
    - prev(e): half-edge precedente
```

**Proprietà fondamentale**: Seguendo `next` si percorre esattamente il bordo di una stanza.

```
Stanza = ciclo di half-edges: e → next(e) → next(next(e)) → ... → e
```

---

### 3. Grafo Duale

Il **grafo duale** $G^*$ di una suddivisione planare:
- Ogni faccia (stanza) diventa un nodo
- Due nodi sono connessi se le stanze condividono un arco (parete)

```
G = (Vertici pareti, Archi pareti)
G* = (Stanze, Connessioni tra stanze)
```

**Il grafo duale È la topologia che vogliamo estrarre.**

Per l'HVAC, ci interessa $G^*$ (quali stanze sono adiacenti) più che $G$ (dove sono le pareti esattamente).

---

### 4. Teorema di Jordan

> Ogni curva chiusa semplice nel piano divide il piano in esattamente due regioni: interno ed esterno.

**Applicazione:** Una sequenza chiusa di segmenti di parete definisce univocamente una stanza. Il problema è trovare tutte le curve chiuse minimali (cicli base).

---

## 🔬 Algoritmo Formale

### Passo 1: Da Immagine a Grafo Planare

**Input:** Immagine binaria (pixel bianchi = pareti, neri = spazio)

**Output:** Grafo planare $G = (V, E)$

```
1. Scheletrizzazione (thinning): riduci pareti a linee di 1px
2. Rilevamento vertici: pixel con ≥3 vicini = nodo
3. Tracciamento archi: segui pixel tra due vertici = arco
4. Costruisci DCEL
```

**Teorema:** Lo scheletro di una regione 2D connessa è un grafo planare.

---

### Passo 2: Enumerazione delle Facce (Stanze)

**Problema:** Dato un grafo planare embedded, trova tutte le facce.

**Algoritmo (ben noto in letteratura):**

```python
def trova_facce(DCEL):
    facce = []
    visitati = set()
    
    for e in DCEL.half_edges:
        if e not in visitati:
            # Percorri il ciclo
            ciclo = []
            corrente = e
            while corrente not in ciclo:
                ciclo.append(corrente)
                visitati.add(corrente)
                corrente = next(corrente)
            
            if len(ciclo) >= 3:  # almeno un triangolo
                facce.append(Faccia(ciclo))
    
    return facce
```

**Complessità:** $O(V + E)$ - lineare!

---

### Passo 3: Classificazione Facce

Non tutte le facce sono stanze:
- La faccia esterna (unbounded) non è una stanza
- Facce troppo piccole sono artefatti
- Facce "dentro" altre facce possono essere pilastri

**Criteri formali:**

| Criterio | Formula |
|----------|---------|
| Faccia esterna | Area = ∞ (o > soglia) |
| Artefatto | Area < $\epsilon$ (es. 0.5 m²) |
| Stanza valida | $\epsilon <$ Area $< A_{max}$ |

**Area di un poligono (formula di Gauss):**
$$A = \frac{1}{2} \left| \sum_{i=0}^{n-1} (x_i y_{i+1} - x_{i+1} y_i) \right|$$

---

### Passo 4: Costruzione Grafo Duale

```python
def costruisci_duale(facce, DCEL):
    G_duale = Graph()
    
    for f in facce:
        G_duale.add_node(f.id)
    
    for e in DCEL.half_edges:
        f1 = face(e)
        f2 = face(twin(e))
        if f1 != f2 and f1.is_stanza and f2.is_stanza:
            G_duale.add_edge(f1.id, f2.id, wall=e)
    
    return G_duale
```

---

## 🚪 Il Problema delle Porte

Le porte creano **discontinuità** nel grafo delle pareti. Matematicamente:

> Una porta è un arco "virtuale" che **completa** un ciclo altrimenti aperto.

**Approccio formale:**

1. Trova tutti i vertici di grado 1 (dead ends) → candidati porte
2. Per ogni coppia di dead-ends vicini (< 1.2m):
   - Aggiungi arco virtuale "porta"
   - Questo chiude il ciclo → crea la faccia/stanza
3. Marca l'arco come `tipo=porta`

```
Prima:    A -------- B (dead end)
                           gap
          C -------- D (dead end)

Dopo:     A -------- B
                     |  ← arco virtuale (porta)
          C -------- D
```

---

## 📊 Complessità e Garanzie

| Operazione | Complessità | Garanzia |
|------------|-------------|----------|
| Scheletrizzazione | $O(n)$ dove n = pixel | Preserva topologia |
| Costruzione DCEL | $O(E \log E)$ | Correttezza by construction |
| Enumerazione facce | $O(V + E)$ | Trova TUTTE le facce |
| Grafo duale | $O(F)$ | Isomorfo alla topologia reale |

**Invariante di validazione:**
$$V - E + F = 2$$

Se questa formula non vale dopo l'estrazione, c'è un bug.

---

## 🧮 Vantaggi dell'Approccio Matematico

1. **Completezza**: L'algoritmo trova TUTTE le stanze, non "quelle che riesce a vedere"

2. **Correttezza**: Formula di Eulero come invariante di validazione

3. **Determinismo**: Nessuna euristica probabilistica, risultato riproducibile

4. **Efficienza**: Complessità lineare o quasi-lineare

5. **Robustezza**: Funziona su qualsiasi suddivisione planare valida

6. **Formalizzazione**: Possiamo DIMOSTRARE proprietà dell'algoritmo

---

## ⚠️ Dove Serve Ancora Euristica

La matematica risolve il problema **dato un grafo planare pulito**. Il problema resta:

| Fase | Natura |
|------|--------|
| Immagine → Linee | Signal processing (Hough, edge detection) |
| Linee → Grafo pulito | Geometria + euristiche (merge linee vicine) |
| Grafo → DCEL | **Matematica pura** ✓ |
| DCEL → Facce | **Matematica pura** ✓ |
| Facce → Stanze | **Matematica + soglie** |
| OCR label matching | NLP / fuzzy matching |
| Semantica (cucina vs bagno) | Classificazione / regole |

---

## 📚 Librerie Consigliate

```python
# Geometria computazionale con garanzie formali
from shapely.geometry import Polygon, LineString
from shapely.ops import polygonize, unary_union

# Grafi con algoritmi certificati
import networkx as nx

# DCEL implementation
# Opzione 1: Implementare da zero (200-300 righe)
# Opzione 2: Usare CGAL via Python bindings (scikit-geometry)
```

---

## 🎯 Proposta di Implementazione

### Fase 1: Core Matematico (1-2 settimane)
```python
# dcel.py
class HalfEdge:
    origin: Vertex
    twin: HalfEdge
    face: Face
    next: HalfEdge
    prev: HalfEdge

class DCEL:
    def from_segments(segments: List[Segment]) -> DCEL
    def enumerate_faces() -> List[Face]
    def dual_graph() -> nx.Graph
    def validate() -> bool  # V - E + F == 2
```

### Fase 2: Bridge Immagine → Grafo (1-2 settimane)
```python
# extraction.py
def image_to_skeleton(binary_image) -> np.array
def skeleton_to_graph(skeleton) -> nx.Graph
def graph_to_dcel(graph) -> DCEL
```

### Fase 3: Semantica (1 settimana)
```python
# semantic.py
def classify_faces(faces, ocr_labels) -> List[Room]
def detect_doors(dcel) -> List[Door]
def build_knowledge_model(rooms, doors) -> KnowledgeModel
```

---

## 📖 Riferimenti Accademici

1. **de Berg et al.** - "Computational Geometry: Algorithms and Applications" (Capitolo 2: DCEL)

2. **O'Rourke** - "Computational Geometry in C" (Polygon algorithms)

3. **Preparata & Shamos** - "Computational Geometry: An Introduction"

4. **Edelsbrunner** - "Geometry and Topology for Mesh Generation"

Per floor plan specifico:
5. **"Automatic Room Detection in Floor Plans"** - Ricerca su IEEE/ACM

---

## ✅ Conclusione

> **Il problema non è "difficile" - è MAL POSTO se affrontato con brute force.**

Con il framework matematico corretto (suddivisioni planari, DCEL, grafi duali):
- L'algoritmo è **lineare** in complessità
- Il risultato è **garantito** corretto
- La topologia è **formalmente estratta**

La difficoltà si sposta sulla qualità dell'input (immagine → grafo pulito), ma il core dell'estrazione diventa un problema **risolto** dalla teoria.
