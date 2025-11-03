#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collector.py

Invoca repetidamente test_extractor.py (máx 25 preguntas por ejecución),
fusiona preguntas únicas en un JSON y (opcionalmente) imprime las preguntas
al estilo del original.

Ejemplos:
    python3 collector.py \
        --extractor /mnt/data/test_extractor.py \
        --out all_answers.json \
        --preguntas 25 \
        --target 200 \
        --delay 1.0 \
        --print-batch \
        --print-final

Flags de impresión:
    --print-batch : imprime cada pregunta nueva a medida que se añade.
    --print-final : imprime todas las preguntas al finalizar.
"""

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any

# ---------- utilidades JSON ----------
def load_json(path: str):
    p = Path(path)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))

def save_json(path: str, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- formateo estilo original ----------
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def _normalize_options(opts: Any) -> List[Tuple[str, str]]:
    """
    Devuelve lista de pares (letra, texto).
    - Si viene dict: respeta claves (A,B,C,...) en orden alfabético.
    - Si viene lista: asigna A,B,C,... en orden.
    - Si viene cualquier otra cosa, devuelve lista vacía.
    """
    if isinstance(opts, dict):
        # ordenar por clave (A,B,C,...)
        items = sorted(opts.items(), key=lambda kv: kv[0])
        return [(k, str(v)) for k, v in items]
    if isinstance(opts, list):
        out = []
        for i, v in enumerate(opts):
            letter = _LETTERS[i] if i < len(_LETTERS) else f"({i+1})"
            out.append((letter, str(v)))
        return out
    return []

def _pick_display_index(p: dict, fallback_num: int) -> Tuple[str, str]:
    """
    Construye el prefijo '01) 1) ' si hay campo idx/numero, etc.
    Devuelve (prefijo_01, sufijo_idx) sin espacios al final.
    """
    # índice acumulado con padding 2
    pref01 = f"{fallback_num:02d})"
    # si la pregunta trae su propio índice, muéstralo como 'X)'
    own_idx = p.get("idx") or p.get("numero") or p.get("n")
    if isinstance(own_idx, (int, str)) and str(own_idx).strip():
        return pref01, f"{str(own_idx).strip()})"
    return pref01, ""  # sin segundo índice

def format_question_like_original(p: dict, ordinal: int) -> str:
    """
    Genera el bloque de texto:
        01) 1) Pregunta...
           * A. Opción
             B. Opción
    """
    pref01, idx2 = _pick_display_index(p, ordinal)
    qtext = str(p.get("pregunta") or p.get("enunciado") or p.get("question") or "").strip()
    head_parts = [pref01]
    if idx2:
        head_parts.append(idx2)
    head = " ".join(head_parts)
    lines = [f"{head} {qtext}"]

    # opciones
    options = _normalize_options(p.get("opciones") or p.get("opciones_texto") or p.get("answers") or p.get("respuestas"))
    if options:
        for i, (letter, text) in enumerate(options):
            lines.append(f"   {letter}. {text}")
    return "\n".join(lines)

def print_questions_block(questions: List[dict], start_ordinal: int = 1):
    """
    Imprime un bloque de preguntas consecutivas desde un ordinal dado.
    """
    for i, q in enumerate(questions, start=start_ordinal):
        print(format_question_like_original(q, i))
        print()  # línea en blanco

# ---------- merge ----------
def merge_into_map(existing_map: Dict[str, dict], extracted_list: List[dict]) -> Tuple[int, int, List[dict]]:
    """
    existing_map: dict id_pregunta -> objeto pregunta
    extracted_list: lista como exporta test_extractor.py
    Devuelve (nuevos_insertados, total_after, lista_nuevos_en_orden)
    """
    new_items = []
    for p in extracted_list:
        key = p.get("id_pregunta") or p.get("id") or None
        if not key:
            # fallback reproducible: idx + pregunta
            key = f"idx{p.get('idx')}_{p.get('pregunta') or p.get('enunciado')}"
        if key not in existing_map:
            existing_map[key] = p
            new_items.append(p)
    return len(new_items), len(existing_map), new_items

# ---------- invocación extractor ----------
def run_extractor(extractor_path: str, preguntas: int, tipo: str = "testArb", tmp_out: str = "", sleep_between: float = 0.3):
    """
    Ejecuta test_extractor.py y genera un JSON temporal.
    Devuelve (lista_preguntas or None, tmp_out, proc)
    """
    if tmp_out is None:
        temp = tempfile.NamedTemporaryFile(prefix="te_", suffix=".json", delete=False)
        tmp_out = temp.name
        temp.close()
    cmd = [
        "python3", extractor_path,
        "--preguntas", str(preguntas),
        "--export-json", tmp_out,
        "--tipo", tipo,
        "--sleep", str(sleep_between)
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        print(f"[ERROR] ejecución del extractor falló: {e}")
        return None, tmp_out, None

    if proc.returncode != 0:
        print(f"[ERROR] extractor devolvió código {proc.returncode}")
        if proc.stdout:
            print("stdout:", proc.stdout.strip())
        if proc.stderr:
            print("stderr:", proc.stderr.strip())
        return None, tmp_out, proc

    try:
        data = load_json(tmp_out)
        return data, tmp_out, proc
    except Exception as e:
        print(f"[ERROR] no pude leer JSON generado por extractor ({tmp_out}): {e}")
        if proc.stdout:
            print("stdout:", proc.stdout.strip())
        if proc.stderr:
            print("stderr:", proc.stderr.strip())
        return None, tmp_out, proc

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", required=True, help="Ruta a test_extractor.py")
    ap.add_argument("--out", default="all_answers.json", help="Salida JSON agregada")
    ap.add_argument("--preguntas", type=int, default=25, help="Preguntas por invocación")
    ap.add_argument("--tipo", default="testArb", help="Tipo que pasa al extractor (testArb/testOf)")
    ap.add_argument("--target", type=int, default=0, help="Nº objetivo de preguntas únicas (0 = desactivar)")
    ap.add_argument("--max-iter", type=int, default=0, help="Máx invocaciones (0 = sin límite)")
    ap.add_argument("--stop-after-no-new", type=int, default=5, help="Parar si N iteraciones seguidas no añaden nuevas")
    ap.add_argument("--delay", type=float, default=1.0, help="Segs entre invocaciones")

    # Opciones de impresión
    ap.add_argument("--print-batch", dest="print_batch", action="store_true", help="Imprime cada pregunta nueva cuando se agrega")
    ap.add_argument("--print-final", dest="print_final", action="store_true", help="Imprime todas las preguntas al finalizar")
    args = ap.parse_args()

    extractor = Path(args.extractor)
    if not extractor.exists():
        raise SystemExit(f"Extractor no encontrado: {extractor}")

    out_path = Path(args.out)

    # cargar progreso previo (si existe)
    existing_map: Dict[str, dict] = {}
    if out_path.exists():
        try:
            prev = load_json(str(out_path))
            for p in prev:
                key = p.get("id_pregunta") or p.get("id") or f"idx{p.get('idx')}_{p.get('pregunta') or p.get('enunciado')}"
                existing_map[key] = p
            print(f"[OK] Cargadas {len(existing_map)} preguntas desde {out_path}")
        except Exception as e:
            print(f"[WARN] no pude leer {out_path}: {e} -- comenzando desde 0")

    iter_count = 0
    no_new_streak = 0

    while True:
        iter_count += 1
        if args.max_iter and iter_count > args.max_iter:
            print("[INFO] alcanzado max-iter. Parando.")
            break

        print(f"[INFO] Iteración #{iter_count}: llamando extractor (preguntas={args.preguntas}) ...")
        extracted, tmpfile, proc = run_extractor(str(extractor), args.preguntas, tipo=args.tipo, sleep_between=0.3)

        if extracted is None:
            print("[WARN] extracción fallida en esta iteración. Esperando y reintentando.")
            no_new_streak += 1
        else:
            new, total, new_items = merge_into_map(existing_map, extracted)
            if new > 0:
                no_new_streak = 0
                print(f"[OK] nuevas preguntas: {new}  | total acumulado: {total}")
                # impresión por lote (solo lo nuevo), ordinal comienza en total-previo - new + 1
                if args.print_batch:
                    start_ord = total - new + 1
                    print_questions_block(new_items, start_ordinal=start_ord)
            else:
                no_new_streak += 1
                print(f"[INFO] no se añadieron preguntas nuevas en esta iteración (streak={no_new_streak})")

            # Guardar progreso inmediatamente
            save_json(str(out_path), list(existing_map.values()))
            print(f"[OK] guardado {out_path} (total={len(existing_map)})")

        # condiciones de parada
        if args.target and len(existing_map) >= args.target:
            print(f"[DONE] alcanzado target de {args.target} preguntas.")
            break
        if args.stop_after_no_new and no_new_streak >= args.stop_after_no_new:
            print(f"[DONE] no se han encontrado preguntas nuevas en {no_new_streak} iteraciones consecutivas. Parando.")
            break

        print(f"[INFO] esperando {args.delay}s antes de la siguiente iteración...")
        time.sleep(args.delay)

    # impresión final si procede (todas)
    if args.print_final:
        print("\n================== IMPRESIÓN FINAL ==================\n")
        all_questions = list(existing_map.values())
        # ordenar con heurística por idx si existe
        def _key(q):
            # intenta ordenar por idx/numero si es convertible a int, si no por pregunta
            for k in ("idx", "numero", "n"):
                v = q.get(k)
                if v is not None:
                    try:
                        return (0, int(v))
                    except Exception:
                        return (1, str(v))
            return (2, str(q.get("pregunta") or q.get("enunciado") or ""))
        all_questions.sort(key=_key)
        print_questions_block(all_questions, start_ordinal=1)

    print(f"[FIN] iteraciones: {iter_count}  preguntas totales únicas: {len(existing_map)}  salida: {out_path}")

if __name__ == "__main__":
    main()
