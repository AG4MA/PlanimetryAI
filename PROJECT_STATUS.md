# PlanimetryAI - Project Status Report

**Date:** January 9, 2026  
**PM Assessment**

---

## 🎯 Project Vision

Create an intelligent system that automatically generates professional HVAC (heating/cooling) plans from architectural floor plans, with precise measurements ready for workers and professionals to use directly.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INPUT SOURCES                               │
│              PDF / DWG / DXF / Images + Client Data                 │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         PLANPARSER                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │ Source      │→ │ Floor       │→ │ Room        │→ │ Knowledge  │ │
│  │ Ingestion   │  │ Detection   │  │ Recognition │  │ Model      │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │
│                                                            │        │
│  Outputs: Structured Digital Twin (JSON/Object Model)      │        │
│  - Floors with boundaries                                  │        │
│  - Rooms with polygons, areas, labels                      │        │
│  - Connections (doors, passages)                           │        │
│  - Scale & orientation                                     │        │
│  - Topology graph                                          │        │
└────────────────────────────────────────────────────────────┼────────┘
                                                             │
                         ┌───────────────────────────────────┼───────┐
                         │      KNOWLEDGE MODEL OUTPUT       │       │
                         │   (Structured, Machine-Readable)  │       │
                         └───────────────────────────────────┼───────┘
                                                             │
                    ┌────────────────────────────────────────┴────────────────────────────────────┐
                    │                                                                              │
                    ▼                                                                              ▼
