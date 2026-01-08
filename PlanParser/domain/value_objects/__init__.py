"""
Domain Value Objects
====================
Immutable value objects for measurements, orientation, and topology.
"""

from PlanParser.domain.value_objects.measurements import (
    LengthUnit,
    AreaUnit,
    Length,
    Area,
    Scale,
)

from PlanParser.domain.value_objects.orientation import (
    CardinalDirection,
    Compass,
)

from PlanParser.domain.value_objects.topology import (
    ConnectionType,
    WallPosition,
    Adjacency,
    TopologyGraph,
)


__all__ = [
    # Measurements
    "LengthUnit",
    "AreaUnit", 
    "Length",
    "Area",
    "Scale",
    
    # Orientation
    "CardinalDirection",
    "Compass",
    
    # Topology
    "ConnectionType",
    "WallPosition",
    "Adjacency",
    "TopologyGraph",
]
