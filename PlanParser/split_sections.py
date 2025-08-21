import os
import cv2

def split_sections(input_image_path, lines_info_path, output_prefix="base_rectangle_section_"):
    if not os.path.exists(input_image_path):
        print(f"File non trovato: {input_image_path}")
        return
    if not os.path.exists(lines_info_path):
        print(f"File non trovato: {lines_info_path}")
        return
    img = cv2.imread(input_image_path)
    if img is None:
        print("Impossibile leggere l'immagine.")
        return
    img_h, img_w = img.shape[:2]
    with open(lines_info_path, "r") as f:
        piano_lines_sorted = [int(line.strip()) for line in f if line.strip().isdigit()]
    if not piano_lines_sorted:
        print("No piano lines found in info file.")
        return
    for i, y_top in enumerate(piano_lines_sorted):
        y_bottom = piano_lines_sorted[i + 1] if i + 1 < len(piano_lines_sorted) else img_h - 1
        section_path = f"{output_prefix}{i+1}.png"
        if os.path.exists(section_path):
            print(f"[SKIP] {section_path} already exists.")
            continue
        section_img = img[y_top:y_bottom, 0:img_w]
        cv2.imwrite(section_path, section_img)
        print(f"[DONE] Saved section image: {section_path}")

if __name__ == "__main__":
    split_sections(
        input_image_path="base_rectangle.png",
        lines_info_path="piano_lines.txt",
        output_prefix="base_rectangle_section_",
    )
