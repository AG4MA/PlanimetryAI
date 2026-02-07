# Plan2HVAC

Given a planimetry parsed by PlanParser, automates the generation of an HVAC heat/cold plant drawing with precise sizing and accurate layout over the plan.

## Features

- **Thermal Calculations**: Calculates heating and cooling requirements per room based on:
  - Room volume and area
  - External wall exposure
  - Climate zone (Italian zones A-F)
  - Room usage type (living, bedroom, bathroom, etc.)
  - Insulation quality

- **HVAC Element Placement**: Automatically places:
  - Radiators (sized and positioned on optimal walls)
  - AC split units (positioned on internal walls)
  - Boiler (auto-detected or specified room)

- **Pipe Routing**: Routes heating pipes with support for:
  - Two-pipe system (parallel, recommended)
  - One-pipe system (series, simpler)
  - Radial/manifold system (star topology)

- **Output Generation**:
  - JSON export with complete system specifications
  - SVG drawing with HVAC elements overlaid on floor plan

## Installation

```bash
cd Plan2HVAC
pip install -r requirements.txt
```

## Usage

### As a Python Module

```python
from Plan2HVAC.pipeline import Plan2HVACPipeline, PipelineConfig
from Plan2HVAC.core.thermal_calculator import ClimateZone

# Configure the pipeline
config = PipelineConfig(
    climate_zone=ClimateZone.E,  # Northern Italy
    include_heating=True,
    include_cooling=True,
    output_dir="output"
)

# Run pipeline
pipeline = Plan2HVACPipeline(config)
hvac_system = pipeline.run("path/to/knowledge_model.json")

# Access results
print(f"Total heating: {hvac_system.total_heating_power_kw} kW")
print(f"Radiators: {len(hvac_system.radiators)}")
```

### Command Line

```bash
python -m Plan2HVAC.pipeline input.json -o output/ -z E
```

Options:
- `-o, --output`: Output directory (default: output)
- `-p, --prefix`: Output file prefix (default: hvac_plan)
- `-z, --climate-zone`: Climate zone A-F (default: E)
- `--no-cooling`: Skip AC unit placement
- `--no-svg`: Skip SVG generation

## Project Structure

```
Plan2HVAC/
├── __init__.py
├── pipeline.py           # Main orchestration
├── models/
│   ├── knowledge_model.py   # Input model from PlanParser
│   └── hvac_elements.py     # HVAC element definitions
├── core/
│   ├── thermal_calculator.py  # Heat/cool load calculations
│   ├── hvac_placer.py         # Element placement logic
│   └── pipe_router.py         # Pipe routing algorithms
├── output/
│   ├── json_exporter.py      # JSON output
│   └── drawing_generator.py  # SVG generation
└── examples/
    └── run_example.py        # Example usage
```

## Input Format

Plan2HVAC consumes the Knowledge Model JSON from PlanParser:

```json
{
  "source": {
    "file": "planimetry.pdf",
    "scale": "1:100"
  },
  "floors": [
    {
      "id": "floor_0",
      "label": "Piano Terra",
      "rooms": [
        {
          "id": "room_1",
          "label": "Soggiorno",
          "polygon": [[0,0], [400,0], [400,300], [0,300]],
          "area_m2": 12.0,
          "walls": [
            {"side": "north", "type": "external", "length_m": 4.0}
          ]
        }
      ]
    }
  ]
}
```

## Output Format

### JSON Output

```json
{
  "meta": {"generated_at": "...", "generator": "Plan2HVAC"},
  "thermal_requirements": {...},
  "hvac_system": {
    "radiators": [...],
    "ac_units": [...],
    "pipes": [...],
    "boilers": [...]
  },
  "summary": {
    "total_heating_power_kw": 15.5,
    "total_cooling_power_kw": 12.0,
    "n_radiators": 8
  }
}
```

### SVG Output

Visual floor plan with:
- Room outlines and labels
- Radiator symbols (red rectangles)
- AC unit symbols (blue with snowflake)
- Supply pipes (solid red)
- Return pipes (dashed blue)
- Legend

## Climate Zones

Italian climate zones based on degree-days:

| Zone | Degree Days | Example Cities |
|------|-------------|----------------|
| A | <600 | Lampedusa |
| B | 600-900 | Palermo, Catania |
| C | 900-1400 | Napoli, Bari |
| D | 1400-2100 | Roma, Firenze |
| E | 2100-3000 | Milano, Torino, Bologna |
| F | >3000 | Belluno, mountain areas |

## Dependencies

- Python 3.8+
- No external dependencies for core functionality
- Optional: Pillow for PNG export, ReportLab for PDF export
