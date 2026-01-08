"""
Geometric Validation Module
===========================
Formalizza invarianti matematiche che DEVONO essere vere per un risultato corretto.

Se una invariante è violata → risultato sicuramente sbagliato.
Se tutte rispettate → risultato probabilmente corretto.

INVARIANTI FONDAMENTALI:
1. CONTENIMENTO: La label DEVE essere DENTRO il poligono della sua stanza
2. AREA MINIMA: Area poligono >> Area bbox label (almeno 10x)
3. ASPECT RATIO: Stanze reali hanno ratio ragionevole (0.2 < w/h < 5)
4. NON-OVERLAP: Stanze diverse non devono sovrapporsi significativamente
5. CONVESSITÀ RAGIONEVOLE: Stanze hanno convexity ratio > 0.5
6. COPERTURA: Somma aree stanze ≈ area utile planimetria (30-90%)
"""

import logging
import math
from dataclasses import dataclass, field
from enum import Enum

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    PASS = "✅ PASS"
    FAIL = "❌ FAIL"
    WARN = "⚠️ WARN"


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    name: str
    status: ValidationStatus
    message: str
    details: dict = field(default_factory=dict)
    
    def __str__(self):
        return f"{self.status.value} {self.name}: {self.message}"


@dataclass
class RoomValidation:
    """Validation results for a single room."""
    label: str
    results: list[ValidationResult] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        """Room is valid only if no FAIL results."""
        return not any(r.status == ValidationStatus.FAIL for r in self.results)
    
    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == ValidationStatus.PASS)
    
    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == ValidationStatus.FAIL)


@dataclass
class GlobalValidation:
    """Global validation results across all rooms."""
    results: list[ValidationResult] = field(default_factory=list)
    room_validations: list[RoomValidation] = field(default_factory=list)
    total_ocr_labels: int = 0  # How many labels OCR found
    
    @property
    def is_valid(self) -> bool:
        global_ok = not any(r.status == ValidationStatus.FAIL for r in self.results)
        rooms_ok = all(rv.is_valid for rv in self.room_validations)
        return global_ok and rooms_ok
    
    @property
    def valid_room_count(self) -> int:
        return sum(1 for rv in self.room_validations if rv.is_valid)
    
    @property
    def score(self) -> float:
        """
        Compute overall validation score S ∈ [0, 1].
        
        S = (weighted sum of passed invariants) / (total possible)
        """
        weights = {
            "I1": 2.0,   # Containment - critical
            "I2": 1.5,   # Area ratio - important
            "I3": 1.0,   # Border distance
            "I4": 0.5,   # Aspect ratio
            "I5": 0.5,   # Convexity
            "I6": 0.5,   # Min area
            "I7": 0.5,   # Vertex count
            "I8": 1.5,   # Overlap - important
            "I9": 2.0,   # Coverage - critical
            "I10": 1.0,  # Room count
        }
        
        total_weight = 0.0
        earned_weight = 0.0
        
        # Per-room invariants
        for rv in self.room_validations:
            for r in rv.results:
                # Extract invariant number from name (e.g., "I1 Containment" -> "I1")
                inv_id = r.name.split()[0] if r.name.startswith("I") else "I0"
                w = weights.get(inv_id, 1.0)
                total_weight += w
                if r.status == ValidationStatus.PASS:
                    earned_weight += w
                elif r.status == ValidationStatus.WARN:
                    earned_weight += w * 0.5
        
        # Global invariants
        for r in self.results:
            inv_id = r.name.split()[0] if r.name.startswith("I") else "I0"
            w = weights.get(inv_id, 1.0)
            total_weight += w
            if r.status == ValidationStatus.PASS:
                earned_weight += w
            elif r.status == ValidationStatus.WARN:
                earned_weight += w * 0.5
        
        return earned_weight / total_weight if total_weight > 0 else 0.0
    
    @property
    def detection_rate(self) -> float:
        """Fraction of OCR labels that got matched to valid rooms."""
        if self.total_ocr_labels == 0:
            return 0.0
        return self.valid_room_count / self.total_ocr_labels
    
    def summary(self) -> str:
        lines = ["=" * 60]
        lines.append("VALIDATION REPORT")
        lines.append("=" * 60)
        
        # Score summary
        lines.append(f"\n📈 SCORE: {self.score:.1%}")
        lines.append(f"   Detection Rate: {self.valid_room_count}/{self.total_ocr_labels} labels = {self.detection_rate:.1%}")
        
        # Global checks
        lines.append("\n📊 GLOBAL CHECKS:")
        for r in self.results:
            lines.append(f"  {r}")
        
        # Per-room checks
        lines.append(f"\n📦 ROOM CHECKS ({self.valid_room_count}/{len(self.room_validations)} valid):")
        for rv in self.room_validations:
            status = "✅" if rv.is_valid else "❌"
            lines.append(f"\n  {status} {rv.label}:")
            for r in rv.results:
                lines.append(f"    {r}")
        
        # Final verdict
        lines.append("\n" + "=" * 60)
        if self.is_valid:
            lines.append(f"🎉 OVERALL: VALID (Score: {self.score:.1%})")
        else:
            lines.append(f"💥 OVERALL: INVALID (Score: {self.score:.1%})")
            lines.append("   Check failed invariants above")
        lines.append("=" * 60)
        
        return "\n".join(lines)


