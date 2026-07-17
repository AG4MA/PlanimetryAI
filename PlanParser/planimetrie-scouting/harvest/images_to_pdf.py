"""Converte le planimetrie-immagine (JPG/PNG) in PDF a pagina singola.

Mette i PDF risultanti nella stessa cartella piatta PLANIMETRIE_PDF/, cosi' TUTTE
le planimetrie (native PDF + immagini convertite) stanno insieme come PDF.

- rieseguibile: salta le immagini gia' convertite;
- robusto: un'immagine corrotta non ferma il batch (viene contata e saltata);
- il PDF ha lo stesso nome base dell'immagine, con estensione .pdf.

Uso:  python -m harvest.images_to_pdf
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from .core import PLANIMETRIE_DIR

PDF_DIR = PLANIMETRIE_DIR.parent / "PLANIMETRIE_PDF"
IMG_EXT = {".jpg", ".jpeg", ".png"}


def convert() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    images = [p for p in PLANIMETRIE_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT]
    total = len(images)
    done = skipped = failed = 0
    print(f"immagini da convertire: {total}", flush=True)

    for i, img_path in enumerate(images, 1):
        out = PDF_DIR / (img_path.stem + ".pdf")
        if out.exists():
            skipped += 1
            continue
        try:
            with Image.open(img_path) as im:
                im.load()
                if im.mode in ("RGBA", "P", "LA"):
                    im = im.convert("RGB")
                elif im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(out, "PDF", resolution=200.0)
            done += 1
        except Exception as exc:  # immagine corrotta/non valida: salto, non fermo il batch
            failed += 1
            print(f"  ! salto {img_path.name}: {type(exc).__name__}: {exc}", flush=True)
        if i % 200 == 0:
            print(f"  ...{i}/{total} (convertite {done}, saltate {skipped}, errori {failed})", flush=True)

    pdf_count = sum(1 for p in PDF_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    print(f"convertite ora: {done} · gia' presenti: {skipped} · errori: {failed}", flush=True)
    print(f"TOTALE PDF nella cartella unica {PDF_DIR}: {pdf_count}", flush=True)


if __name__ == "__main__":
    convert()
