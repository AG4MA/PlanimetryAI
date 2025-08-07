import cv2
import numpy as np
import fitz
from PIL import Image
import io
import os

def render_pdf_to_image(pdf_path, zoom=3.0):
    """
    Converte la prima pagina del PDF in un'immagine ad alta risoluzione
    """
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(0)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_data))
        doc.close()
        return image
    except Exception as e:
        print(f"❌ Errore nel caricamento del PDF: {e}")
        return None

def preprocess_image(image):
    """
    Preprocessa l'immagine per migliorare il rilevamento dei bordi
    """
    # Converti in array numpy
    img_array = np.array(image)
    
    # Converti in scala di grigi
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array
    
    # Applica blur per ridurre il rumore
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # Applica threshold adattivo per migliorare il contrasto
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    
    # Applica operazioni morfologiche per pulire l'immagine
    kernel = np.ones((3, 3), np.uint8)
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)
    
    return cleaned

def detect_rectangles(processed_image):
    """
    Rileva tutti i rettangoli nell'immagine processata
    """
    # Trova i contorni
    contours, _ = cv2.findContours(
        processed_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    
    rectangles = []
    
    for contour in contours:
        # Calcola l'area del contorno
        area = cv2.contourArea(contour)
        
        # Ignora contorni troppo piccoli
        if area < 1000:  # Soglia minima per l'area
            continue
        
        # Approssima il contorno a un poligono
        epsilon = 0.02 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        
        # Se il poligono ha 4 vertici, è probabilmente un rettangolo
        if len(approx) == 4:
            # Verifica che sia convesso
            if cv2.isContourConvex(approx):
                # Calcola il bounding rectangle
                x, y, w, h = cv2.boundingRect(approx)
                
                # Calcola l'area del rettangolo
                rect_area = w * h
                
                # Calcola il rapporto aspect (per evitare rettangoli troppo stretti)
                aspect_ratio = max(w, h) / min(w, h)
                
                # Filtra rettangoli con aspect ratio ragionevole (non troppo stretti)
                if aspect_ratio < 10:
                    rectangles.append({
                        'contour': contour,
                        'approx': approx,
                        'bbox': (x, y, w, h),
                        'area': rect_area,
                        'aspect_ratio': aspect_ratio
                    })
    
    return rectangles

def find_largest_rectangle(rectangles):
    """
    Trova il rettangolo con l'area più grande
    """
    if not rectangles:
        return None
    
    # Ordina per area decrescente
    rectangles.sort(key=lambda x: x['area'], reverse=True)
    
    # Restituisce il rettangolo più grande
    return rectangles[0]

def draw_rectangle_on_image(image, rectangle_info, color=(0, 255, 0), thickness=3):
    """
    Disegna il rettangolo rilevato sull'immagine
    """
    if rectangle_info is None:
        return image
    
    x, y, w, h = rectangle_info['bbox']
    
    # Disegna il rettangolo
    cv2.rectangle(image, (x, y), (x + w, y + h), color, thickness)
    
    # Aggiungi testo con informazioni
    text = f"Area: {rectangle_info['area']}"
    cv2.putText(image, text, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    return image

def save_debug_images(original_image, processed_image, result_image, output_dir="debug_output"):
    """
    Salva le immagini di debug per l'analisi
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Salva l'immagine originale
    cv2.imwrite(f"{output_dir}/01_original.png", cv2.cvtColor(np.array(original_image), cv2.COLOR_RGB2BGR))
    
    # Salva l'immagine processata
    cv2.imwrite(f"{output_dir}/02_processed.png", processed_image)
    
    # Salva l'immagine con il rettangolo evidenziato
    cv2.imwrite(f"{output_dir}/03_result.png", cv2.cvtColor(result_image, cv2.COLOR_RGB2BGR))
    
    print(f"📁 Immagini di debug salvate in: {output_dir}/")

def main(pdf_path):
    """
    Funzione principale per rilevare il rettangolo più grande
    """
    print(f"🔍 Analizzando: {pdf_path}")
    
    # 1. Carica il PDF
    image = render_pdf_to_image(pdf_path)
    if image is None:
        return
    
    print(f"✅ PDF caricato, dimensione: {image.size}")
    
    # 2. Preprocessa l'immagine
    processed = preprocess_image(image)
    print("✅ Immagine preprocessata")
    
    # 3. Rileva i rettangoli
    rectangles = detect_rectangles(processed)
    print(f"✅ Trovati {len(rectangles)} rettangoli candidati")
    
    # 4. Trova il più grande
    largest = find_largest_rectangle(rectangles)
    
    if largest:
        x, y, w, h = largest['bbox']
        print(f"🎯 Rettangolo più grande trovato:")
        print(f"   Posizione: x={x}, y={y}")
        print(f"   Dimensioni: {w}x{h} pixel")
        print(f"   Area: {largest['area']} pixel²")
        print(f"   Aspect ratio: {largest['aspect_ratio']:.2f}")
        
        # 5. Disegna il risultato
        result_image = draw_rectangle_on_image(np.array(image), largest)
        
        # 6. Salva le immagini di debug
        save_debug_images(image, processed, result_image)
        
        return largest
    else:
        print("❌ Nessun rettangolo valido trovato")
        return None

if __name__ == "__main__":
    pdf_path = "./data/scheda_catastale.pdf"
    result = main(pdf_path)
