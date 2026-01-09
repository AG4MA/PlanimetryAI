"""
Costruzione del grafo planare da segmenti.

Pipeline:
    Segmenti → Intersezioni → Vertici → Grafo planare → DCEL
"""

import numpy as np
from typing import List, Tuple, Optional, Dict, Set
from dataclasses import dataclass
from collections import defaultdict
import math

from .line_extraction import Segment
from .dcel import DCEL, Vertex, HalfEdge, Face


@dataclass
class Intersection:
    """Punto di intersezione tra due segmenti"""
    x: float
    y: float
    segment1_idx: int
    segment2_idx: int


def line_intersection(
    p1: Tuple[float, float], 
    p2: Tuple[float, float],
    p3: Tuple[float, float], 
    p4: Tuple[float, float]
) -> Optional[Tuple[float, float]]:
    """
    Trova l'intersezione tra due segmenti (p1-p2) e (p3-p4).
    
    Returns:
        (x, y) se i segmenti si intersecano, None altrimenti
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    
    if abs(denom) < 1e-10:
        return None  # Linee parallele
    
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    
    # Controlla se l'intersezione è all'interno di entrambi i segmenti
    if 0 <= t <= 1 and 0 <= u <= 1:
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return (x, y)
    
    return None


def find_all_intersections(segments: List[Segment]) -> List[Intersection]:
    """
    Trova tutte le intersezioni tra i segmenti.
    
    Complessità: O(n²) - per planimetrie piccole è accettabile
    """
    intersections = []
    
    for i, s1 in enumerate(segments):
        for j, s2 in enumerate(segments[i+1:], start=i+1):
            p = line_intersection(
                (s1.x1, s1.y1), (s1.x2, s1.y2),
                (s2.x1, s2.y1), (s2.x2, s2.y2)
            )
            if p:
                intersections.append(Intersection(p[0], p[1], i, j))
    
    return intersections


def split_segments_at_intersections(
    segments: List[Segment], 
    intersections: List[Intersection],
    tolerance: float = 1.0
) -> List[Segment]:
    """
    Divide i segmenti nei punti di intersezione.
    
    Questo è fondamentale: dopo questa operazione, i segmenti si toccano
    solo agli endpoint, mai nel mezzo.
    """
    # Raggruppa le intersezioni per segmento
    splits: Dict[int, List[Tuple[float, float]]] = defaultdict(list)
    
    for inter in intersections:
        splits[inter.segment1_idx].append((inter.x, inter.y))
        splits[inter.segment2_idx].append((inter.x, inter.y))
    
    new_segments = []
    
    for i, seg in enumerate(segments):
        if i not in splits:
            new_segments.append(seg)
            continue
        
        # Ordina i punti di split lungo il segmento
        points = [(seg.x1, seg.y1)] + splits[i] + [(seg.x2, seg.y2)]
        
        # Ordina per distanza dall'inizio
        def dist_from_start(p):
            return (p[0] - seg.x1)**2 + (p[1] - seg.y1)**2
        
        points.sort(key=dist_from_start)
        
        # Rimuovi duplicati
        unique_points = [points[0]]
        for p in points[1:]:
            if (p[0] - unique_points[-1][0])**2 + (p[1] - unique_points[-1][1])**2 > tolerance**2:
                unique_points.append(p)
        
        # Crea nuovi segmenti
        for j in range(len(unique_points) - 1):
            p1, p2 = unique_points[j], unique_points[j+1]
            new_seg = Segment(p1[0], p1[1], p2[0], p2[1])
            if new_seg.length > tolerance:
                new_segments.append(new_seg)
    
    return new_segments


class GraphBuilder:
    """
    Costruisce una DCEL da una lista di segmenti.
    """
    
    def __init__(self, vertex_tolerance: float = 2.0):
        self.vertex_tolerance = vertex_tolerance
    
    def build(self, segments: List[Segment]) -> DCEL:
        """
        Costruisce la DCEL dai segmenti.
        
        1. Trova tutte le intersezioni
        2. Divide i segmenti
        3. Crea vertici e half-edges
        4. Collega la struttura
        5. Enumera le facce
        """
        print(f"[GraphBuilder] Input: {len(segments)} segmenti")
        
        # Step 1: Trova intersezioni
        intersections = find_all_intersections(segments)
        print(f"[GraphBuilder] Trovate {len(intersections)} intersezioni")
        
        # Step 2: Dividi segmenti
        split_segs = split_segments_at_intersections(segments, intersections)
        print(f"[GraphBuilder] Dopo split: {len(split_segs)} segmenti")
        
        # Step 3: Costruisci DCEL
        dcel = DCEL()
        
        # Mappa coordinate -> vertice (per evitare duplicati)
        coord_to_vertex: Dict[Tuple[int, int], Vertex] = {}
        
        def get_or_create_vertex(x: float, y: float) -> Vertex:
            key = (round(x / self.vertex_tolerance), round(y / self.vertex_tolerance))
            if key in coord_to_vertex:
                return coord_to_vertex[key]
            v = dcel.create_vertex(x, y)
            coord_to_vertex[key] = v
            return v
        
        # Crea half-edges per ogni segmento
        for seg in split_segs:
            v1 = get_or_create_vertex(seg.x1, seg.y1)
            v2 = get_or_create_vertex(seg.x2, seg.y2)
            
            if v1 == v2:
                continue
            
            dcel.create_edge_pair(v1, v2)
        
        print(f"[GraphBuilder] Creati {len(dcel.vertices)} vertici, {len(dcel.half_edges)} half-edges")
        
        # Step 4: Collega next/prev
        self._link_edges(dcel)
        
        # Step 5: Enumera facce
        faces = dcel.enumerate_faces()
        print(f"[GraphBuilder] Trovate {len(faces)} facce")
        
        # Step 6: Identifica la faccia esterna (quella con area maggiore o illimitata)
        self._identify_external_face(dcel, faces)
        
        # Validazione
        valid, msg = dcel.validate()
        print(f"[GraphBuilder] {msg}")
        
        return dcel
    
    def _link_edges(self, dcel: DCEL):
        """
        Collega gli half-edges intorno a ogni vertice in senso orario.
        """
        # Raggruppa half-edges per vertice di origine
        edges_from: Dict[int, List[HalfEdge]] = defaultdict(list)
        edges_to: Dict[int, List[HalfEdge]] = defaultdict(list)
        
        for edge in dcel.half_edges.values():
            if edge.origin:
                edges_from[edge.origin.id].append(edge)
            if edge.twin and edge.twin.origin:
                edges_to[edge.twin.origin.id].append(edge)
        
        # Per ogni vertice, ordina gli half-edges uscenti per angolo
        for vertex_id in dcel.vertices:
            vertex = dcel.vertices[vertex_id]
            outgoing = edges_from[vertex_id]
            
            if len(outgoing) < 1:
                continue
            
            # Calcola angolo per ogni edge uscente
            def edge_angle(e: HalfEdge) -> float:
                dest = e.destination()
                if dest is None:
                    return 0.0
                dx = dest.x - vertex.x
                dy = dest.y - vertex.y
                return math.atan2(dy, dx)
            
            # Ordina in senso antiorario (per avere facce con bordo in senso antiorario)
            sorted_outgoing = sorted(outgoing, key=edge_angle)
            
            # Collega: l'incoming edge (twin) punta al prossimo outgoing
            for i, e_out in enumerate(sorted_outgoing):
                e_in = e_out.twin  # Edge che ARRIVA al vertice
                if e_in is None:
                    continue
                
                # Il prossimo edge in senso antiorario
                next_idx = (i + 1) % len(sorted_outgoing)
                next_out = sorted_outgoing[next_idx]
                
                e_in.next = next_out
                next_out.prev = e_in
    
    def _identify_external_face(self, dcel: DCEL, faces: List[Face]):
        """
        Identifica la faccia esterna (quella che contiene "l'infinito").
        
        Euristica: la faccia esterna ha l'area più grande O è percorsa in senso orario.
        """
        if not faces:
            return
        
        # Trova la faccia con area maggiore
        max_area = -1
        external = None
        
        for face in faces:
            area = face.compute_area()
            if area > max_area:
                max_area = area
                external = face
        
        if external:
            external.is_external = True
            external.label = "EXTERNAL"


def segments_to_rooms(
    segments: List[Segment],
    min_room_area: float = 100.0,  # pixel²
    max_room_area: float = float('inf')
) -> Tuple[DCEL, List[Face]]:
    """
    Funzione di convenienza: da segmenti a lista di stanze.
    
    Returns:
        (dcel, rooms) dove rooms sono le facce che rappresentano stanze
    """
    builder = GraphBuilder()
    dcel = builder.build(segments)
    
    rooms = []
    for face in dcel.faces.values():
        if face.is_external:
            continue
        area = face.compute_area()
        if min_room_area <= area <= max_room_area:
            rooms.append(face)
    
    return dcel, rooms


# ==================== TEST ====================
if __name__ == "__main__":
    print("Test GraphBuilder\n")
    
    # Crea segmenti di test: due stanze adiacenti
    #
    #  +--------+--------+
    #  |        |        |
    #  | Room1  | Room2  |
    #  |        |        |
    #  +--------+--------+
    #
    segments = [
        # Bordo esterno
        Segment(0, 0, 200, 0),      # Top
        Segment(200, 0, 200, 100),  # Right
        Segment(200, 100, 0, 100),  # Bottom
        Segment(0, 100, 0, 0),      # Left
        # Parete divisoria
        Segment(100, 0, 100, 100),  # Middle wall
    ]
    
    print(f"Segmenti di input: {len(segments)}")
    for i, s in enumerate(segments):
        print(f"  {i}: ({s.x1:.0f},{s.y1:.0f}) -> ({s.x2:.0f},{s.y2:.0f})")
    
    # Costruisci DCEL
    dcel, rooms = segments_to_rooms(segments, min_room_area=0)
    
    print(f"\nStanze trovate: {len(rooms)}")
    for room in rooms:
        print(f"  Face {room.id}: area={room.compute_area():.1f}, vertices={len(room.get_vertices())}")
        print(f"    Polygon: {room.get_polygon()}")
    
    # Grafo duale
    dual = dcel.build_dual_graph()
    print(f"\nGrafo duale (adiacenze):")
    for face_id, neighbors in dual.items():
        face = dcel.faces[face_id]
        label = "EXT" if face.is_external else f"Room"
        print(f"  Face {face_id} ({label}): adiacente a {neighbors}")
