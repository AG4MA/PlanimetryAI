"""
Estrazione di segmenti (linee) da immagini di planimetrie.

Pipeline:
    Immagine → Preprocessing → Edge detection → Hough Lines → Segmenti puliti
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    """Un segmento di linea"""
    x1: float
    y1: float
    x2: float
    y2: float
    
    @property
    def length(self) -> float:
        return np.sqrt((self.x2 - self.x1)**2 + (self.y2 - self.y1)**2)
    
    @property
    def angle(self) -> float:
        """Angolo in radianti [-pi, pi]"""
        return np.arctan2(self.y2 - self.y1, self.x2 - self.x1)
    
    @property
    def angle_deg(self) -> float:
        """Angolo in gradi [0, 180]"""
        a = np.degrees(self.angle)
        if a < 0:
            a += 180
        return a
    
    def to_tuple(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return ((self.x1, self.y1), (self.x2, self.y2))
    
    def is_horizontal(self, tolerance_deg: float = 5.0) -> bool:
        return self.angle_deg < tolerance_deg or self.angle_deg > 180 - tolerance_deg
    
    def is_vertical(self, tolerance_deg: float = 5.0) -> bool:
        return abs(self.angle_deg - 90) < tolerance_deg


class LineExtractor:
    """
    Estrae segmenti di linea da un'immagine usando Hough Transform.
    """
    
    def __init__(
        self,
        canny_low: int = 50,
        canny_high: int = 150,
        hough_threshold: int = 50,
        min_line_length: int = 30,
        max_line_gap: int = 10,
        merge_distance: float = 10.0,
        merge_angle_tolerance: float = 5.0,
    ):
        self.canny_low = canny_low
        self.canny_high = canny_high
        self.hough_threshold = hough_threshold
        self.min_line_length = min_line_length
        self.max_line_gap = max_line_gap
        self.merge_distance = merge_distance
        self.merge_angle_tolerance = merge_angle_tolerance
    
    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocessing dell'immagine"""
        # Converti in grayscale se necessario
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Blur per ridurre rumore
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Bilateral filter per preservare i bordi
        filtered = cv2.bilateralFilter(blurred, 9, 75, 75)
        
        return filtered
    
    def detect_edges(self, gray: np.ndarray) -> np.ndarray:
        """Rileva i bordi con Canny"""
        edges = cv2.Canny(gray, self.canny_low, self.canny_high)
        
        # Dilata leggermente per connettere linee vicine
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        
        return edges
    
    def detect_lines(self, edges: np.ndarray) -> List[Segment]:
        """Rileva linee con Hough Transform"""
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=self.hough_threshold,
            minLineLength=self.min_line_length,
            maxLineGap=self.max_line_gap
        )
        
        if lines is None:
            return []
        
        segments = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            segments.append(Segment(x1, y1, x2, y2))
        
        return segments
    
    def merge_collinear_segments(self, segments: List[Segment]) -> List[Segment]:
        """
        Unisce segmenti collineari vicini.
        
        Due segmenti vengono uniti se:
        1. Hanno angoli simili (entro tolerance)
        2. La distanza tra gli endpoint è piccola
        """
        if len(segments) < 2:
            return segments
        
        merged = []
        used = set()
        
        for i, s1 in enumerate(segments):
            if i in used:
                continue
            
            # Cerca segmenti da unire
            current = s1
            for j, s2 in enumerate(segments[i+1:], start=i+1):
                if j in used:
                    continue
                
                # Controlla se gli angoli sono simili
                angle_diff = abs(current.angle_deg - s2.angle_deg)
                if angle_diff > 90:
                    angle_diff = 180 - angle_diff
                
                if angle_diff > self.merge_angle_tolerance:
                    continue
                
                # Controlla la distanza tra endpoint
                dist = self._min_endpoint_distance(current, s2)
                if dist > self.merge_distance:
                    continue
                
                # Unisci i segmenti
                current = self._merge_two_segments(current, s2)
                used.add(j)
            
            merged.append(current)
            used.add(i)
        
        return merged
    
    def _min_endpoint_distance(self, s1: Segment, s2: Segment) -> float:
        """Distanza minima tra gli endpoint di due segmenti"""
        distances = [
            np.sqrt((s1.x1 - s2.x1)**2 + (s1.y1 - s2.y1)**2),
            np.sqrt((s1.x1 - s2.x2)**2 + (s1.y1 - s2.y2)**2),
            np.sqrt((s1.x2 - s2.x1)**2 + (s1.y2 - s2.y1)**2),
            np.sqrt((s1.x2 - s2.x2)**2 + (s1.y2 - s2.y2)**2),
        ]
        return min(distances)
    
    def _merge_two_segments(self, s1: Segment, s2: Segment) -> Segment:
        """Unisce due segmenti nel segmento che li copre entrambi"""
        all_points = [
            (s1.x1, s1.y1),
            (s1.x2, s1.y2),
            (s2.x1, s2.y1),
            (s2.x2, s2.y2),
        ]
        
        # Trova i due punti più distanti
        max_dist = 0
        best_pair = (all_points[0], all_points[1])
        for i, p1 in enumerate(all_points):
            for p2 in all_points[i+1:]:
                dist = np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
                if dist > max_dist:
                    max_dist = dist
                    best_pair = (p1, p2)
        
        return Segment(
            best_pair[0][0], best_pair[0][1],
            best_pair[1][0], best_pair[1][1]
        )
    
    def extract(self, image: np.ndarray) -> List[Segment]:
        """
        Pipeline completa di estrazione.
        
        Args:
            image: Immagine BGR o grayscale
            
        Returns:
            Lista di segmenti
        """
        gray = self.preprocess(image)
        edges = self.detect_edges(gray)
        segments = self.detect_lines(edges)
        merged = self.merge_collinear_segments(segments)
        return merged
    
    def extract_with_debug(
        self, 
        image: np.ndarray, 
        output_dir: Optional[Path] = None
    ) -> Tuple[List[Segment], dict]:
        """
        Estrazione con output di debug.
        """
        debug = {}
        
        # Preprocessing
        gray = self.preprocess(image)
        debug['preprocessed'] = gray
        
        # Edges
        edges = self.detect_edges(gray)
        debug['edges'] = edges
        
        # Linee grezze
        raw_segments = self.detect_lines(edges)
        debug['raw_segments'] = raw_segments
        debug['raw_count'] = len(raw_segments)
        
        # Linee unite
        merged = self.merge_collinear_segments(raw_segments)
        debug['merged_segments'] = merged
        debug['merged_count'] = len(merged)
        
        # Visualizzazione
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(exist_ok=True)
            
            cv2.imwrite(str(output_dir / "01_preprocessed.png"), gray)
            cv2.imwrite(str(output_dir / "02_edges.png"), edges)
            
            # Disegna raw segments
            raw_img = image.copy()
            for s in raw_segments:
                cv2.line(raw_img, (int(s.x1), int(s.y1)), (int(s.x2), int(s.y2)), (0, 0, 255), 1)
            cv2.imwrite(str(output_dir / "03_raw_lines.png"), raw_img)
            
            # Disegna merged segments
            merged_img = image.copy()
            for s in merged:
                cv2.line(merged_img, (int(s.x1), int(s.y1)), (int(s.x2), int(s.y2)), (0, 255, 0), 2)
            cv2.imwrite(str(output_dir / "04_merged_lines.png"), merged_img)
        
        return merged, debug


