"""
DCEL - Doubly Connected Edge List

Implementazione della struttura dati fondamentale per rappresentare
suddivisioni planari (planimetrie = stanze).

Basato su: de Berg et al. - "Computational Geometry: Algorithms and Applications"
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Set
import math


@dataclass
class Vertex:
    """Un vertice (punto di intersezione pareti)"""
    id: int
    x: float
    y: float
    incident_edge: Optional['HalfEdge'] = None  # Un half-edge che parte da questo vertice
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, Vertex):
            return False
        return self.id == other.id
    
    def distance_to(self, other: 'Vertex') -> float:
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)
    
    def coords(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass
class Face:
    """Una faccia (stanza o regione esterna)"""
    id: int
    outer_edge: Optional['HalfEdge'] = None  # Un half-edge sul bordo esterno
    inner_edges: List['HalfEdge'] = field(default_factory=list)  # Half-edges su buchi interni
    label: Optional[str] = None  # Nome della stanza (da OCR)
    is_external: bool = False  # True se è la faccia esterna infinita
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, Face):
            return False
        return self.id == other.id
    
    def get_vertices(self) -> List[Vertex]:
        """Restituisce tutti i vertici del bordo in ordine"""
        if self.outer_edge is None:
            return []
        
        vertices = []
        edge = self.outer_edge
        start = edge
        while True:
            vertices.append(edge.origin)
            edge = edge.next
            if edge is None or edge == start:
                break
        return vertices
    
    def get_polygon(self) -> List[Tuple[float, float]]:
        """Restituisce le coordinate del poligono"""
        return [v.coords() for v in self.get_vertices()]
    
    def compute_area(self) -> float:
        """Calcola l'area usando la formula di Gauss (Shoelace)"""
        coords = self.get_polygon()
        if len(coords) < 3:
            return 0.0
        
        n = len(coords)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += coords[i][0] * coords[j][1]
            area -= coords[j][0] * coords[i][1]
        return abs(area) / 2.0


@dataclass
class HalfEdge:
    """
    Un half-edge (mezzo arco).
    
    Ogni segmento di parete è rappresentato da DUE half-edges:
    - Uno per ogni direzione
    - Ogni half-edge "appartiene" alla faccia alla sua sinistra
    """
    id: int
    origin: Optional[Vertex] = None  # Vertice di partenza
    twin: Optional['HalfEdge'] = None  # Half-edge opposto (stessa linea, direzione inversa)
    face: Optional[Face] = None  # Faccia alla sinistra di questo half-edge
    next: Optional['HalfEdge'] = None  # Prossimo half-edge lungo il bordo della faccia
    prev: Optional['HalfEdge'] = None  # Half-edge precedente
    
    # Metadati
    is_door: bool = False  # True se questo arco rappresenta una porta
    is_window: bool = False
    is_external_wall: bool = False
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, HalfEdge):
            return False
        return self.id == other.id
    
    def destination(self) -> Optional[Vertex]:
        """Il vertice di destinazione (= origin del twin)"""
        if self.twin:
            return self.twin.origin
        return None
    
    def length(self) -> float:
        """Lunghezza del segmento"""
        if self.origin and self.twin and self.twin.origin:
            return self.origin.distance_to(self.twin.origin)
        return 0.0


