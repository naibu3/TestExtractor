#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extrae preguntas/opciones del test anónimo del Club del Árbitro, y deduce
la respuesta correcta de TODAS las preguntas incluso si el HTML de resultados
no la muestra (porque acertaste en el envío base).

NOVEDAD: El CSV conserva TODAS las opciones del original.
- El encabezado añade columnas A, B, C, ... hasta el número máximo de opciones
  que haya en alguna pregunta.
- Cada fila coloca las opciones de esa pregunta y deja vacío si tiene menos.

Estrategia:
  1) Envío base: todo "A" -> score_base.
  2) Parsear "Respuesta correcta" de las falladas.
  3) Para las restantes, sondeo por puntuación: variar UNA pregunta cada vez
     probando B, C, ...; si la puntuación sube, esa opción es la correcta.
     Si nunca sube, A era la correcta.

Salida: CSV/JSON con "correcta" (letra) y "correcta_texto".
"""

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from typing import List, Dict, Tuple
import requests
from bs4 import BeautifulSoup

BASE = "https://www.clubdelarbitro.com/Tests"
CONFIG_URL = f"{BASE}/configurarTestAnonimo.php?ins=0&pub=1"
ACTION_URL = f"{BASE}/mostrarTestAnonimo.php?ins=0"   # página que genera el test y a la que se hace POST inicial
GRADE_URL  = f"{BASE}/testAnonimo2.php?ins=0"         # página de corrección

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TestExtractor/1.1)",
    "Referer": CONFIG_URL
}

# Generador de letras A..Z (y más si hiciera falta)
def letter(i: int) -> str:
    # A, B, C... Z, AA, AB... por si existieran >26 (poco probable)
    s = ""
    i0 = i
    i += 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s

@dataclass
class Pregunta:
    idx: int
    id_pregunta: str
    pregunta: str
    opciones_val: List[str]      # value del radio en el form
    opciones_texto: List[str]    # texto visible de cada opción
    correcta_letra: str = ""     # A/B/C...
    correcta_texto: str = ""     # texto literal de la opción correcta

# -------------------- HTTP helpers --------------------

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
    # Devolver .text según lo detectado por requests/servidor (no forzamos re-codificación)
    return r.text

# -------------------- Parsing --------------------

def parse_test_html(html: str) -> Tuple[List[Pregunta], Dict[int, str]]:
    """
    Parsea el HTML del test (mostrarTestAnonimo.php) y devuelve:
      - lista de Pregunta (con idx, id, enunciado, opciones val/texto)
      - map idx -> 'opcion{idx}'
    """
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

        # Enunciado visible
        b = tr.find("b")
        enunciado = b.get_text(" ", strip=True) if b else ""

        # Opciones
        radios = tr.find_all("input", {"type": "radio", "name": f"opcion{idx}"})
        opciones_val, opciones_texto = [], []
        for r in radios:
            val = (r.get("value") or "").strip()
            # texto de la opción: concatenar hasta el <br>
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

def parse_correct_from_results(html: str) -> Dict[int, str]:
    """
    Extrae {idx -> texto_correcto} del HTML de resultados.
    OJO: solo aparece en preguntas FALLADAS en ese envío.
    """
    out: Dict[int, str] = {}
    soup = BeautifulSoup(html, "html.parser")

    for b in soup.find_all("b"):
        t = b.get_text(" ", strip=True)
        m = re.match(r"(\d+)\)", t)
        if not m:
            continue
        idx_humano = int(m.group(1))
        idx = idx_humano - 1

        u = b.find_next("u", string=re.compile(r"Respuesta correcta", re.I))
        if not u:
            continue
        i = u.find_next("i")
        if not i:
            continue
        corr = i.get_text(" ", strip=True)
        # eliminar trailing "(ART...)" o similares
        corr = re.sub(r"\s*\(.*?\)\s*$", "", corr).strip()
        out[idx] = corr
    return out

def parse_score_from_results(html: str) -> int | None:
    m = re.search(r"Tienes\s+(\d+)\s+aciertos\s+sobre\s+(\d+)", html, re.I)
    return int(m.group(1)) if m else None

# -------------------- Payload builders --------------------

def build_payload_with_choice(preguntas: List[Pregunta],
                              base_choice_idx: int,
                              override_idx: int,
                              override_pos: int,
                              tipo: str,
                              preguntas_n: int) -> dict:
    """
    Todas con 'base_choice_idx' (0=A), salvo la pregunta 'override_idx' que
    toma 'override_pos'.
    """
    data = {"tipo": tipo, "preguntas": str(preguntas_n), "enviar": "Corregir test"}
    for p in preguntas:
        data[f"id{p.idx}"] = p.id_pregunta
        pos = base_choice_idx
        if p.idx == override_idx:
            pos = override_pos
        pos = max(0, min(pos, len(p.opciones_val) - 1))
        data[f"opcion{p.idx}"] = p.opciones_val[pos]
    return data

# -------------------- Main logic --------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", default="testArb", help="testArb/testOf")
    ap.add_argument("--preguntas", type=int, default=25, help="Número de preguntas (1/5/10/25)")
    ap.add_argument("--export-csv", help="Ruta CSV de salida")
    ap.add_argument("--export-json", help="Ruta JSON de salida")
    ap.add_argument("--sleep", type=float, default=0.3, help="Retardo entre peticiones (seg)")
    args = ap.parse_args()

    s = requests.Session()

    # 1) Cargar página de configuración
    http_get(s, CONFIG_URL)

    # 2) Generar test del tipo/preguntas
    cfg_payload = {"tipo": args.tipo, "preguntas": str(args.preguntas)}
    r = http_post(s, ACTION_URL, data=cfg_payload, referer=CONFIG_URL)
    test_html = decode_response(r)

    # 3) Parsear test
    preguntas, _ = parse_test_html(test_html)
    if not preguntas:
        raise RuntimeError("No se detectaron preguntas en el HTML del test.")

    # 4) Envío base: todo A (pos 0)
    base_payload = build_payload_with_choice(
        preguntas=preguntas,
        base_choice_idx=0,
        override_idx=-1,
        override_pos=0,
        tipo=args.tipo,
        preguntas_n=args.preguntas
    )
    r_res = http_post(s, GRADE_URL, data=base_payload, referer=ACTION_URL)
    res_html = decode_response(r_res)
    score_base = parse_score_from_results(res_html)
    if score_base is None:
        raise RuntimeError("No pude leer el marcador base en resultados.")

    # 5) Correctas que el HTML imprime (solo falladas)
    correct_texts = parse_correct_from_results(res_html)  # {idx -> texto_correcto}

    # 6) Deducción por puntuación para las que faltan
    for p in preguntas:
        if p.idx in correct_texts:
            continue  # ya conocida
        best_pos = 0
        best_score = score_base
        for pos in range(1, len(p.opciones_val)):
            payload = build_payload_with_choice(
                preguntas=preguntas,
                base_choice_idx=0,
                override_idx=p.idx,
                override_pos=pos,
                tipo=args.tipo,
                preguntas_n=args.preguntas
            )
            r_try = http_post(s, GRADE_URL, data=payload, referer=ACTION_URL)
            html_try = decode_response(r_try)
            sc = parse_score_from_results(html_try)
            if sc is not None and sc > best_score:
                best_score = sc
                best_pos = pos
            time.sleep(args.sleep)
        correct_texts[p.idx] = p.opciones_texto[best_pos]

    # 7) Completar letra/texto correcto en estructura Pregunta
    for p in preguntas:
        # localizar posición correcta por texto (exacto o con trim)
        try:
            pos = p.opciones_texto.index(correct_texts[p.idx])
        except ValueError:
            pos = next((i for i, t in enumerate(p.opciones_texto)
                        if t.strip() == correct_texts[p.idx].strip()), 0)
        p.correcta_letra = letter(pos)
        p.correcta_texto = p.opciones_texto[pos]

    # 8) Exportar
    # 8.1 JSON (ya conserva todas las opciones)
    if args.export_json:
        out = []
        for p in preguntas:
            out.append({
                "idx": p.idx,
                "id_pregunta": p.id_pregunta,
                "pregunta": p.pregunta,
                "opciones": p.opciones_texto,
                "correcta": p.correcta_letra,
                "correcta_texto": p.correcta_texto,
            })
        with open(args.export_json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"[OK] JSON exportado: {args.export_json}")

    # 8.2 CSV DINÁMICO (todas las opciones)
    if args.export_csv:
        max_opts = max(len(p.opciones_texto) for p in preguntas)
        header = ["idx", "id_pregunta", "pregunta"]
        header += [letter(i) for i in range(max_opts)]  # A.. hasta max
        header += ["correcta", "correcta_texto"]
        with open(args.export_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            for p in preguntas:
                row = [p.idx, p.id_pregunta, p.pregunta]
                row += p.opciones_texto + [""] * (max_opts - len(p.opciones_texto))
                row += [p.correcta_letra, p.correcta_texto]
                w.writerow(row)
        print(f"[OK] CSV exportado: {args.export_csv}")

    # Sin export: salida legible en consola
    if not args.export_csv and not args.export_json:
        for p in preguntas:
            print(f"{p.idx+1:02d}) {p.pregunta}")
            for i, t in enumerate(p.opciones_texto):
                flag = "*" if letter(i) == p.correcta_letra else " "
                print(f"   {flag} {letter(i)}. {t}")
            print()

if __name__ == "__main__":
    main()