def filter_by_orientation(
    segments: List[Segment], 
    keep_horizontal: bool = True,
    keep_vertical: bool = True,
    tolerance_deg: float = 10.0
) -> List[Segment]:
    """Filtra segmenti per orientamento"""
    filtered = []
    for s in segments:
        if keep_horizontal and s.is_horizontal(tolerance_deg):
            filtered.append(s)
        elif keep_vertical and s.is_vertical(tolerance_deg):
            filtered.append(s)
        elif not keep_horizontal and not keep_vertical:
            # Tieni solo diagonali
            if not s.is_horizontal(tolerance_deg) and not s.is_vertical(tolerance_deg):
                filtered.append(s)
    return filtered


def filter_by_length(
    segments: List[Segment],
    min_length: float = 0,
    max_length: float = float('inf')
) -> List[Segment]:
    """Filtra segmenti per lunghezza"""
    return [s for s in segments if min_length <= s.length <= max_length]


# ==================== TEST ====================
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    from testV1 import OUTPUT_DIR, DATA_DIR
    
    print("Test LineExtractor\n")
    
    # Cerca un'immagine di test
    test_images = list(DATA_DIR.glob("*.png")) + list(DATA_DIR.glob("*.jpg"))
    
    if not test_images:
        # Crea un'immagine di test sintetica
        print("Creazione immagine di test sintetica...")
        test_img = np.ones((400, 400, 3), dtype=np.uint8) * 255
        
        # Disegna un rettangolo (stanza)
        cv2.rectangle(test_img, (50, 50), (350, 350), (0, 0, 0), 2)
        
        # Aggiungi una parete interna
        cv2.line(test_img, (200, 50), (200, 250), (0, 0, 0), 2)
        
        test_path = OUTPUT_DIR / "test_synthetic.png"
        cv2.imwrite(str(test_path), test_img)
    else:
        test_path = test_images[0]
        test_img = cv2.imread(str(test_path))
        print(f"Usando immagine: {test_path}")
    
    # Estrai linee
    extractor = LineExtractor()
    segments, debug = extractor.extract_with_debug(test_img, OUTPUT_DIR / "line_debug")
    
    print(f"\nRisultati:")
    print(f"  Segmenti raw: {debug['raw_count']}")
    print(f"  Segmenti merged: {debug['merged_count']}")
    
    # Statistiche
    if segments:
        lengths = [s.length for s in segments]
        print(f"\nLunghezze:")
        print(f"  Min: {min(lengths):.1f}")
        print(f"  Max: {max(lengths):.1f}")
        print(f"  Media: {np.mean(lengths):.1f}")
        
        h_count = sum(1 for s in segments if s.is_horizontal())
        v_count = sum(1 for s in segments if s.is_vertical())
        print(f"\nOrientamento:")
        print(f"  Orizzontali: {h_count}")
        print(f"  Verticali: {v_count}")
        print(f"  Altro: {len(segments) - h_count - v_count}")
    
    print(f"\nDebug salvato in: {OUTPUT_DIR / 'line_debug'}")
