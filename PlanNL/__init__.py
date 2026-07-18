"""
PlanNL — natural-language querying over the PlanimetryAI Knowledge Model.

Public API:
    from PlanNL import load, answer
    building = load("knowledge_model.json")
    print(answer(building, "quante stanze ci sono?").format())
"""
from .knowledge import Building, Room, load, build_from_dict
from .query import Answer, answer, SUPPORTED

__all__ = [
    "Building",
    "Room",
    "load",
    "build_from_dict",
    "Answer",
    "answer",
    "SUPPORTED",
]
