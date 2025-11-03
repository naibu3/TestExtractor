#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exam_solver.py

Genera un test anónimo en la web del Club del Árbitro y lo responde usando
un banco de respuestas (JSON) ya existente. NO hay aleatoriedad: elige la
opción correcta del banco por id_pregunta y, si no hay id, por texto.

Imprime por pantalla las preguntas falladas y la nota final.
Opcionalmente exporta el examen con las elecciones realizadas.

Uso:
  python3 exam_solver.py --kb all_answers.json --tipo testArb --preguntas 25 --print

Opciones:
  --kb            Ruta al JSON del banco (collector).
  --tipo          testArb / testOf (por defecto: testArb).
  --preguntas     Nº preguntas (1/5/10/25). Por defecto: 25.
  --sleep         Retardo entre peticiones (s). Por defecto: 0.3
  --print         Muestra por pantalla las falladas + nota.
  --export-json   Guarda el examen resuelto (preguntas + elegida + correcta_texto).
"""

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import requests
from bs4 import BeautifulSoup

BASE = "https://www.clubdelarbitro.com/Tests"
CONFIG_URL = f"{BASE}/configurarTestAnonimo.php?ins=0&pub=1"
ACTION_URL = f"{BASE}/mostrarTestAnonimo.php?ins=0"
GRADE_URL  = f"{BASE}/testAnonimo2.php?ins=0"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ExamSolver/1.0)",
    "Referer": CONFIG_URL
}

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def letter(i: int) -> str:
    s = ""
    i += 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s

def norm_text(s: str) -> str:
    if s is None:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

@dataclass
class Pregunta:
    idx: int
    id_pregunta: str
    pregunta: str
    opciones_val: List[str]
    opciones_texto: List[str]

# -------------------- HTTP --------------------

def http_get(session: requests.Session, url: str) -> requests.Response:
    r = session.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r

def http_post(session: requests.Session, url: str, data: dict, referer: str) -> requests.Response:
    h = HEADERS.copy()
    h["Referer"] = referer
    r = session.post(url, headers=h, data=data, timeout=20)
    r.raise_for_status()
    return r

def decode_response(r: requests.Response) -> str:
    return r.text

# -------------------- Parseo HTML --------------------

def parse_test_html(html: str) -> Tuple[List[Pregunta], Dict[int, str]]:
    soup = BeautifulSoup(html, "html.parser")
    preguntas: List[Pregunta] = []
    idx_to_name: Dict[int, str] = {}

    trs = soup.select("table table form tr")
    for tr in trs:
        hid = tr.find("input", {"type": "hidden", "name": re.compile(r"^id\d+$")})
        if not hid:
            continue
        m = re.match(r"^id(\d+)$", hid["name"])
        if not m:
            continue
        idx = int(m.group(1))
        id_pregunta = (hid.get("value") or "").strip()

        b = tr.find("b")
        enunciado = b.get_text(" ", strip=True) if b else ""

        radios = tr.find_all("input", {"type": "radio", "name": f"opcion{idx}"})
        opciones_val, opciones_texto = [], []
        for r in radios:
            val = (r.get("value") or "").strip()
            # texto hasta <br>
            txt_parts = []
            for sib in r.next_siblings:
                if getattr(sib, "name", None) == "br":
                    break
                if hasattr(sib, "get_text"):
                    txt_parts.append(sib.get_text(" ", strip=True))
                else:
                    txt_parts.append(str(sib).strip())
            txt = " ".join(p for p in txt_parts if p).strip()
            txt = re.sub(r"\s+", " ", txt)
            opciones_val.append(val)
            opciones_texto.append(txt)

        preguntas.append(Pregunta(
            idx=idx,
            id_pregunta=id_pregunta,
            pregunta=enunciado,
            opciones_val=opciones_val,
            opciones_texto=opciones_texto
        ))
        idx_to_name[idx] = f"opcion{idx}"

    return preguntas, idx_to_name

def parse_score_from_results(html: str) -> Optional[int]:
    m = re.search(r"Tienes\s+(\d+)\s+aciertos\s+sobre\s+(\d+)", html, re.I)
    return int(m.group(1)) if m else None

def parse_correct_from_results(html: str) -> Dict[int, str]:
    """
    Devuelve {idx -> texto_correcto} para las que salieron mal en ese envío.
    """
    out: Dict[int, str] = {}
    soup = BeautifulSoup(html, "html.parser")
    for b in soup.find_all("b"):
        t = b.get_text(" ", strip=True)
        m = re.match(r"(\d+)\)", t)
        if not m:
            continue
        idx_hum = int(m.group(1))
        idx = idx_hum - 1
        u = b.find_next("u", string=re.compile(r"Respuesta correcta", re.I))
        if not u:
            continue
        i = u.find_next("i")
        if not i:
            continue
        corr = i.get_text(" ", strip=True)
        corr = re.sub(r"\s*\(.*?\)\s*$", "", corr).strip()
        out[idx] = corr
    return out

# -------------------- Banco (KB) --------------------

def load_kb(path: Path) -> List[dict]:
    return json.loads(path.read_text(encoding="utf-8"))

def build_kb_indices(kb_list: List[dict]):
    by_id = {}
    by_text = {}
    for e in kb_list:
        key = e.get("id_pregunta") or e.get("id")
        if key:
            by_id[str(key)] = e
        qtext = e.get("pregunta") or e.get("enunciado") or e.get("question")
        if qtext:
            by_text.setdefault(norm_text(qtext), []).append(e)
    return by_id, by_text

def kb_get_answer_letter(entry: dict) -> Optional[str]:
    # Prioridad a campos de letra
    for k in ("correcta", "respuesta_correcta", "solution_letter", "solution"):
        v = entry.get(k)
        if isinstance(v, str) and re.fullmatch(r"[A-Za-z]", v.strip()):
            return v.strip().upper()
    # Por texto
    correct_text = entry.get("correct_text") or entry.get("respuesta") or entry.get("solucion_texto")
    if correct_text:
        opts = entry.get("opciones") or entry.get("respuestas") or entry.get("answers")
        if isinstance(opts, dict):
            for L, txt in sorted(opts.items()):
                if norm_text(str(txt)) == norm_text(str(correct_text)):
                    return L
        elif isinstance(opts, list):
            for i, txt in enumerate(opts):
                if norm_text(str(txt)) == norm_text(str(correct_text)):
                    return letter(i)
    # Índice numérico (1..)
    v = entry.get("solucion")
    if v is not None:
        try:
            i = int(v)
            if 1 <= i <= 26:
                return LETTERS[i-1]
        except Exception:
            pass
    return None

def choose_from_kb(p: Pregunta, kb_by_id, kb_by_text) -> Optional[int]:
    """
    Devuelve el índice (0..n-1) de la opción a marcar según el KB.
    Intenta por id_pregunta; si no, por texto de pregunta y luego mapeo por texto de opción.
    """
    entry = None
    if p.id_pregunta and str(p.id_pregunta) in kb_by_id:
        entry = kb_by_id[str(p.id_pregunta)]
    if entry is None:
        lst = kb_by_text.get(norm_text(p.pregunta))
        if lst:
            entry = lst[0]
    if entry is None:
        return None

    # 1) Si el KB tiene letra, mapear letra -> índice
    L = kb_get_answer_letter(entry)
    if L:
        # convertir letra a índice (A->0, B->1...)
        pos = 0
        if len(L) == 1 and L in LETTERS:
            pos = LETTERS.index(L)
            if pos < len(p.opciones_texto):
                return pos

    # 2) Si el KB tiene texto correcto, buscar en opciones_texto
    correct_text = entry.get("correct_text") or entry.get("respuesta") or entry.get("solucion_texto")
    if correct_text:
        nt = norm_text(str(correct_text))
        for i, txt in enumerate(p.opciones_texto):
            if norm_text(txt) == nt:
                return i

    return None

# -------------------- Payload --------------------

def build_payload_from_choices(preguntas: List[Pregunta],
                               chosen_positions: Dict[int, int],
                               tipo: str,
                               preguntas_n: int) -> dict:
    data = {"tipo": tipo, "preguntas": str(preguntas_n), "enviar": "Corregir test"}
    for p in preguntas:
        data[f"id{p.idx}"] = p.id_pregunta
        pos = chosen_positions.get(p.idx, 0)  # si no hay en KB, marcar A (pos 0) como fallback
        pos = max(0, min(pos, len(p.opciones_val) - 1))
        data[f"opcion{p.idx}"] = p.opciones_val[pos]
    return data

# -------------------- Impresión --------------------

def pick_display_indices(p: Pregunta, ordinal: int):
    pref01 = f"{ordinal:02d})"
    # En la página el índice humano es idx+1
    idx2 = f"{p.idx+1})"
    return pref01, idx2

def format_question_block(p: Pregunta, ordinal: int, chosen_letter: Optional[str], correct_text: Optional[str]) -> str:
    pref01, idx2 = pick_display_indices(p, ordinal)
    head = f"{pref01} {idx2} {p.pregunta}"
    lines = [head]
    for i, text in enumerate(p.opciones_texto):
        L = letter(i)
        bullet = "* " if i == 0 else "  "
        lines.append(f"   {bullet}{L}. {text}")
    if chosen_letter is not None:
        if correct_text is None:
            lines.append(f"   -> Elegida: {chosen_letter}")
        else:
            # hallar letra de la correcta a partir de su texto (para mostrar ambas)
            corr_letter = None
            for i, t in enumerate(p.opciones_texto):
                if norm_text(t) == norm_text(correct_text):
                    corr_letter = letter(i)
                    break
            verdict = "✅ CORRECTA" if corr_letter == chosen_letter else "❌ INCORRECTA"
            lines.append(f"   -> Elegida: {chosen_letter} | Correcta: {corr_letter or '?'}  {verdict}")
    return "\n".join(lines)

# -------------------- Main --------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True, help="Ruta al JSON del banco (collector)")
    ap.add_argument("--tipo", default="testArb", help="testArb/testOf")
    ap.add_argument("--preguntas", type=int, default=25, help="Número de preguntas (1/5/10/25)")
    ap.add_argument("--sleep", type=float, default=0.3, help="Retardo entre peticiones (s)")
    ap.add_argument("--print", dest="do_print", action="store_true", help="Imprime falladas y nota")
    ap.add_argument("--export-json", help="Guardar el examen resuelto en JSON")
    args = ap.parse_args()

    kb_path = Path(args.kb)
    if not kb_path.exists():
        raise SystemExit(f"KB no encontrada: {kb_path}")

    kb_list = load_kb(kb_path)
    kb_by_id, kb_by_text = build_kb_indices(kb_list)

    s = requests.Session()

    # 1) Carga de configuración
    http_get(s, CONFIG_URL)

    # 2) Generar test
    cfg_payload = {"tipo": args.tipo, "preguntas": str(args.preguntas)}
    r = http_post(s, ACTION_URL, data=cfg_payload, referer=CONFIG_URL)
    test_html = decode_response(r)

    # 3) Parsear test
    preguntas, _ = parse_test_html(test_html)
    if not preguntas:
        raise RuntimeError("No se detectaron preguntas en el HTML del test.")

    # 4) Elegir posiciones desde el KB (sin aleatoriedad)
    chosen_positions: Dict[int, int] = {}
    for p in preguntas:
        pos = choose_from_kb(p, kb_by_id, kb_by_text)
        if pos is None:
            # fallback: A (0). Puedes cambiar a "no responder" si la web lo permite (no suele).
            pos = 0
        chosen_positions[p.idx] = pos

    # 5) Enviar y corregir
    payload = build_payload_from_choices(preguntas, chosen_positions, tipo=args.tipo, preguntas_n=args.preguntas)
    r_res = http_post(s, GRADE_URL, data=payload, referer=ACTION_URL)
    res_html = decode_response(r_res)

    score = parse_score_from_results(res_html)
    correct_by_idx = parse_correct_from_results(res_html)  # solo trae las falladas

    # 6) Preparar impresión / export
    wrong_blocks = []
    aciertos = score if score is not None else 0
    total = len(preguntas)

    # Para export-json
    export_items = []

    for ord_i, p in enumerate(preguntas, start=1):
        chosen_L = letter(chosen_positions[p.idx]) if p.idx in chosen_positions else None
        corr_text = correct_by_idx.get(p.idx)  # si está, es que falló

        export_items.append({
            "idx": p.idx,
            "id_pregunta": p.id_pregunta,
            "pregunta": p.pregunta,
            "opciones": p.opciones_texto,
            "elegida_letra": chosen_L,
            "elegida_texto": p.opciones_texto[chosen_positions[p.idx]],
            "correcta_texto": corr_text  # solo en falladas (según HTML)
        })

        if corr_text:  # fallada -> imprimir bloque
            wrong_blocks.append(format_question_block(p, ord_i, chosen_L, corr_text))

    if args.do_print:
        print("\n==================== RESULTADOS DEL EXAMEN ====================\n")
        if wrong_blocks:
            print("---- PREGUNTAS FALLADAS ----\n")
            for blk in wrong_blocks:
                print(blk)
                print()
        else:
            print("No se han detectado fallos (o no se pudieron extraer desde el HTML de resultados).")
        if score is not None:
            pct = (score / total) * 100.0
            print(f"Nota: {score}/{total}  ({pct:.2f}%)")
        else:
            print("Nota: no se pudo leer la puntuación del HTML.")

    if args.export_json:
        out = {
            "tipo": args.tipo,
            "preguntas": args.preguntas,
            "score": score,
            "total": total,
            "items": export_items
        }
        Path(args.export_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Examen exportado: {args.export_json}")

    # Pequeño respiro por cortesía
    time.sleep(args.sleep)

if __name__ == "__main__":
    main()
