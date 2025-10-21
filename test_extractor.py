#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import csv
import json
import html
import argparse
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag, NavigableString

BASE         = "https://www.clubdelarbitro.com/"
CONFIG_URL   = "https://www.clubdelarbitro.com/Tests/configurarTestAnonimo.php?ins=0&pub=1"
ACTION_URL   = "https://www.clubdelarbitro.com/Tests/mostrarTestAnonimo.php?ins=0"
GRADE_URL    = "https://www.clubdelarbitro.com/Tests/testAnonimo2.php?ins=0"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# -------------------- HTTP helpers --------------------

def http_get(s: requests.Session, url: str, referer: str | None = None):
    h = HEADERS.copy()
    if referer: h["Referer"] = referer
    r = s.get(url, headers=h, timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r

def http_post(s: requests.Session, url: str, data: dict, referer: str | None = None):
    h = HEADERS.copy()
    if referer: h["Referer"] = referer
    r = s.post(url, headers=h, data=data, timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r

def decode_response(resp: requests.Response) -> str:
    """
    Devuelve el HTML decodificado con el charset correcto.
    Si detecta ISO-8859-1 en meta o cabeceras, fuerza esa decodificación.
    """
    raw = resp.content  # bytes
    ctype = (resp.headers.get("content-type") or "").lower()
    head = raw[:2048].decode("ascii", errors="ignore").lower()

    enc = None
    # meta charset
    m = re.search(r'charset\s*=\s*([a-z0-9_\-]+)', head)
    if m:
        enc = m.group(1).strip()
    # header
    if not enc:
        m2 = re.search(r'charset\s*=\s*([a-z0-9_\-]+)', ctype)
        if m2:
            enc = m2.group(1).strip()
    # fallback
    if not enc:
        enc = resp.apparent_encoding or resp.encoding or "utf-8"

    if enc.lower() in ("iso-8859-1", "latin-1", "latin1", "iso8859-1"):
        enc = "iso-8859-1"

    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")

def save_debug(html_str: str, path: str, print_first=False, print_full=False, label="HTML"):
    Path(path).write_text(html_str, encoding="utf-8")
    print(f"[DEBUG] {label} guardado en: {path} ({len(html_str)} bytes)")
    if print_full:
        print("\n-----", label, "COMPLETO -----\n", html_str, "\n----- FIN -----\n")
    elif print_first:
        snippet = re.sub(r"\s+", " ", html_str[:1200]).strip()
        print(f"[DEBUG] {label} (primeros 1200 chars): {snippet}")


# -------------------- Normalización / matching (para comparar) --------------------

def normalize_txt_strict(s: str) -> str:
    if s is None:
        return ""
    # Decodifica entidades para comparar mejor
    s = html.unescape(s)
    # Normaliza comillas
    s = (s.replace("“", '"').replace("”", '"')
           .replace("’", "'").replace("‘", "'"))
    s = s.replace('""""', '"').replace('"""', '"').replace("''", "'")
    # Quita referencias finales (ART, IO, RJ, etc.)
    s = re.sub(
        r"\s*\((art|arts?|art[íi]culo|ejemplo|io|rj|situaci[oó]n|sit|v[0-9._-]+)[^)]+\)\s*$",
        "", s, flags=re.I
    )
    # Quita diacríticos SOLO para comparar
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')
    s = s.lower()
    s = s.strip().rstrip(".;:¡!¿?[]()")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def best_option_match(correct_text: str, opciones_texto: list[str]) -> int:
    target = normalize_txt_strict(correct_text)
    opts_norm = [normalize_txt_strict(x) for x in opciones_texto]

    # exacto
    for i, o in enumerate(opts_norm):
        if o == target:
            return i
    # inclusión
    for i, o in enumerate(opts_norm):
        if o and (o in target or target in o):
            return i
    # fuzzy
    best_i, best_r = -1, -1.0
    for i, o in enumerate(opts_norm):
        r = SequenceMatcher(None, o, target).ratio()
        if r > best_r:
            best_r, best_i = r, i
    if best_r >= 0.80:
        return best_i
    return best_i


# -------------------- Limpieza para SALIDA visible --------------------

def clean_visible_text(s: str) -> str:
    """Limpieza ligera para SALIDA (conserva tildes)."""
    s = html.unescape(s)  # entidades → caracteres reales con tildes
    s = s.replace('""""', '"').replace('"""', '"').replace("''", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# -------------------- Parseo del TEST --------------------

def parse_test_form(test_html: str):
    """
    Returns:
      preguntas: list of dicts {idx, id_pregunta, pregunta, opciones_texto(list[str])}
      id_map:    {idx -> hidden id value}
      opciones_map: {idx -> list of (value, texto)}
    """
    soup = BeautifulSoup(test_html, "html.parser")

    # Form que postea a testAnonimo2.php
    form = None
    for f in soup.find_all("form"):
        act = (f.get("action") or "").lower()
        if "testanonimo2.php" in act:
            form = f
            break
    if form is None:
        forms = soup.find_all("form")
        if not forms:
            return [], {}, {}
        form = max(forms, key=lambda x: len(x.get_text()))

    # Índices por hidden id{i}
    hidden_ids = form.find_all("input", attrs={"type": "hidden", "name": re.compile(r"^id\d+$")})
    indices, id_map = [], {}
    for hid in hidden_ids:
        m = re.match(r"id(\d+)$", hid.get("name",""))
        if m:
            i = int(m.group(1))
            indices.append(i)
            id_map[i] = hid.get("value", "")
    indices = sorted(set(indices))

    preguntas, opciones_map = [], {}
    for i in indices:
        hid = form.find("input", attrs={"type": "hidden", "name": f"id{i}"})
        cont = hid.find_parent("td") if hid else form

        # Pregunta
        qtxt = ""
        btag = cont.find("b")
        if btag and btag.get_text(strip=True):
            qtxt = clean_visible_text(btag.get_text(" ", strip=True))
        else:
            raw = clean_visible_text(cont.get_text(" ", strip=True))
            qtxt = raw.split("?")[0] + "?" if "?" in raw else raw[:200]
        qtxt = re.sub(r"^\s*\d+\)\s*", "", qtxt).strip()

        # Opciones (en orden A,B,C,…)
        opciones = []
        for inp in cont.find_all("input", attrs={"type": "radio", "name": f"opcion{i}"}):
            val = inp.get("value", "")
            txt = ""
            sib = inp.next_sibling
            steps = 0
            while sib and steps < 8:
                steps += 1
                if isinstance(sib, NavigableString):
                    if str(sib).strip():
                        txt = str(sib).strip()
                        break
                elif isinstance(sib, Tag):
                    cand = sib.get_text(" ", strip=True)
                    if cand:
                        txt = cand
                        break
                sib = sib.next_sibling
            if not txt and isinstance(inp.next_sibling, str):
                txt = inp.next_sibling.strip()
            txt = clean_visible_text(txt)
            if val and txt:
                opciones.append((val, txt))

        opciones_map[i] = opciones
        preguntas.append({
            "idx": i,
            "id_pregunta": id_map.get(i, ""),
            "pregunta": qtxt,
            "opciones_texto": [t for _, t in opciones],
        })

    return preguntas, id_map, opciones_map


# -------------------- Enviar "todo A" y leer RESULTADOS --------------------

def build_all_A_payload(id_map: dict, opciones_map: dict, tipo: str, preguntas_n: str):
    data = {"tipo": tipo, "preguntas": preguntas_n, "enviar": "Corregir test"}
    for i, pid in id_map.items():
        data[f"id{i}"] = pid
    for i, opts in opciones_map.items():
        if opts:
            data[f"opcion{i}"] = opts[0][0]  # primera opción = "A"
    return data

def parse_correct_answers_from_results(result_html: str):
    """
    Extrae el texto del <i> que sigue a 'Respuesta correcta:' para cada pregunta.
    Devuelve la lista en el orden de aparición. (Texto con tildes correcto.)
    """
    def _norm_out(s: str) -> str:
        s = html.unescape(s)
        s = s.replace('""""', '"').replace('"""', '"').replace("''", "'")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    soup = BeautifulSoup(result_html, "html.parser")
    correct_texts = []

    # Buscar <u> con "Respuesta correcta" y tomar el siguiente <i>
    for u in soup.find_all("u"):
        label = _norm_out(u.get_text(" ", strip=True)).lower()
        if "respuesta correcta" not in label:
            continue

        nxt = u
        i_tag = None
        for _ in range(12):
            nxt = nxt.next_sibling if hasattr(nxt, "next_sibling") else None
            if nxt is None:
                break
            if isinstance(nxt, Tag):
                if nxt.name == "i":
                    i_tag = nxt
                    break
                found = nxt.find("i")
                if isinstance(found, Tag):
                    i_tag = found
                    break

        if i_tag is None:
            found = u.find_next("i")
            if isinstance(found, Tag):
                i_tag = found

        if i_tag is not None:
            txt = _norm_out(i_tag.get_text(" ", strip=True))
            if txt:
                correct_texts.append(txt)

    # Respaldo por regex
    if not correct_texts:
        pattern = re.compile(r"Respuesta\s*correcta\s*:.*?<i>(.*?)</i>", re.I | re.S)
        correct_texts = [_norm_out(m.group(1)) for m in pattern.finditer(result_html)]

    return correct_texts


# -------------------- Export (CSV / JSON) --------------------

def to_letter(idx0: int) -> str:
    return LETTERS[idx0] if 0 <= idx0 < len(LETTERS) else ""

def write_csv_with_correct(preguntas, correcta_letras: dict, path: str, encoding: str = "utf-8-sig"):
    # UTF-8 con BOM por defecto (ideal para Excel)
    max_ops = max((len(p["opciones_texto"]) for p in preguntas), default=0)
    fieldnames = ["id_pregunta", "pregunta"] + [f"opcion_{k}" for k in range(1, max_ops+1)] + ["correcta"]

    with open(path, "w", encoding=encoding, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for p in preguntas:
            row = {
                "id_pregunta": p["id_pregunta"],
                "pregunta": p["pregunta"],
                "correcta": correcta_letras.get(p["idx"], ""),
            }
            for k, txt in enumerate(p["opciones_texto"], start=1):
                row[f"opcion_{k}"] = txt
            w.writerow(row)
    print(f"[OK] CSV creado: {path} (encoding={encoding}, preguntas: {len(preguntas)})")

def write_json_with_correct(preguntas, correcta_letras: dict, correcta_textos: dict, path: str,
                            encoding: str = "utf-8"):
    data = []
    for p in preguntas:
        idx = p["idx"]
        data.append({
            "id_pregunta": p["id_pregunta"],
            "pregunta": p["pregunta"],
            "opciones": p["opciones_texto"],
            "correcta": correcta_letras.get(idx, ""),
            "correcta_texto": correcta_textos.get(idx, "")
        })
    with open(path, "w", encoding=encoding) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON creado: {path} (encoding={encoding}, preguntas: {len(data)})")


# -------------------- Main --------------------

def main():
    ap = argparse.ArgumentParser(description="Extrae preguntas/opciones y la RESPUESTA CORRECTA (CSV/JSON) con tildes OK.")
    ap.add_argument("--tipo", choices=["testArb", "testOf"], default="testArb")
    ap.add_argument("--preguntas", choices=["1", "5", "10", "25"], default="25")
    ap.add_argument("--format", choices=["csv", "json", "both"], default="csv", help="Formato de salida.")
    ap.add_argument("--output-base", default="test_con_correcta", help="Nombre base sin extensión.")
    ap.add_argument("--csv-encoding", default="utf-8-sig", choices=["utf-8-sig","utf-8","latin-1"],
                    help="Codificación del CSV (utf-8-sig recomendado para Excel).")
    ap.add_argument("--json-encoding", default="utf-8", choices=["utf-8","latin-1"],
                    help="Codificación del JSON (UTF-8 estándar).")
    ap.add_argument("--test-html", default="debug_test.html")
    ap.add_argument("--result-html", default="debug_resultados.html")
    ap.add_argument("--print-test-html", action="store_true")
    ap.add_argument("--print-result-html", action="store_true")
    ap.add_argument("--peek", action="store_true", help="Imprime primeros 1200 chars de los HTML")
    args = ap.parse_args()

    with requests.Session() as s:
        # 1) Primer GET (cookies)
        r0 = http_get(s, CONFIG_URL, referer=BASE)
        _ = decode_response(r0)  # no usado, pero útil si quieres depurar

        # 2) Generar test
        r1 = http_post(s, ACTION_URL,
                       data={"tipo": args.tipo, "preguntas": args.preguntas},
                       referer=CONFIG_URL)
        test_html = decode_response(r1)
        save_debug(test_html, args.test_html, print_first=args.peek, print_full=args.print_test_html, label="TEST")

        # 3) Parsear preguntas/opciones
        preguntas, id_map, opciones_map = parse_test_form(test_html)
        if not preguntas:
            print("[WARN] No se detectaron preguntas en el test. Revisa debug_test.html")
            return
        print(f"[INFO] Preguntas detectadas: {len(preguntas)}")

        # 4) Enviar todo "A"
        payload = build_all_A_payload(id_map, opciones_map, tipo=args.tipo, preguntas_n=args.preguntas)
        r2 = http_post(s, GRADE_URL, data=payload, referer=ACTION_URL)
        result_html = decode_response(r2)
        save_debug(result_html, args.result_html, print_first=args.peek, print_full=args.print_result_html, label="RESULTADOS")

        # 5) Extraer "Respuesta correcta:"
        correct_texts = parse_correct_answers_from_results(result_html)
        while len(correct_texts) < len(preguntas):
            correct_texts.append("")

        # 6) Mapear texto correcto → letra según opciones del test
        correcta_letras, correcta_textos = {}, {}
        for p, correct_txt in zip(preguntas, correct_texts):
            if not correct_txt:
                correcta_letras[p["idx"]] = ""
                correcta_textos[p["idx"]] = ""
                continue
            pos = best_option_match(correct_txt, p["opciones_texto"])
            correcta_letras[p["idx"]] = LETTERS[pos] if 0 <= pos < len(LETTERS) else ""
            correcta_textos[p["idx"]] = p["opciones_texto"][pos] if 0 <= pos < len(p["opciones_texto"]) else ""

        # 7) Exportar
        out_base = Path(args.output_base)
        if args.format in ("csv", "both"):
            write_csv_with_correct(preguntas, correcta_letras, str(out_base.with_suffix(".csv")),
                                   encoding=args.csv_encoding)
        if args.format in ("json", "both"):
            write_json_with_correct(preguntas, correcta_letras, correcta_textos, str(out_base.with_suffix(".json")),
                                    encoding=args.json_encoding)

if __name__ == "__main__":
    main()
