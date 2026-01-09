# PlanParser - Technical Roadmap

**Goal:** Extract structured knowledge from raw floor plan sources (PDF/DWG/DXF) and produce a machine-readable Knowledge Model.

---

## 🧠 The Core Challenge

Extracting knowledge from floor plans is **hard** because:

1. **No standards** - Every architect, every software, every country draws differently
2. **Implicit information** - Humans "see" rooms, but the file only has lines
3. **OCR noise** - Text is rotated, stylized, abbreviated, multilingual
4. **Scale ambiguity** - Scale might be in a corner, in a legend, or not shown at all
5. **Multi-floor complexity** - One PDF can have 1 floor or 10 floors stacked

---

## 📊 Current State (master branch)

```
✅ WORKING:
├── PDF → Image rendering (PyMuPDF)
├── Largest rectangle detection (main planimetry area)
├── Floor section splitting (based on "Piano" OCR)
├── Room label OCR detection (Tesseract)
└── Basic room candidate detection (bounding boxes)

⏳ PARTIAL:
├── Floor label recognition (OCR returns empty - Tesseract not installed?)
├── Room label → canonical name mapping (fuzzy matching exists)
└── KNN graph for room proximity

❌ MISSING:
├── Room polygon extraction (actual room shapes)
├── Scale detection/input
├── Compass/orientation detection/input
├── Door/window/passage detection
├── Wall classification (internal vs external)
├── Connection graph (which rooms connect)
└── Knowledge Model JSON export
```

---

## 🔬 Technical Deep-Dive: What's Hard

### 1. Room Polygon Extraction

**Problem:** A floor plan has thousands of lines. A room is a closed polygon formed by walls. How do you find it?

**Current approach:** Detect text labels → draw bounding boxes around OCR regions

**What's needed:**
```
Lines (raw) → Wall segments → Closed contours → Room polygons
```

**Techniques to explore:**
- **Hough Line Transform** - Detect all straight lines
- **Line merging** - Combine collinear segments
- **Contour detection** - Find closed shapes after flood-fill
- **Graph-based approach** - Lines as edges, intersections as nodes, find cycles

**Challenges:**
- Furniture lines vs wall lines (same thickness?)
- Doors create gaps in walls (how to "close" them?)
- Curved walls, irregular shapes
- Nested rooms (bathroom inside bedroom suite)

**Files involved:**
- `geometry.py` - needs line detection
- `work_on_sections_v2.1.py` - has some contour logic

---

### 2. Scale Detection

**Problem:** The plan shows 4cm on screen. Is that 4 meters or 40 meters in reality?

**Sources of scale:**
| Source | Reliability | Detection Method |
|--------|-------------|------------------|
| OCR "Scala 1:100" | High | Regex pattern on OCR text |
| Scale bar graphic | Medium | Detect ruler-like shapes + OCR |
| Known dimension annotation | Medium | Find "3.50 m" near a line |
| User input | Highest | CLI argument `--scale 1:100` |
| Default assumption | Low | Assume 1:100 if nothing found |

**Implementation:**
```python
def detect_scale(image, ocr_text, user_input=None):
    if user_input:
        return parse_scale(user_input)
    
    # Try OCR patterns
    patterns = [r"scala\s*1\s*:\s*(\d+)", r"scale\s*1\s*:\s*(\d+)"]
    for p in patterns:
        match = re.search(p, ocr_text, re.IGNORECASE)
        if match:
            return 1 / int(match.group(1))
    
    # Try scale bar detection
    scale_bar = detect_scale_bar_graphic(image)
    if scale_bar:
        return scale_bar
    
    # Fallback
    return 1 / 100  # assume 1:100
```

---

### 3. Compass / Orientation Detection

**Problem:** Which way is North? Critical for thermal calculations.

**Sources:**
| Source | Detection Method |
|--------|------------------|
| North arrow symbol | Template matching, symbol recognition |
| "N" or "NORD" label | OCR near arrow shapes |
| User input | CLI argument `--north 45` (degrees from up) |

**Why it matters for HVAC:**
- South-facing rooms get more sun → less heating, more cooling
- North-facing rooms are colder → more heating
- East/West have morning/evening sun peaks

---

### 4. Connection Detection (Doors, Passages)

**Problem:** Two rooms share a wall. But do they connect? Is there a door?

**Signals:**
- Gap in wall line (door opening)
- Door arc symbol (swing indicator)
- "P" or door label
- Threshold line pattern

**Approach:**
```
For each pair of adjacent rooms:
    Find shared wall segment
    Check for gaps in wall (> 60cm = door width)
    Check for door symbols near gap
    Classify: door / passage / window / solid wall
```

---

### 5. Wall Classification (Internal vs External)

**Problem:** Which walls are exposed to outside? These have heat loss.

**Heuristic:**
- Walls on the perimeter of the entire floor = external
- Walls between rooms = internal
- Walls thicker in drawing = often external (structural)

**Algorithm:**
```python
def classify_walls(floor_polygon, room_polygons):
    external_walls = []
    for room in room_polygons:
        for wall in room.walls:
            if wall.touches(floor_polygon.boundary):
                wall.type = "external"
            else:
                wall.type = "internal"
```

---

## 📁 Proposed File Structure

