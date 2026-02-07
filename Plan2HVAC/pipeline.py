"""
Plan2HVAC Pipeline

Main orchestration module that ties together all components:
1. Load knowledge model from PlanParser
2. Calculate thermal requirements
3. Place HVAC elements
4. Route pipes
5. Generate outputs (JSON, SVG)
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from pathlib import Path

from .models.knowledge_model import KnowledgeModel
from .models.hvac_elements import HVACSystem, Boiler
from .core.thermal_calculator import (
    ThermalCalculator, ThermalRequirements, ClimateZone
)
from .core.hvac_placer import HVACPlacer, PlacementConstraints
from .core.pipe_router import PipeRouter, PipeRouterConfig, PipingLayout
from .output.json_exporter import JSONExporter
from .output.drawing_generator import DrawingGenerator, DrawingConfig


@dataclass
class PipelineConfig:
    """Configuration for the HVAC generation pipeline."""
    # Climate and building settings
    climate_zone: ClimateZone = ClimateZone.E
    insulation_quality: float = 1.0
    ceiling_height_m: float = 2.7
    
    # System preferences
    include_heating: bool = True
    include_cooling: bool = True
    piping_layout: PipingLayout = PipingLayout.TWO_PIPE
    
    # Boiler settings
    boiler_room_id: Optional[str] = None  # Auto-detect if None
    boiler_fuel_type: str = "gas"
    
    # Output settings
    output_dir: str = "output"
    generate_svg: bool = True
    generate_json: bool = True


class Plan2HVACPipeline:
    """
    Main pipeline for generating HVAC plans.
    
    Usage:
        pipeline = Plan2HVACPipeline()
        result = pipeline.run("path/to/knowledge_model.json")
        result = pipeline.run_from_model(knowledge_model)
    """
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        
        # Initialize components
        self.thermal_calculator = ThermalCalculator(
            climate_zone=self.config.climate_zone,
            insulation_quality=self.config.insulation_quality,
            ceiling_height_m=self.config.ceiling_height_m
        )
        self.hvac_placer = HVACPlacer()
        self.pipe_router = PipeRouter(
            PipeRouterConfig(layout=self.config.piping_layout)
        )
        self.json_exporter = JSONExporter()
        self.drawing_generator = DrawingGenerator()
    
    def _find_boiler_room(self, knowledge_model: KnowledgeModel) -> Tuple[str, Tuple[float, float]]:
        """
        Find the best room for the boiler.
        
        Prefers: utility rooms, kitchens, garages.
        Returns: (room_id, position)
        """
        preferred_keywords = ["caldaia", "centrale", "tecnico", "garage", "cantina", "cucina"]
        
        for floor in knowledge_model.floors:
            for room in floor.rooms:
                label_lower = room.label.lower()
                for keyword in preferred_keywords:
                    if keyword in label_lower:
                        return room.id, room.get_centroid()
        
        # Fallback: first room on first floor
        if knowledge_model.floors and knowledge_model.floors[0].rooms:
            room = knowledge_model.floors[0].rooms[0]
            return room.id, room.get_centroid()
        
        return "unknown", (0, 0)
    
    def run_from_model(
        self, 
        knowledge_model: KnowledgeModel,
        output_prefix: str = "hvac_plan"
    ) -> HVACSystem:
        """
        Run the pipeline on a loaded knowledge model.
        
        Returns the generated HVACSystem.
        """
        print(f"[Plan2HVAC] Starting HVAC generation...")
        print(f"  Climate zone: {self.config.climate_zone.value}")
        print(f"  Floors: {len(knowledge_model.floors)}")
        print(f"  Total rooms: {sum(len(f.rooms) for f in knowledge_model.floors)}")
        
        # Step 1: Calculate thermal requirements
        print("\n[Step 1] Calculating thermal requirements...")
        requirements = self.thermal_calculator.calculate_building_requirements(
            knowledge_model
        )
        
        total_heating = self.thermal_calculator.get_total_heating_load(requirements)
        total_cooling = self.thermal_calculator.get_total_cooling_load(requirements)
        print(f"  Total heating load: {total_heating:.1f} kW")
        print(f"  Total cooling load: {total_cooling:.1f} kW")
        
        # Step 2: Place HVAC elements
        print("\n[Step 2] Placing HVAC elements...")
        radiators, ac_units = self.hvac_placer.place_all_hvac(
            knowledge_model,
            requirements,
            include_heating=self.config.include_heating,
            include_cooling=self.config.include_cooling
        )
        print(f"  Radiators placed: {len(radiators)}")
        print(f"  AC units placed: {len(ac_units)}")
        
        # Step 3: Create boiler
        print("\n[Step 3] Sizing boiler...")
        boiler_size = self.thermal_calculator.recommend_boiler_size(requirements)
        
        if self.config.boiler_room_id:
            boiler_room_id = self.config.boiler_room_id
            # Find room position
            boiler_pos = (0, 0)
            for floor in knowledge_model.floors:
                for room in floor.rooms:
                    if room.id == boiler_room_id:
                        boiler_pos = room.get_centroid()
                        break
        else:
            boiler_room_id, boiler_pos = self._find_boiler_room(knowledge_model)
        
        boiler = Boiler(
            id="BOILER_001",
            position=boiler_pos,
            room_id=boiler_room_id,
            power_kw=boiler_size,
            fuel_type=self.config.boiler_fuel_type
        )
        print(f"  Recommended boiler: {boiler_size} kW ({self.config.boiler_fuel_type})")
        
        # Step 4: Route pipes
        print("\n[Step 4] Routing pipes...")
        pipes = self.pipe_router.route_system(
            boiler, radiators, knowledge_model
        )
        pipe_lengths = self.pipe_router.calculate_total_pipe_length(pipes)
        print(f"  Pipe layout: {self.config.piping_layout.value}")
        print(f"  Total pipe length: {pipe_lengths['total_m']:.1f} m")
        
        # Step 5: Assemble HVAC system
        hvac_system = HVACSystem(
            radiators=radiators,
            ac_units=ac_units,
            pipes=pipes,
            boilers=[boiler],
            total_heating_power_kw=total_heating,
            total_cooling_power_kw=total_cooling
        )
        
        # Step 6: Generate outputs
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if self.config.generate_json:
            print("\n[Step 5] Exporting JSON...")
            json_path = output_dir / f"{output_prefix}.json"
            self.json_exporter.export_to_file(
                hvac_system,
                knowledge_model,
                requirements,
                str(json_path),
                climate_zone=self.config.climate_zone.value
            )
            print(f"  Saved: {json_path}")
        
        if self.config.generate_svg:
            print("\n[Step 6] Generating SVG drawing...")
            svg_path = output_dir / f"{output_prefix}.svg"
            self.drawing_generator.export_svg(
                knowledge_model,
                hvac_system,
                str(svg_path)
            )
            print(f"  Saved: {svg_path}")
        
        print("\n[Plan2HVAC] Complete!")
        return hvac_system
    
    def run(
        self,
        knowledge_model_path: str,
        output_prefix: str = "hvac_plan"
    ) -> HVACSystem:
        """
        Run the pipeline on a knowledge model JSON file.
        
        Args:
            knowledge_model_path: Path to the knowledge model JSON from PlanParser
            output_prefix: Prefix for output files
            
        Returns:
            The generated HVACSystem
        """
        print(f"[Plan2HVAC] Loading knowledge model: {knowledge_model_path}")
        knowledge_model = KnowledgeModel.from_json_file(knowledge_model_path)
        
        return self.run_from_model(knowledge_model, output_prefix)


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Plan2HVAC - Automated HVAC Plan Generation"
    )
    parser.add_argument(
        "input",
        help="Path to knowledge model JSON file from PlanParser"
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "-p", "--prefix",
        default="hvac_plan",
        help="Output file prefix (default: hvac_plan)"
    )
    parser.add_argument(
        "-z", "--climate-zone",
        choices=["A", "B", "C", "D", "E", "F"],
        default="E",
        help="Italian climate zone (default: E)"
    )
    parser.add_argument(
        "--no-cooling",
        action="store_true",
        help="Skip AC unit placement"
    )
    parser.add_argument(
        "--no-svg",
        action="store_true",
        help="Skip SVG generation"
    )
    
    args = parser.parse_args()
    
    config = PipelineConfig(
        climate_zone=ClimateZone[args.climate_zone],
        output_dir=args.output,
        include_cooling=not args.no_cooling,
        generate_svg=not args.no_svg
    )
    
    pipeline = Plan2HVACPipeline(config)
    pipeline.run(args.input, args.prefix)


if __name__ == "__main__":
    main()
