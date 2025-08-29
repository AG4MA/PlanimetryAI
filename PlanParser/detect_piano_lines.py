import os
import cv2
import pytesseract

# Draw piano lines and save debug image

def detect_piano_lines(input_image_path, output_image_path, lines_info_path):
    if os.path.exists(output_image_path) and os.path.exists(lines_info_path):
        print(f"[SKIP] {output_image_path} and {lines_info_path} already exist.")
        return
    if not os.path.exists(input_image_path):
        print(f"File non trovato: {input_image_path}")
        return
    img = cv2.imread(input_image_path)
    if img is None:
        print("Impossibile leggere l'immagine.")
        return
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    data = pytesseract.image_to_data(gray, lang="ita+eng", config="--psm 6", output_type=pytesseract.Output.DICT)
    img_h, img_w = img.shape[:2]
    piano_lines = []
    for i in range(len(data['text'])):
        word = data['text'][i]
        if word and 'piano' in word.lower():
            x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
            # Horizontal line just above the word (no overlap)
            margin_above = 2
            line_y = max(0, y - margin_above)
            # Margins around the word to keep a small gap
            gap_side = 2  # horizontal gap on each side of the word where line is omitted
            left_seg_end = max(0, x - gap_side)
            right_seg_start = min(x + w + gap_side, img_w - 1)
            # Draw left segment
            if left_seg_end > 0:
                cv2.line(img, (0, line_y), (left_seg_end, line_y), (0, 255, 0), 2)
            # Draw right segment
            if right_seg_start < img_w - 1:
                cv2.line(img, (right_seg_start, line_y), (img_w - 1, line_y), (0, 255, 0), 2)
            # Draw the word rectangle and label
            cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.putText(img, word, (x, max(0, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            piano_lines.append(line_y)
    if piano_lines:
        cv2.imwrite(output_image_path, img)
        print(f"[DONE] Saved: {output_image_path}")
        piano_lines_sorted = sorted(piano_lines)
        with open(lines_info_path, "w") as f:
            for y in piano_lines_sorted:
                f.write(f"{y}\n")
        print(f"[DONE] Saved: {lines_info_path}")
    else:
        print("No 'piano' lines found.")

if __name__ == "__main__":
    detect_piano_lines(
        input_image_path="base_rectangle.png",
        output_image_path="base_rectangle_piano_lines.png",
        lines_info_path="piano_lines.txt",
    )
