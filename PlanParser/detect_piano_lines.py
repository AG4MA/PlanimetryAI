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
            y_center = y + h // 2
            # Draw horizontal line only up to the left edge of the word (with small gap)
            gap = 4  # pixels before the word starts
            line_end_x = max(0, x - gap)
            cv2.line(img, (0, y_center), (line_end_x, y_center), (0, 255, 0), 2)
            # Now draw the word rectangle and label (uninterrupted by the line)
            cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.putText(img, word, (x, max(0, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            piano_lines.append(y_center)
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