class DCEL:
    """
    Doubly Connected Edge List.
    
    Struttura dati per suddivisioni planari con:
    - Accesso O(1) a vertici, archi, facce
    - Navigazione O(1) tra elementi adiacenti
    - Enumerazione O(n) di tutte le facce
    """
    
    def __init__(self):
        self.vertices: Dict[int, Vertex] = {}
        self.half_edges: Dict[int, HalfEdge] = {}
        self.faces: Dict[int, Face] = {}
        
        self._next_vertex_id = 0
        self._next_edge_id = 0
        self._next_face_id = 0
    
    def create_vertex(self, x: float, y: float) -> Vertex:
        """Crea un nuovo vertice"""
        v = Vertex(id=self._next_vertex_id, x=x, y=y)
        self.vertices[v.id] = v
        self._next_vertex_id += 1
        return v
    
    def create_half_edge(self) -> HalfEdge:
        """Crea un nuovo half-edge"""
        e = HalfEdge(id=self._next_edge_id)
        self.half_edges[e.id] = e
        self._next_edge_id += 1
        return e
    
    def create_face(self, label: Optional[str] = None) -> Face:
        """Crea una nuova faccia"""
        f = Face(id=self._next_face_id, label=label)
        self.faces[f.id] = f
        self._next_face_id += 1
        return f
    
    def create_edge_pair(self, v1: Vertex, v2: Vertex) -> Tuple[HalfEdge, HalfEdge]:
        """
        Crea una coppia di half-edges tra due vertici.
        Restituisce (e1, e2) dove e1 va da v1 a v2, e2 è il twin.
        """
        e1 = self.create_half_edge()
        e2 = self.create_half_edge()
        
        e1.origin = v1
        e2.origin = v2
        
        e1.twin = e2
        e2.twin = e1
        
        # Aggiorna incident_edge dei vertici se non impostato
        if v1.incident_edge is None:
            v1.incident_edge = e1
        if v2.incident_edge is None:
            v2.incident_edge = e2
        
        return e1, e2
    
    def enumerate_faces(self) -> List[Face]:
        """
        Enumera tutte le facce percorrendo i cicli di half-edges.
        
        Complessità: O(V + E)
        """
        visited: Set[int] = set()
        faces: List[Face] = []
        
        for edge_id, edge in self.half_edges.items():
            if edge_id in visited:
                continue
            
            # Percorri il ciclo
            cycle: List[HalfEdge] = []
            current = edge
            while current.id not in visited:
                cycle.append(current)
                visited.add(current.id)
                if current.next is None:
                    break
                current = current.next
                if current == edge:
                    break
            
            # Se abbiamo un ciclo chiuso, crea/identifica la faccia
            if len(cycle) >= 3 and current == edge:
                face = cycle[0].face
                if face is None:
                    face = self.create_face()
                    face.outer_edge = edge
                    for e in cycle:
                        e.face = face
                
                if face not in faces:
                    faces.append(face)
        
        return faces
    
    def get_rooms(self, min_area: float = 0.0, max_area: float = float('inf')) -> List[Face]:
        """
        Restituisce le facce che sono "stanze" (non la faccia esterna, area valida).
        """
        rooms = []
        for face in self.enumerate_faces():
            if face.is_external:
                continue
            area = face.compute_area()
            if min_area <= area <= max_area:
                rooms.append(face)
        return rooms
    
    def build_dual_graph(self) -> Dict[int, List[int]]:
        """
        Costruisce il grafo duale: nodi = facce, archi = pareti condivise.
        
        Returns:
            Dict[face_id, List[adjacent_face_ids]]
        """
        adjacency: Dict[int, Set[int]] = {f.id: set() for f in self.faces.values()}
        
        for edge in self.half_edges.values():
            if edge.face and edge.twin and edge.twin.face:
                f1_id = edge.face.id
                f2_id = edge.twin.face.id
                if f1_id != f2_id:
                    adjacency[f1_id].add(f2_id)
                    adjacency[f2_id].add(f1_id)
        
        return {k: list(v) for k, v in adjacency.items()}
    
    def validate(self) -> Tuple[bool, str]:
        """
        Valida la struttura DCEL usando la formula di Eulero: V - E + F = 2
        
        Returns:
            (is_valid, message)
        """
        V = len(self.vertices)
        E = len(self.half_edges) // 2  # Ogni arco ha 2 half-edges
        F = len(self.enumerate_faces())
        
        euler = V - E + F
        
        if euler == 2:
            return True, f"✅ Formula di Eulero verificata: V({V}) - E({E}) + F({F}) = 2"
        else:
            return False, f"❌ Formula di Eulero fallita: V({V}) - E({E}) + F({F}) = {euler} (dovrebbe essere 2)"
    
    @classmethod
    def from_segments(cls, segments: List[Tuple[Tuple[float, float], Tuple[float, float]]]) -> 'DCEL':
        """
        Costruisce una DCEL da una lista di segmenti.
        
        Args:
            segments: Lista di ((x1, y1), (x2, y2)) che rappresentano i segmenti
            
        Returns:
            DCEL costruita
        """
        dcel = cls()
        
        # 1. Trova tutti i vertici unici (con tolleranza)
        EPSILON = 1.0  # Tolleranza per considerare due punti uguali
        vertex_coords: List[Tuple[float, float]] = []
        coord_to_vertex: Dict[Tuple[int, int], Vertex] = {}
        
        def get_or_create_vertex(x: float, y: float) -> Vertex:
            # Cerca un vertice esistente vicino
            key = (round(x / EPSILON), round(y / EPSILON))
            if key in coord_to_vertex:
                return coord_to_vertex[key]
            
            v = dcel.create_vertex(x, y)
            coord_to_vertex[key] = v
            return v
        
        # 2. Crea half-edges per ogni segmento
        edge_pairs: List[Tuple[HalfEdge, HalfEdge]] = []
        for (x1, y1), (x2, y2) in segments:
            v1 = get_or_create_vertex(x1, y1)
            v2 = get_or_create_vertex(x2, y2)
            
            if v1 == v2:
                continue  # Ignora segmenti degeneri
            
            e1, e2 = dcel.create_edge_pair(v1, v2)
            edge_pairs.append((e1, e2))
        
        # 3. Collega next/prev per ogni vertice (in senso orario)
        dcel._link_edges_around_vertices()
        
        # 4. Identifica le facce
        dcel.enumerate_faces()
        
        return dcel
    
    def _link_edges_around_vertices(self):
        """
        Per ogni vertice, ordina gli half-edges uscenti in senso orario
        e collega i next/prev appropriatamente.
        """
        from collections import defaultdict
        
        # Raggruppa half-edges per vertice di origine
        edges_from_vertex: Dict[int, List[HalfEdge]] = defaultdict(list)
        for edge in self.half_edges.values():
            if edge.origin:
                edges_from_vertex[edge.origin.id].append(edge)
        
        # Per ogni vertice, ordina gli half-edges per angolo
        for vertex_id, edges in edges_from_vertex.items():
            if len(edges) < 2:
                continue
            
            vertex = self.vertices[vertex_id]
            
            # Calcola l'angolo di ogni half-edge
            def edge_angle(e: HalfEdge) -> float:
                dest = e.destination()
                if dest is None:
                    return 0.0
                dx = dest.x - vertex.x
                dy = dest.y - vertex.y
                return math.atan2(dy, dx)
            
            # Ordina in senso orario (angoli decrescenti)
            sorted_edges = sorted(edges, key=edge_angle, reverse=True)
            
            # Collega: il next di un edge entrante è il prossimo edge uscente
            for i, e_out in enumerate(sorted_edges):
                e_in = e_out.twin  # L'edge che ARRIVA a questo vertice
                if e_in is None:
                    continue
                
                # Il prossimo edge uscente in senso orario
                next_out = sorted_edges[(i + 1) % len(sorted_edges)]
                
                e_in.next = next_out
                next_out.prev = e_in