```
PlanParser/
├── __main__.py                    # CLI entry point
├── config.py                      # Settings, thresholds
│
├── extraction/
│   ├── source_loader.py           # PDF/DWG/DXF → Image
│   ├── scale_detector.py          # Find scale
│   ├── compass_detector.py        # Find north orientation
│   ├── floor_detector.py          # Split into floors
│   ├── room_detector.py           # Find room polygons
│   ├── label_extractor.py         # OCR for room names
│   ├── connection_detector.py     # Doors, passages
│   └── wall_classifier.py         # Internal vs external
│
├── geometry/
│   ├── line_detection.py          # Hough, line merging
│   ├── polygon_builder.py         # Lines → closed shapes
│   ├── graph_builder.py           # Topology graph
│   └── measurements.py            # Pixel → meters conversion
│
├── models/
│   ├── floor.py                   # Floor dataclass
│   ├── room.py                    # Room dataclass
│   ├── wall.py                    # Wall dataclass
│   ├── connection.py              # Door/passage dataclass
│   └── knowledge_model.py         # Full output model
│
├── output/
│   └── json_exporter.py           # Export Knowledge Model
│
└── tests/
    └── ...
```

---

## 🎯 Implementation Phases

### Phase A: Stabilize Current Pipeline (1 week)
- [ ] Install Tesseract, verify OCR works
- [ ] Test on 5+ different floor plan PDFs
- [ ] Fix floor detection OCR patterns
- [ ] Add CLI arguments for `--scale` and `--north`
- [ ] Export basic JSON with floors and room labels

### Phase B: Room Polygon Extraction (2-3 weeks)
- [ ] Implement Hough line detection
- [ ] Implement line segment merging
- [ ] Implement polygon finding (cycle detection)
- [ ] Handle door gaps (close them temporarily for polygon finding)
- [ ] Match OCR labels to polygons (label inside polygon)
- [ ] Calculate room areas (pixels → m² using scale)

### Phase C: Connection & Wall Analysis (1-2 weeks)
- [ ] Detect shared walls between adjacent room polygons
- [ ] Detect gaps in shared walls (potential doors)
- [ ] Classify walls as internal/external
- [ ] Build connection graph

### Phase D: Knowledge Model Export (1 week)
- [ ] Define final JSON schema
- [ ] Implement full export
- [ ] Add validation (schema check)
- [ ] Test with Plan2HVAC prototype consumer

---

## 🧪 Test Cases Needed

| Test Case | Input | Expected Output |
|-----------|-------|-----------------|
| Single floor, 4 rooms | Simple PDF | 4 room polygons, labeled |
| Multi-floor (3 levels) | Complex PDF | 3 floors, each with rooms |
| With scale bar | PDF with "1:50" | Correct m² calculations |
| Rotated text | Angled labels | Labels still extracted |
| DWG input | AutoCAD file | Same output as PDF |
| Missing scale | No scale info | Default 1:100, warning |

---

## 🔧 Dependencies to Add

```txt
# Already have
opencv-python
numpy
pymupdf
pillow

# Need to add
pytesseract          # OCR (+ install Tesseract binary)
shapely              # Polygon operations
networkx             # Graph operations (topology)
pydantic             # Data validation for Knowledge Model
```

---

## 📐 Algorithms Reference

### Line Detection (Hough Transform)
```python
edges = cv2.Canny(gray, 50, 150)
lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50,
                        minLineLength=30, maxLineGap=10)
```

### Polygon from Lines (Shapely)
```python
from shapely.ops import polygonize
from shapely.geometry import LineString

line_strings = [LineString([(x1,y1), (x2,y2)]) for x1,y1,x2,y2 in lines]
polygons = list(polygonize(line_strings))
```

### Room-Label Matching
```python
from shapely.geometry import Point, Polygon

for label, (lx, ly) in ocr_labels:
    label_point = Point(lx, ly)
    for room_polygon in room_polygons:
        if room_polygon.contains(label_point):
            room_polygon.label = label
            break
```

---

## ⚠️ Known Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| OCR accuracy too low | Can't identify rooms | Multi-pass OCR, user correction UI |
| Polygon extraction fails | No room shapes | Fallback to bounding boxes + manual |
| DWG parsing complex | Format not supported | Use external converter (ODA, LibreCAD) |
| Performance on large PDFs | Too slow | Process in tiles, parallel processing |

---

## 📝 Notes from Theory Documents

From `theory/Tre assi fondamentali della teoria.txt`:
- Focus on **topology** (what connects to what) over geometry
- Room **function** matters (bedroom vs bathroom = different HVAC needs)
- **Hierarchy**: Building → Floor → Room → Wall → Opening

From `theory/Struttura topologica e Machine Learning.txt`:
- Graph-based representation is key
- Can use ML for room classification if rule-based fails
- Training data: labeled floor plans

---

## ✅ Definition of Done (PlanParser Complete)

PlanParser is **complete** when it can:

1. Accept PDF/DWG/DXF input
2. Detect scale (OCR or user input)
3. Detect orientation (OCR or user input)
4. Split into floors
5. Extract room polygons with accurate boundaries
6. Label rooms (OCR + fuzzy match)
7. Calculate room areas in m²
8. Detect connections (doors/passages)
9. Classify walls (internal/external)
10. Export valid Knowledge Model JSON

**Acceptance test:** Run on 10 diverse floor plans → 80%+ accuracy on room detection