┌─────────────────────────────────────────────┐      ┌─────────────────────────────────────────────┐
│               PLAN2HVAC                     │      │                 PLANNL                      │
│                                             │      │                                             │
│  Consumes Knowledge Model to:               │      │  Consumes Knowledge Model to:               │
│  • Calculate thermal requirements           │      │  • Answer natural language questions        │
│  • Size heating/cooling units               │      │  • "How big is the living room?"            │
│  • Place radiators/AC units                 │      │  • "Which rooms face south?"                │
│  • Route pipes/ducts                        │      │  • "Show me the bathroom layout"            │
│  • Generate annotated HVAC plan             │      │  • Export filtered views                    │
│                                             │      │                                             │
│  Output: Professional HVAC drawings         │      │  Output: Answers, reports, custom views     │
└─────────────────────────────────────────────┘      └─────────────────────────────────────────────┘
```

**Key Insight:** PlanParser is the **producer** of structured knowledge. Plan2HVAC and PlanNL are **consumers** that use this knowledge for different purposes.

---

## 📋 Project Phases Overview

### Phase 1: Input & Source Parsing *(Current Focus)*
| Task | Status | Notes |
|------|--------|-------|
| Accept PDF sources | ✅ Done | via PyMuPDF |
| Accept DWG/DXF sources | ⏳ Planned | Not yet implemented |
| Detect largest rectangle (main planimetry) | ✅ Done | `from_pdf_to_floors.v2.py` |
| Extract scale from plan | ⏳ Not Started | Client input OR OCR detection needed |
| Extract compass/orientation | ⏳ Not Started | Not yet implemented |

### Phase 2: Floor & Section Detection *(In Progress)*
| Task | Status | Notes |
|------|--------|-------|
| Split into floors | 🔄 In Progress | `define_floor_v2.py` - OCR-based floor detection |
| OCR floor labels (Piano Terra, 1° Piano, etc.) | 🔄 In Progress | Works but needs tuning (currently no detection on test PDF) |
| Create floor sections | 🔄 In Progress | Creates sections based on detected "piano" lines |
| Handle multi-floor PDFs | 🔄 Partial | Logic exists but needs validation |

### Phase 3: Semantic Room Recognition *(Early Stage)*
| Task | Status | Notes |
|------|--------|-------|
| Detect room boundaries | ⏳ Planned | `work_on_sections_v2.1.py` has candidate detection |
| OCR room labels (Bagno, Cucina, Camera, etc.) | 🔄 In Progress | Using Tesseract with multiple PSM modes |
| Build room graph (KNN neighbors) | 🔄 In Progress | Logic exists in `work_on_sections_v2.1.py` |
| Understand room connections | ⏳ Not Started | Doors, windows, passages |
| Calculate room areas | ⏳ Not Started | Depends on scale extraction |

### Phase 4: Environmental Understanding *(Not Started)*
| Task | Status | Notes |
|------|--------|-------|
| Identify external walls | ⏳ Not Started | Critical for thermal calculations |
| Sun exposure analysis | ⏳ Not Started | Compass + wall orientation needed |
| Thermal zone mapping | ⏳ Not Started | Group rooms by heating/cooling needs |
| Heat loss/gain calculations | ⏳ Not Started | Based on wall exposure, area, insulation |

### Phase 5: HVAC Generation *(Not Started - Plan2HVAC)*
| Task | Status | Notes |
|------|--------|-------|
| Calculate heating requirements per room | ⏳ Not Started | Watts based on volume, exposure, use |
| Calculate cooling requirements | ⏳ Not Started | Similar factors |
| Place radiators/units optimally | ⏳ Not Started | Under windows, wall space considerations |
| Route piping/ducts | ⏳ Not Started | Shortest paths, avoid obstacles |
| Generate annotated HVAC plan | ⏳ Not Started | Draw on original with measurements |
| Export professional output | ⏳ Not Started | PDF/DXF with specs |

### Phase 6: Natural Language Interface *(Not Started - PlanNL)*
| Task | Status | Notes |
|------|--------|-------|
| Query room information | ⏳ Not Started | "What's the area of the kitchen?" |
| Query spatial relationships | ⏳ Not Started | "Which rooms are adjacent to bathroom?" |
| Query thermal zones | ⏳ Not Started | "Which rooms face south?" |
| Generate custom reports | ⏳ Not Started | Filtered exports, summaries |

---

## 🗂️ Current Repository Structure

```
PlanimetryAI/
├── PlanParser/          ← PRODUCER: Generates Knowledge Model (Phase 1-3)
│   ├── from_pdf_to_floors.v2.py   # Main entry point
│   ├── define_floor_v2.py         # Floor detection & OCR
│   ├── work_on_sections_v2.1.py   # Room detection pipeline
│   ├── geometry.py                # Geometric utilities
│   └── theory/                    # Theoretical notes (Italian)
│
├── Plan2HVAC/           ← CONSUMER: HVAC Generation (Phase 4-5)
│   └── README.md only   # Awaiting Knowledge Model from PlanParser
│
├── PlanNL/              ← CONSUMER: Natural Language Queries
│   └── README.md only   # Awaiting Knowledge Model from PlanParser
│
├── PlanimetryDigitalConventions/  ← STANDARD: Knowledge Model Schema
│   └── README.md only   # Defines the structure of the Knowledge Model
```

---

## 📦 Knowledge Model (PlanParser Output)

The **Knowledge Model** is the structured output that PlanParser must produce. This is what Plan2HVAC and PlanNL will consume.

### Required Knowledge Model Structure:
```json
{
  "source": {
    "file": "planimetry.pdf",
    "scale": "1:100",
    "orientation": { "north": 45 }
  },
  "floors": [
    {
      "id": "floor_0",
      "label": "Piano Terra",
      "bounds": { "x": 0, "y": 0, "width": 1200, "height": 800 },
      "rooms": [
        {
          "id": "room_1",
          "label": "Soggiorno",
          "polygon": [[0,0], [400,0], [400,300], [0,300]],
          "area_m2": 12.0,
          "connections": [
            { "to": "room_2", "type": "door" },
            { "to": "room_3", "type": "passage" }
          ],
          "walls": [
            { "side": "north", "type": "external", "length_m": 4.0 },
            { "side": "east", "type": "internal", "length_m": 3.0 }
          ]
        }
      ]
    }
  ],
  "topology": {
    "adjacency_graph": { ... }
  }
}
```

### Knowledge Model Completeness:
| Data Point | Status | Needed By |
|------------|--------|-----------|
| Floor boundaries | 🔄 In Progress | Plan2HVAC, PlanNL |
| Floor labels | 🔄 In Progress | PlanNL |
| Room polygons | ⏳ Not Started | Plan2HVAC (critical) |
| Room labels | 🔄 In Progress | PlanNL |
| Room areas | ⏳ Not Started | Plan2HVAC (critical) |
| Room connections | ⏳ Not Started | Plan2HVAC, PlanNL |
| Wall classification | ⏳ Not Started | Plan2HVAC (thermal calc) |
| Scale | ⏳ Not Started | Plan2HVAC (critical) |
| Compass/Orientation | ⏳ Not Started | Plan2HVAC (thermal calc) |

---

## 🔴 Current Blockers & Gaps

### Critical Missing Pieces:

1. **Scale Detection** - Without knowing the scale (1:100, 1:50, etc.), we cannot calculate real-world measurements
   - Need: OCR detection of scale annotation OR user input
   
2. **Compass/Orientation** - Without knowing North, we can't determine sun exposure
   - Need: OCR detection of compass symbol OR user input

3. **Room Boundary Detection** - Current OCR detects labels but not the actual room polygons
   - Need: Line detection + contour analysis to create closed room shapes

4. **Connection Detection** - No logic for detecting doors/passages between rooms
   - Need: Gap detection in walls, door symbol recognition

5. **Tesseract not installed** - OCR returning empty results
   - Need: Install Tesseract OCR engine on system

---

## 📊 Progress Summary

| Component | Phase | Progress | Blocker |
|-----------|-------|----------|---------|
| **PlanParser** | 1-3 | **40%** | Room polygons, scale, OCR tuning |
| **Knowledge Model** | - | **20%** | Waiting for PlanParser completion |
| **Plan2HVAC** | 4-5 | **0%** | Waiting for Knowledge Model |
| **PlanNL** | 6 | **0%** | Waiting for Knowledge Model |

**Overall Project Progress: ~20%**

**Critical Path:** PlanParser → Knowledge Model → Plan2HVAC / PlanNL

---

## 🚀 Recommended Next Steps

### Priority 1: Complete PlanParser → Knowledge Model
*Without this, Plan2HVAC and PlanNL cannot start*

**Immediate (This Week):**
1. ✅ Install Tesseract OCR on the system
2. ✅ Fix OCR floor detection (currently returning empty)
3. Define Knowledge Model JSON schema (in PlanimetryDigitalConventions)
4. Add scale input (CLI argument or OCR detection)
5. Add compass/orientation input

**Short-term (2-4 Weeks):**
6. Implement room polygon extraction (closed contours from lines)
7. Calculate room areas from polygons + scale
8. Detect doors/passages between rooms
9. Build room adjacency graph
10. **OUTPUT: First complete Knowledge Model JSON**

### Priority 2: Start Plan2HVAC (After Knowledge Model)
11. Implement wall classification (internal vs external)
12. Add thermal calculation logic
13. Create basic HVAC sizing algorithm
14. Generate first annotated output

### Priority 3: Start PlanNL (Can run parallel to Plan2HVAC)
15. Implement query parser
16. Connect to Knowledge Model
17. Basic Q&A functionality

---

## 📝 Notes

- The `develop` branch contains more mature code with proper project structure (domain models, tests, etc.)
- The `master` branch has simpler experimental scripts
- Consider merging the structured approach from `develop` when stabilizing
- **PlanimetryDigitalConventions** should define the official Knowledge Model schema so Plan2HVAC and PlanNL teams can develop in parallel once schema is frozen