class GeometricValidator:
    """
    Validates room polygons against mathematical invariants.
    
    Usage:
        validator = GeometricValidator()
        report = validator.validate(rooms, image_shape)
        print(report.summary())
    """
    
    # Thresholds (tunabili)
    MIN_AREA_RATIO = 10.0       # Polygon area must be >= 10x label bbox area
    MIN_ASPECT_RATIO = 0.15     # w/h minimum (very thin is suspicious)
    MAX_ASPECT_RATIO = 7.0      # w/h maximum
    MIN_CONVEXITY = 0.4         # Convex hull ratio (0=very concave, 1=convex)
    MAX_OVERLAP_RATIO = 0.1     # Max 10% overlap between rooms
    MIN_COVERAGE = 0.05         # Rooms should cover at least 5% of image
    MAX_COVERAGE = 0.95         # Rooms shouldn't cover more than 95%
    MIN_ROOM_AREA_PX = 500      # Absolute minimum room area in pixels
    MIN_BORDER_DISTANCE = 20    # I3: Minimum distance from label to polygon border (px)
    
    def validate(
        self,
        rooms: list,  # List of RoomPolygon
        image_shape: tuple[int, int],  # (height, width)
        label_bboxes: dict[str, tuple[int, int, int, int]] | None = None,  # {label: (x,y,w,h)}
        total_ocr_labels: int = 0  # Total number of labels found by OCR
    ) -> GlobalValidation:
        """
        Run all validations on detected rooms.
        
        Args:
            rooms: List of RoomPolygon objects
            image_shape: (height, width) of source image
            label_bboxes: Optional dict mapping label to its OCR bounding box
            total_ocr_labels: How many labels OCR found (for detection rate)
        """
        report = GlobalValidation()
        report.total_ocr_labels = total_ocr_labels
        
        image_height, image_width = image_shape
        image_area = image_width * image_height
        
        # ===== PER-ROOM VALIDATIONS =====
        for room in rooms:
            rv = RoomValidation(label=room.label)
            
            # 1. CONTAINMENT: Label position must be inside polygon
            rv.results.append(self._check_containment(room))
            
            # 2. AREA vs LABEL: Polygon area >> label bbox area
            if label_bboxes and room.label in label_bboxes:
                rv.results.append(self._check_area_ratio(room, label_bboxes[room.label]))
            
            # 3. BORDER DISTANCE: Label not too close to walls
            rv.results.append(self._check_border_distance(room))
            
            # 4. ASPECT RATIO: Reasonable proportions
            rv.results.append(self._check_aspect_ratio(room))
            
            # 5. CONVEXITY: Not too convoluted
            rv.results.append(self._check_convexity(room))
            
            # 6. MINIMUM AREA: Not too small
            rv.results.append(self._check_min_area(room, image_area))
            
            # 7. VERTEX COUNT: Reasonable number of vertices
            rv.results.append(self._check_vertex_count(room))
            
            report.room_validations.append(rv)
        
        # ===== GLOBAL VALIDATIONS =====
        
        # 7. NON-OVERLAP: Rooms shouldn't overlap significantly
        report.results.extend(self._check_overlaps(rooms))
        
        # 8. COVERAGE: Total room area should be reasonable fraction of image
        report.results.append(self._check_coverage(rooms, image_area))
        
        # 9. ROOM COUNT: Should have found at least some rooms
        report.results.append(self._check_room_count(rooms))
        
        return report
    
    def _check_containment(self, room) -> ValidationResult:
        """INVARIANT 1: Label position MUST be inside its polygon."""
        lx, ly = room.label_position
        
        # Use OpenCV pointPolygonTest
        # Returns positive if inside, negative if outside, 0 if on edge
        result = cv2.pointPolygonTest(room.contour, (float(lx), float(ly)), measureDist=False)
        
        if result >= 0:
            return ValidationResult(
                name="I1 Containment",
                status=ValidationStatus.PASS,
                message=f"Label at ({lx},{ly}) is inside polygon",
                details={"label_pos": (lx, ly), "test_result": result}
            )
        else:
            # This is a CRITICAL failure - logically impossible
            return ValidationResult(
                name="I1 Containment",
                status=ValidationStatus.FAIL,
                message=f"Label at ({lx},{ly}) is OUTSIDE its polygon! (result={result:.1f})",
                details={"label_pos": (lx, ly), "test_result": result}
            )
    
    def _check_border_distance(self, room) -> ValidationResult:
        """INVARIANT 3: Label must be at least MIN_BORDER_DISTANCE from polygon border."""
        lx, ly = room.label_position
        
        # pointPolygonTest with measureDist=True returns signed distance
        # Positive = inside, value = distance to nearest edge
        distance = cv2.pointPolygonTest(room.contour, (float(lx), float(ly)), measureDist=True)
        
        if distance >= self.MIN_BORDER_DISTANCE:
            return ValidationResult(
                name="I3 Border Distance",
                status=ValidationStatus.PASS,
                message=f"Label is {distance:.1f}px from border (min: {self.MIN_BORDER_DISTANCE}px)",
                details={"distance": distance, "minimum": self.MIN_BORDER_DISTANCE}
            )
        elif distance > 0:
            return ValidationResult(
                name="I3 Border Distance",
                status=ValidationStatus.WARN,
                message=f"Label only {distance:.1f}px from border (min: {self.MIN_BORDER_DISTANCE}px)",
                details={"distance": distance, "minimum": self.MIN_BORDER_DISTANCE}
            )
        else:
            return ValidationResult(
                name="I3 Border Distance",
                status=ValidationStatus.FAIL,
                message=f"Label is outside polygon (distance={distance:.1f}px)",
                details={"distance": distance, "minimum": self.MIN_BORDER_DISTANCE}
            )
    
    def _check_area_ratio(self, room, label_bbox: tuple[int, int, int, int]) -> ValidationResult:
        """INVARIANT 2: Polygon area must be >> label bbox area."""
        x, y, w, h = label_bbox
        label_area = w * h
        
        if label_area == 0:
            return ValidationResult(
                name="I2 Area Ratio",
                status=ValidationStatus.WARN,
                message="Label bbox has zero area",
                details={}
            )
        
        ratio = room.area_pixels / label_area
        
        if ratio >= self.MIN_AREA_RATIO:
            return ValidationResult(
                name="I2 Area Ratio",
                status=ValidationStatus.PASS,
                message=f"Room area = {ratio:.1f}x label area (min: {self.MIN_AREA_RATIO}x)",
                details={"room_area": room.area_pixels, "label_area": label_area, "ratio": ratio}
            )
        else:
            return ValidationResult(
                name="I2 Area Ratio",
                status=ValidationStatus.FAIL,
                message=f"Room area only {ratio:.1f}x label area (need >= {self.MIN_AREA_RATIO}x)",
                details={"room_area": room.area_pixels, "label_area": label_area, "ratio": ratio}
            )
    
    def _check_aspect_ratio(self, room) -> ValidationResult:
        """INVARIANT 3: Bounding box should have reasonable aspect ratio."""
        x, y, w, h = room.bounding_box
        
        if h == 0:
            return ValidationResult(
                name="Aspect Ratio",
                status=ValidationStatus.FAIL,
                message="Height is zero",
                details={}
            )
        
        aspect = w / h
        
        if self.MIN_ASPECT_RATIO <= aspect <= self.MAX_ASPECT_RATIO:
            return ValidationResult(
                name="I4 Aspect Ratio",
                status=ValidationStatus.PASS,
                message=f"Aspect ratio {aspect:.2f} is reasonable ({self.MIN_ASPECT_RATIO}-{self.MAX_ASPECT_RATIO})",
                details={"width": w, "height": h, "aspect": aspect}
            )
        else:
            return ValidationResult(
                name="I4 Aspect Ratio",
                status=ValidationStatus.WARN,
                message=f"Unusual aspect ratio {aspect:.2f} (expected {self.MIN_ASPECT_RATIO}-{self.MAX_ASPECT_RATIO})",
                details={"width": w, "height": h, "aspect": aspect}
            )
    
    def _check_convexity(self, room) -> ValidationResult:
        """INVARIANT 4: Room should not be too convoluted."""
        if room.contour is None or len(room.contour) < 3:
            return ValidationResult(
                name="Convexity",
                status=ValidationStatus.FAIL,
                message="Invalid contour",
                details={}
            )
        
        hull = cv2.convexHull(room.contour)
        hull_area = cv2.contourArea(hull)
        
        if hull_area == 0:
            return ValidationResult(
                name="Convexity",
                status=ValidationStatus.FAIL,
                message="Convex hull has zero area",
                details={}
            )
        
        convexity = room.area_pixels / hull_area
        
        if convexity >= self.MIN_CONVEXITY:
            return ValidationResult(
                name="I5 Convexity",
                status=ValidationStatus.PASS,
                message=f"Convexity {convexity:.2f} is good (min: {self.MIN_CONVEXITY})",
                details={"room_area": room.area_pixels, "hull_area": hull_area, "convexity": convexity}
            )
        else:
            return ValidationResult(
                name="I5 Convexity",
                status=ValidationStatus.WARN,
                message=f"Low convexity {convexity:.2f} - complex shape (min: {self.MIN_CONVEXITY})",
                details={"room_area": room.area_pixels, "hull_area": hull_area, "convexity": convexity}
            )
    
    def _check_min_area(self, room, image_area: int) -> ValidationResult:
        """INVARIANT 5: Room should have minimum absolute area."""
        if room.area_pixels >= self.MIN_ROOM_AREA_PX:
            relative = 100 * room.area_pixels / image_area
            return ValidationResult(
                name="I6 Min Area",
                status=ValidationStatus.PASS,
                message=f"Area {room.area_pixels:.0f}px ({relative:.2f}% of image)",
                details={"area": room.area_pixels, "relative": relative}
            )
        else:
            return ValidationResult(
                name="I6 Min Area",
                status=ValidationStatus.FAIL,
                message=f"Area {room.area_pixels:.0f}px is below minimum {self.MIN_ROOM_AREA_PX}px",
                details={"area": room.area_pixels, "minimum": self.MIN_ROOM_AREA_PX}
            )
    
    def _check_vertex_count(self, room) -> ValidationResult:
        """INVARIANT 6: Simplified polygon should have reasonable vertex count."""
        n_vertices = len(room.vertices)
        
        if 3 <= n_vertices <= 20:
            return ValidationResult(
                name="I7 Vertex Count",
                status=ValidationStatus.PASS,
                message=f"{n_vertices} vertices (3-20 expected for rooms)",
                details={"vertices": n_vertices}
            )
        elif n_vertices > 20:
            return ValidationResult(
                name="I7 Vertex Count",
                status=ValidationStatus.WARN,
                message=f"{n_vertices} vertices is high - complex shape",
                details={"vertices": n_vertices}
            )
        else:
            return ValidationResult(
                name="I7 Vertex Count",
                status=ValidationStatus.FAIL,
                message=f"{n_vertices} vertices - not a valid polygon",
                details={"vertices": n_vertices}
            )
    
    def _check_overlaps(self, rooms: list) -> list[ValidationResult]:
        """INVARIANT 7: Rooms should not overlap significantly."""
        results = []
        
        for i, room1 in enumerate(rooms):
            for j, room2 in enumerate(rooms):
                if i >= j:
                    continue
                
                # Create masks
                # This is expensive but accurate
                x1, y1, w1, h1 = room1.bounding_box
                x2, y2, w2, h2 = room2.bounding_box
                
                # Quick bbox overlap check first
                if not self._bboxes_overlap(room1.bounding_box, room2.bounding_box):
                    continue
                
                # Compute intersection area using masks
                # Create a canvas large enough for both
                max_x = max(x1 + w1, x2 + w2)
                max_y = max(y1 + h1, y2 + h2)
                
                mask1 = np.zeros((max_y + 10, max_x + 10), dtype=np.uint8)
                mask2 = np.zeros((max_y + 10, max_x + 10), dtype=np.uint8)
                
                cv2.fillPoly(mask1, [room1.contour], 255)
                cv2.fillPoly(mask2, [room2.contour], 255)
                
                intersection = cv2.bitwise_and(mask1, mask2)
                inter_area = np.sum(intersection > 0)
                
                min_area = min(room1.area_pixels, room2.area_pixels)
                if min_area > 0:
                    overlap_ratio = inter_area / min_area
                else:
                    overlap_ratio = 0
                
                if overlap_ratio > self.MAX_OVERLAP_RATIO:
                    results.append(ValidationResult(
                        name="I8 Overlap",
                        status=ValidationStatus.FAIL,
                        message=f"'{room1.label}' and '{room2.label}' overlap by {overlap_ratio*100:.1f}%",
                        details={"room1": room1.label, "room2": room2.label, "overlap": overlap_ratio}
                    ))
        
        if not results:
            results.append(ValidationResult(
                name="I8 Overlap",
                status=ValidationStatus.PASS,
                message="No significant room overlaps detected",
                details={}
            ))
        
        return results
    
    def _bboxes_overlap(self, bb1: tuple, bb2: tuple) -> bool:
        """Quick check if two bounding boxes overlap."""
        x1, y1, w1, h1 = bb1
        x2, y2, w2, h2 = bb2
        
        return not (x1 + w1 < x2 or x2 + w2 < x1 or y1 + h1 < y2 or y2 + h2 < y1)
    
    def _check_coverage(self, rooms: list, image_area: int) -> ValidationResult:
        """INVARIANT 8: Total room area should be reasonable."""
        total_area = sum(r.area_pixels for r in rooms)
        coverage = total_area / image_area if image_area > 0 else 0
        
        if self.MIN_COVERAGE <= coverage <= self.MAX_COVERAGE:
            return ValidationResult(
                name="I9 Coverage",
                status=ValidationStatus.PASS,
                message=f"Rooms cover {coverage*100:.1f}% of image ({self.MIN_COVERAGE*100:.0f}-{self.MAX_COVERAGE*100:.0f}% expected)",
                details={"total_area": total_area, "image_area": image_area, "coverage": coverage}
            )
        elif coverage < self.MIN_COVERAGE:
            return ValidationResult(
                name="I9 Coverage",
                status=ValidationStatus.WARN,
                message=f"Rooms cover only {coverage*100:.1f}% - might be missing rooms",
                details={"total_area": total_area, "image_area": image_area, "coverage": coverage}
            )
        else:
            return ValidationResult(
                name="I9 Coverage",
                status=ValidationStatus.WARN,
                message=f"Rooms cover {coverage*100:.1f}% - possible overlap or wrong detection",
                details={"total_area": total_area, "image_area": image_area, "coverage": coverage}
            )
    
    def _check_room_count(self, rooms: list) -> ValidationResult:
        """INVARIANT 9: Should have found at least one room."""
        n = len(rooms)
        
        if n >= 1:
            return ValidationResult(
                name="I10 Room Count",
                status=ValidationStatus.PASS,
                message=f"Found {n} room(s)",
                details={"count": n}
            )
        else:
            return ValidationResult(
                name="I10 Room Count",
                status=ValidationStatus.FAIL,
                message="No rooms detected!",
                details={"count": 0}
            )
