"""
Example usage of Plan2HVAC

This script demonstrates how to use Plan2HVAC with the 
knowledge model output from PlanParser.
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from Plan2HVAC.pipeline import Plan2HVACPipeline, PipelineConfig
from Plan2HVAC.core.thermal_calculator import ClimateZone
from Plan2HVAC.core.pipe_router import PipingLayout


def run_example():
    """Run Plan2HVAC on the example knowledge model from PlanParser."""
    
    # Path to knowledge model from PlanParser
    knowledge_model_path = Path(__file__).parent.parent / \
        "PlanParser/testV1/output/knowledge_model.json"
    
    if not knowledge_model_path.exists():
        print(f"Error: Knowledge model not found at {knowledge_model_path}")
        print("Please run PlanParser first to generate the knowledge model.")
        return
    
    # Configure the pipeline
    config = PipelineConfig(
        climate_zone=ClimateZone.E,  # Northern Italy
        insulation_quality=1.0,       # Average insulation
        ceiling_height_m=2.7,
        include_heating=True,
        include_cooling=True,
        piping_layout=PipingLayout.TWO_PIPE,
        output_dir=str(Path(__file__).parent / "output"),
        generate_svg=True,
        generate_json=True
    )
    
    # Create and run pipeline
    pipeline = Plan2HVACPipeline(config)
    hvac_system = pipeline.run(str(knowledge_model_path), "hvac_example")
    
    # Print summary
    print("\n" + "=" * 50)
    print("HVAC SYSTEM SUMMARY")
    print("=" * 50)
    print(f"Radiators: {len(hvac_system.radiators)}")
    print(f"AC Units: {len(hvac_system.ac_units)}")
    print(f"Boilers: {len(hvac_system.boilers)}")
    print(f"Total Heating: {hvac_system.total_heating_power_kw:.1f} kW")
    print(f"Total Cooling: {hvac_system.total_cooling_power_kw:.1f} kW")
    print(f"Pipe segments: {sum(len(p.segments) for p in hvac_system.pipes)}")
    print("=" * 50)
    
    print(f"\nOutput files in: {config.output_dir}/")


if __name__ == "__main__":
    run_example()