# ==================== TEST ====================
if __name__ == "__main__":
    print("Test DCEL - Creazione manuale di una stanza quadrata\n")
    
    dcel = DCEL()
    
    # Crea 4 vertici (un quadrato)
    v1 = dcel.create_vertex(0, 0)
    v2 = dcel.create_vertex(100, 0)
    v3 = dcel.create_vertex(100, 100)
    v4 = dcel.create_vertex(0, 100)
    
    # Crea 4 archi (i lati)
    e12, e21 = dcel.create_edge_pair(v1, v2)
    e23, e32 = dcel.create_edge_pair(v2, v3)
    e34, e43 = dcel.create_edge_pair(v3, v4)
    e41, e14 = dcel.create_edge_pair(v4, v1)
    
    # Collega i next per la faccia interna (senso antiorario)
    e12.next = e23
    e23.next = e34
    e34.next = e41
    e41.next = e12
    
    e12.prev = e41
    e23.prev = e12
    e34.prev = e23
    e41.prev = e34
    
    # Collega i next per la faccia esterna (senso orario)
    e21.next = e14
    e14.next = e43
    e43.next = e32
    e32.next = e21
    
    # Crea le facce
    room = dcel.create_face(label="Stanza Test")
    room.outer_edge = e12
    e12.face = e23.face = e34.face = e41.face = room
    
    external = dcel.create_face()
    external.is_external = True
    external.outer_edge = e21
    e21.face = e14.face = e43.face = e32.face = external
    
    # Test
    print(f"Vertici: {len(dcel.vertices)}")
    print(f"Half-edges: {len(dcel.half_edges)}")
    print(f"Facce: {len(dcel.faces)}")
    
    # Valida
    valid, msg = dcel.validate()
    print(f"\n{msg}")
    
    # Area della stanza
    print(f"\nArea della stanza: {room.compute_area():.2f} unità²")
    print(f"Poligono: {room.get_polygon()}")
    
    # Grafo duale
    dual = dcel.build_dual_graph()
    print(f"\nGrafo duale: {dual}")
