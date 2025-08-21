import os
import cv2

def crop_base_rectangle_from_debug(debug_image_path, output_cropped_path, inner_padding_px=5):
    if os.path.exists(output_cropped_path):
        print(f"[SKIP] {output_cropped_path} already exists.")
        return
    if not os.path.exists(debug_image_path):
        print(f"File non trovato: {debug_image_path}")
        return
    image_bgr = cv2.imread(debug_image_path)
    if image_bgr is None:
        print("Impossibile leggere l'immagine di debug.")
        return
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lower_green = (40, 100, 80)
    upper_green = (85, 255, 255)
    green_mask = cv2.inRange(hsv, lower_green, upper_green)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    green_mask = cv2.dilate(green_mask, kernel, iterations=1)
    ys, xs = cv2.findNonZero(green_mask) or ([], [])
    if len(xs) == 0 or len(ys) == 0:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 150)
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_rect = None
        max_area = 0
        for cnt in contours:
            approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                x, y, w, h = cv2.boundingRect(approx)
                area = w * h
                if area > max_area:
                    max_area = area
                    best_rect = (x, y, w, h)
        if best_rect is None:
            print("Nessun rettangolo trovato nel fallback.")
            return
        x, y, w, h = best_rect
        x1, y1, x2, y2 = x, y, x + w, y + h
    else:
        xs = [pt[0][0] for pt in ys]
        ys = [pt[0][1] for pt in ys]
        x1, x2 = int(min(xs)), int(max(xs))
        y1, y2 = int(min(ys)), int(max(ys))
    x1_in = max(x1 + inner_padding_px, 0)
    y1_in = max(y1 + inner_padding_px, 0)
    x2_in = min(x2 - inner_padding_px, image_bgr.shape[1])
    y2_in = min(y2 - inner_padding_px, image_bgr.shape[0])
    if x2_in <= x1_in or y2_in <= y1_in:
        print("Bounding box non valida dopo il padding interno.")
        return
    cropped = image_bgr[y1_in:y2_in, x1_in:x2_in]
    cv2.imwrite(output_cropped_path, cropped)
    print(f"[DONE] Saved: {output_cropped_path}")

if __name__ == "__main__":
    crop_base_rectangle_from_debug(
        debug_image_path="largest_rect_debug.png",
        output_cropped_path="base_rectangle.png",
        inner_padding_px=5,
    )
