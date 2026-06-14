#!/usr/bin/env python3
"""
test_cut.py — Seedance 2.0 cut-behaviour probe (BytePlus ARK).

Scopo: verificare se Seedance 2.0 via ARK rispetta i timestamp e produce uno
STACCO NETTO tra due @Image legate a beat diversi, oppure se le impasta
(slideshow/morph). Chiama direttamente generate_video del progetto -> usa il
payload reale e SALTA builder + refiner LLM. L'unica variabile e' prompt+immagini.

USO:
    cd /Users/alessiovalori/arkitect_agent           # dove vive generator.py
    export ARK_API_KEY="..."                          # se non gia' nel tuo env
    export SEEDANCE_2_MODEL_ID="dreamina-seedance-2-0-260128"   # model id CORRETTO
    python test_cut.py path/to/img1.jpg path/to/img2.jpg

NOTE:
  - img1  -> @Image 1 (the man)   |  img2 -> @Image 2 (the woman)
    L'ordine degli argomenti = ordine dei tag @Image N.
  - Scegli DUE immagini volutamente diversissime (soggetto diverso, ambiente
    diverso, colore dominante diverso) cosi' uno stacco e' inconfondibile da un blend.
  - Se torna ModelNotFound: il model id e' sbagliato. Correggi SEEDANCE_2_MODEL_ID
    con la stringa esatta dal tuo console ModelArk prima di concludere alcunche'.
"""

import os
import sys
import json

# generate_video del progetto (deve essere importabile dalla cwd)
try:
    from generator import generate_video
except Exception as e:
    print(f"[FATAL] Non riesco a importare generate_video da generator.py: {e}")
    print("Esegui lo script dalla cartella che contiene generator.py.")
    sys.exit(1)


class LocalFile:
    """Shim minimale per imitare l'UploadedFile di Streamlit che generate_video si aspetta."""
    def __init__(self, path):
        self.name = os.path.basename(path)
        ext = path.lower().rsplit(".", 1)[-1]
        self.type = "image/png" if ext == "png" else "image/jpeg"
        with open(path, "rb") as f:
            self._data = f.read()

    def getvalue(self):
        return self._data


# ── Soggetti (NESSUN volto: oggetti inanimati). Swappa qui se le tue immagini sono altro.
SUBJECT_1 = "the car"
SUBJECT_2 = "the bicycle"

# ── Prompt RAW (tre paragrafi, regole anti-ambiguita' del SKILL sd2-pe) ──────────
PROMPT = f"""[Global settings]
@Image 1 ({SUBJECT_1}): an object whose form, colour and details are locked to @Image 1.
@Image 2 ({SUBJECT_2}): an object whose form, colour and details are locked to @Image 2.
Two completely separate scenes joined by one single hard cut. No people, no faces.

[Time-slice storyboard]
0-2.5s: @Image 1 ({SUBJECT_1}) on a sunlit empty coastal road at midday. Camera: slow push-in. Bright natural daylight.
Hard cut at 2.5s.
2.5-5s: @Image 2 ({SUBJECT_2}) on a rainy neon-lit city street at night. Camera: fixed. Cold blue and magenta neon light.

[Quality & constraints]
4K HD, rich detail, cinematic and photorealistic. A single hard cut at 2.5s with NO dissolve, morph or blending between the two objects or the two locations; @Image 1 ({SUBJECT_1}) appears only in the first slice, @Image 2 ({SUBJECT_2}) only in the second. No people, no faces. Objects stable and not distorted, no clipping."""


def main():
    if len(sys.argv) < 3:
        print("USO: python test_cut.py img1.(jpg|png) img2.(jpg|png)")
        sys.exit(1)

    p1, p2 = sys.argv[1], sys.argv[2]
    for p in (p1, p2):
        if not os.path.exists(p):
            print(f"[FATAL] File non trovato: {p}")
            sys.exit(1)

    model_id = os.getenv("SEEDANCE_2_MODEL_ID")  # passato esplicito -> bypassa il default
    img1, img2 = LocalFile(p1), LocalFile(p2)

    print("── Seedance 2.0 cut-test ──────────────────────────────")
    print(f"  @Image 1 ({SUBJECT_1})   -> {p1}")
    print(f"  @Image 2 ({SUBJECT_2}) -> {p2}")
    print(f"  model_id             -> {model_id or '(default di generator.py)'}")
    print("  res 1080p | 16:9 | 5s | refiner: OFF (chiamata diretta)")
    print("  Invio task e attendo (puo' richiedere qualche minuto)...\n")

    result = generate_video(
        prompt_text=PROMPT,
        scene_description="cut_test",
        images=[img1, img2],
        resolution="1080p",
        aspect_ratio="16:9",
        duration=5,
        model_id=model_id,        # None -> usa il default interno; meglio settarlo via env
    )

    print("── RISULTATO ──────────────────────────────────────────")
    if isinstance(result, dict):
        print(json.dumps(result, indent=2, ensure_ascii=False))
        vp = result.get("video_path")
        if vp:
            print(f"\nVideo salvato in: {vp}")
        print("\nApri il clip e valuta col rubric (vedi chat).")
    else:
        # generate_video ritorna una stringa di errore in caso di problema
        print(f"ERRORE / messaggio non-dict:\n{result}")
        if "ModelNotFound" in str(result) or "not found" in str(result).lower():
            print("\n>> Probabile model id sbagliato. Correggi SEEDANCE_2_MODEL_ID e rilancia.")


if __name__ == "__main__":
    main()
