"""
Pipeline completa: PDF → Stanze con topologia.

Questo script integra tutto il codice esistente + l'approccio matematico
per estrarre stanze e relazioni da una planimetria PDF.
"""

import sys
import cv2
import numpy as np
import fitz  # PyMuPDF
from PIL import Image
import io
from pathlib import Path
from typing import Optional, Tuple, List, Dict

# Setup paths
TESTV1_ROOT = Path(__file__).parent
sys.path.insert(0, str(TESTV1_ROOT))

from core.dcel import DCEL, Face
from core.line_extraction import LineExtractor, Segment, filter_by_orientation, filter_by_length
from core.graph_builder import GraphBuilder, segments_to_rooms

# Tesseract setup
TESSERACT_EXE = TESTV1_ROOT / "tesseract" / "tesseract.exe"
TESSDATA_DIR = TESTV1_ROOT / "tesseract" / "tessdata"

# Configura pytesseract
try:
    import pytesseract
    if TESSERACT_EXE.exists():
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
        import os
        os.environ['TESSDATA_PREFIX'] = str(TESSDATA_DIR)
        print(f"✅ Tesseract configurato: {TESSERACT_EXE}")
    else:
        print(f"⚠️ Tesseract non trovato: {TESSERACT_EXE}")
        pytesseract = None
except ImportError:
    print("⚠️ pytesseract non installato")
    pytesseract = None


class PlanimetryPipeline:
    """
    Pipeline completa per l'analisi di planimetrie.
    
    Fasi:
    1. Carica PDF/immagine
    2. Trova il rettangolo principale
    3. Estrai linee (pareti)
    4. Costruisci grafo planare (DCEL)
    5. Identifica stanze
    6. OCR per etichette
    7. Costruisci Knowledge Model
    """
    
    def __init__(
        self,
        output_dir: Optional[Path] = None,
        min_room_area_px: float = 1000,
        scale: Optional[str] = None,  # es. "1:100"
    ):
        self.output_dir = output_dir or (TESTV1_ROOT / "output")
        self.output_dir.mkdir(exist_ok=True)
        self.min_room_area_px = min_room_area_px
        self.scale = scale
        self.scale_factor = self._parse_scale(scale) if scale else None
        
        self.line_extractor = LineExtractor(
            canny_low=50,
            canny_high=150,
            hough_threshold=40,
            min_line_length=20,
            max_line_gap=15,
        )
        self.graph_builder = GraphBuilder(vertex_tolerance=5.0)
    
    def _parse_scale(self, scale: str) -> float:
        """Parse scala tipo '1:100' → 0.01"""
        if ':' in scale:
            parts = scale.split(':')
            return float(parts[0]) / float(parts[1])
        return 1.0
    
    def load_pdf(self, pdf_path: str, page: int = 0, zoom: float = 2.0) -> np.ndarray:
        """Carica una pagina PDF come immagine"""
        doc = fitz.open(pdf_path)
        page_obj = doc.load_page(page)
        mat = fitz.Matrix(zoom, zoom)
        pix = page_obj.get_pixmap(matrix=mat)
        
        # Converti in numpy array
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img_np = np.array(img.convert("RGB"))
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        
        print(f"📄 Caricato PDF: {pdf_path}")
        print(f"   Dimensioni: {img_bgr.shape[1]}x{img_bgr.shape[0]} px")
        
        return img_bgr
    
    def find_main_rectangle(self, image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Trova il rettangolo più grande (area della planimetria).
        
        Replicato dal codice originale from_pdf_to_floors.v2.py
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 150)
        
        contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        max_area = 0
        best_rect = None
        
        for cnt in contours:
            approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                x, y, w, h = cv2.boundingRect(approx)
                area = w * h
                if area > max_area:
                    max_area = area
                    best_rect = (x, y, w, h)
        
        if best_rect:
            x, y, w, h = best_rect
            print(f"📐 Rettangolo principale: {w}x{h} @ ({x},{y})")
        
        return best_rect
    
    def crop_main_area(
        self, 
        image: np.ndarray, 
        rect: Tuple[int, int, int, int],
        padding: int = 10
    ) -> np.ndarray:
        """Ritaglia l'area principale con un po' di padding"""
        x, y, w, h = rect
        x1 = max(0, x + padding)
        y1 = max(0, y + padding)
        x2 = min(image.shape[1], x + w - padding)
        y2 = min(image.shape[0], y + h - padding)
        
        return image[y1:y2, x1:x2].copy()
    
    def extract_lines(self, image: np.ndarray) -> List[Segment]:
        """Estrai le linee (pareti) dall'immagine"""
        segments, debug = self.line_extractor.extract_with_debug(
            image, 
            self.output_dir / "01_line_extraction"
        )
        
        print(f"📏 Estratte {len(segments)} linee")
        
        # Filtra per orientamento (mantieni solo H/V per planimetrie standard)
        hv_segments = filter_by_orientation(segments, True, True, tolerance_deg=15)
        print(f"   → {len(hv_segments)} linee orizzontali/verticali")
        
        return hv_segments
    
    def build_topology(self, segments: List[Segment]) -> Tuple[DCEL, List[Face]]:
        """Costruisci la struttura topologica"""
        dcel, rooms = segments_to_rooms(
            segments, 
            min_room_area=self.min_room_area_px
        )
        
        print(f"🏠 Trovate {len(rooms)} stanze")
        
        return dcel, rooms
    
    def ocr_room_labels(self, image: np.ndarray, rooms: List[Face]) -> Dict[int, str]:
        """
        Esegui OCR per trovare le etichette delle stanze.
        
        Per ogni stanza, cerca testo all'interno del suo poligono.
        """
        if pytesseract is None:
            print("⚠️ OCR non disponibile (pytesseract non configurato)")
            return {}
        
        labels = {}
        
        try:
            # OCR sull'intera immagine
            data = pytesseract.image_to_data(
                image, 
                lang="ita+eng",
                config="--psm 6",
                output_type=pytesseract.Output.DICT
            )
            
            # Per ogni parola trovata, assegna alla stanza che la contiene
            from shapely.geometry import Point, Polygon
            
            for i, word in enumerate(data['text']):
                if not word or len(word.strip()) < 2:
                    continue
                
                # Centro del box OCR
                cx = data['left'][i] + data['width'][i] / 2
                cy = data['top'][i] + data['height'][i] / 2
                point = Point(cx, cy)
                
                # Trova la stanza che contiene questo punto
                for room in rooms:
                    poly_coords = room.get_polygon()
                    if len(poly_coords) < 3:
                        continue
                    
                    poly = Polygon(poly_coords)
                    if poly.contains(point):
                        if room.id not in labels:
                            labels[room.id] = []
                        labels[room.id].append(word.strip())
                        break
            
            # Combina le parole per ogni stanza
            for room_id in labels:
                labels[room_id] = " ".join(labels[room_id])
            
            print(f"🏷️ OCR trovate etichette per {len(labels)} stanze")
            
        except Exception as e:
            print(f"❌ Errore OCR: {e}")
        
        return labels
    
    def visualize_results(
        self, 
        image: np.ndarray, 
        dcel: DCEL, 
        rooms: List[Face],
        labels: Dict[int, str]
    ) -> np.ndarray:
        """Crea un'immagine con le stanze colorate e etichettate"""
        result = image.copy()
        
        # Colori per le stanze
        colors = [
            (255, 200, 200),  # Rosa
            (200, 255, 200),  # Verde chiaro
            (200, 200, 255),  # Azzurro
            (255, 255, 200),  # Giallo
            (255, 200, 255),  # Magenta chiaro
            (200, 255, 255),  # Ciano
        ]
        
        for i, room in enumerate(rooms):
            poly = room.get_polygon()
            if len(poly) < 3:
                continue
            
            # Converti in numpy array
            pts = np.array(poly, dtype=np.int32)
            
            # Riempi con colore semitrasparente
            overlay = result.copy()
            cv2.fillPoly(overlay, [pts], colors[i % len(colors)])
            result = cv2.addWeighted(result, 0.7, overlay, 0.3, 0)
            
            # Bordo
            cv2.polylines(result, [pts], True, (0, 0, 255), 2)
            
            # Etichetta
            label = labels.get(room.id, f"Room {room.id}")
            area = room.compute_area()
            
            # Centro del poligono per il testo
            cx = int(np.mean([p[0] for p in poly]))
            cy = int(np.mean([p[1] for p in poly]))
            
            cv2.putText(result, label, (cx - 30, cy), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
            cv2.putText(result, f"{area:.0f}px²", (cx - 30, cy + 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)
        
        return result
    
    def export_knowledge_model(
        self, 
        dcel: DCEL, 
        rooms: List[Face],
        labels: Dict[int, str]
    ) -> dict:
        """Esporta il Knowledge Model come dizionario"""
        model = {
            "meta": {
                "scale": self.scale,
                "scale_factor": self.scale_factor,
            },
            "rooms": [],
            "topology": {
                "adjacency": {int(k): [int(v) for v in vals] for k, vals in dcel.build_dual_graph().items()}
            }
        }
        
        for room in rooms:
            # Converti polygon in tipi nativi Python (non numpy)
            polygon = [(float(p[0]), float(p[1])) for p in room.get_polygon()]
            
            room_data = {
                "id": int(room.id),
                "label": labels.get(room.id, None),
                "polygon": polygon,
                "area_px": float(room.compute_area()),
            }
            
            if self.scale_factor:
                room_data["area_m2"] = float(room.compute_area() * (self.scale_factor ** 2))
            
            model["rooms"].append(room_data)
        
        return model
    
    def run(self, input_path: str) -> dict:
        """
        Esegue la pipeline completa.
        
        Args:
            input_path: Path al PDF o immagine
            
        Returns:
            Knowledge Model (dict)
        """
        print("\n" + "="*60)
        print("   PLANIMETRY PIPELINE - TestV1")
        print("="*60 + "\n")
        
        input_path = Path(input_path)
        
        # 1. Carica input
        if input_path.suffix.lower() == '.pdf':
            image = self.load_pdf(str(input_path))
        else:
            image = cv2.imread(str(input_path))
        
        cv2.imwrite(str(self.output_dir / "00_input.png"), image)
        
        # 2. Trova area principale
        rect = self.find_main_rectangle(image)
        if rect:
            cropped = self.crop_main_area(image, rect)
        else:
            print("⚠️ Nessun rettangolo trovato, uso immagine intera")
            cropped = image
        
        cv2.imwrite(str(self.output_dir / "01_cropped.png"), cropped)
        
        # 3. Estrai linee
        segments = self.extract_lines(cropped)
        
        # Salva visualizzazione linee
        lines_img = cropped.copy()
        for s in segments:
            cv2.line(lines_img, (int(s.x1), int(s.y1)), (int(s.x2), int(s.y2)), (0, 255, 0), 2)
        cv2.imwrite(str(self.output_dir / "02_lines.png"), lines_img)
        
        # 4. Costruisci topologia
        dcel, rooms = self.build_topology(segments)
        
        # 5. OCR etichette
        labels = self.ocr_room_labels(cropped, rooms)
        
        # Assegna le etichette alle stanze
        for room in rooms:
            if room.id in labels:
                room.label = labels[room.id]
        
        # 6. Visualizza risultati
        result_img = self.visualize_results(cropped, dcel, rooms, labels)
        cv2.imwrite(str(self.output_dir / "03_rooms.png"), result_img)
        
        # 7. Esporta Knowledge Model
        knowledge = self.export_knowledge_model(dcel, rooms, labels)
        
        # Salva come JSON
        import json
        with open(self.output_dir / "knowledge_model.json", "w", encoding="utf-8") as f:
            json.dump(knowledge, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Pipeline completata!")
        print(f"   Output salvato in: {self.output_dir}")
        print(f"   Stanze trovate: {len(rooms)}")
        print(f"   Etichette OCR: {len(labels)}")
        
        # Stampa sommario
        print("\n📊 SOMMARIO:")
        for room in rooms:
            label = labels.get(room.id, "???")
            area = room.compute_area()
            print(f"   • Room {room.id}: {label} ({area:.0f} px²)")
        
        return knowledge


# ==================== MAIN ====================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Pipeline planimetria → stanze")
    parser.add_argument("input", help="Path al file PDF o immagine")
    parser.add_argument("--scale", help="Scala (es. 1:100)")
    parser.add_argument("--output", help="Cartella output")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output) if args.output else None
    
    pipeline = PlanimetryPipeline(
        output_dir=output_dir,
        scale=args.scale,
    )
    
    knowledge = pipeline.run(args.input)
