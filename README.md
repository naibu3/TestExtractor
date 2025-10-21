# Extractor de Tests Anónimos (Club del Árbitro FEB)

Script en Python que genera un test anónimo, extrae preguntas y opciones, envía respuestas “todo A” para obtener la solución, deduce la respuesta correcta por texto y exporta los resultados a CSV y/o JSON con las tildes correctamente codificadas.

# Funcionamiento

Genera test desde configurarTestAnonimo.php y lo carga en mostrarTestAnonimo.php.

Extrae preguntas y opciones respetando el orden (A, B, C).

Envía el test (todas A) a testAnonimo2.php para obtener la solución.

Empareja la “Respuesta correcta:” con la opción original por texto normalizado
(igualdad → inclusión → similitud difusa).

Exporta:

CSV: id_pregunta, pregunta, opcion_1..N, correcta (A/B/C/...)

JSON: objetos con id_pregunta, pregunta, opciones[], correcta (letra) y correcta_texto.

Tildes OK: CSV UTF-8 con BOM (ideal Excel) por defecto; JSON UTF-8.

# Requisitos

Python 3.9+ (recomendado 3.10+)

Paquetes:

```bash
pip install requests beautifulsoup4
```

# Uso rápido

- CSV + JSON con tildes correctas (UTF-8 con BOM para Excel)

```bash
python3 basket.py --tipo testArb --preguntas 25 --format both --output-base resultados
```

- Solo JSON

```bash
python3 basket.py --tipo testArb --preguntas 10 --format json --output-base arbitro_10
```

- Solo CSV en Latin-1 (si tu visor no acepta UTF-8)

```bash
python3 basket.py --tipo testOf --preguntas 25 --format csv --csv-encoding latin-1
```

## Opciones CLI

```bash
Opción	Valores	Predeterminado	Descripción
--tipo	testArb, testOf	testArb	Tipo de test (árbitros o auxiliares).
--preguntas	1, 5, 10, 25	25	Nº de preguntas a generar.
--format	csv, json, both	csv	Formato(s) de salida.
--output-base	texto	test_con_correcta	Nombre base de archivo sin extensión.
--csv-encoding	utf-8-sig, utf-8, latin-1	utf-8-sig	Codificación del CSV (UTF-8 con BOM recomendado para Excel).
--json-encoding	utf-8, latin-1	utf-8	Codificación del JSON.
--test-html	ruta	debug_test.html	HTML de depuración del test generado.
--result-html	ruta	debug_resultados.html	HTML de depuración con las correcciones.
--print-test-html	flag	False	Imprime el HTML completo del test por consola.
--print-result-html	flag	False	Imprime el HTML completo de resultados por consola.
--peek	flag	False	Muestra los primeros 1200 caracteres de cada HTML.
```

# ¿Cómo funciona?

GET a configurarTestAnonimo.php para establecer sesión/cookies.

POST a mostrarTestAnonimo.php con tipo y preguntas para generar el test.

Parseo del formulario que postea a testAnonimo2.php: se extraen id{i} y las opciones opcion{i} (texto y valor).

Envío de todas “A” (primera opción de cada pregunta) a testAnonimo2.php.

Parseo de la página de resultados: se localiza “Respuesta correcta:” y se extrae el <i> siguiente (texto de la opción correcta).

Matching del texto correcto con las opciones originales (normalización + heurísticas).

Exportación a CSV/JSON: letra A/B/C/… y, en JSON, correcta_texto.

## Formatos de salida

CSV (ejemplo)

```csv
id_pregunta,pregunta,opcion_1,opcion_2,opcion_3,correcta
1419,En un final de cuarto...,2 décimas,3 décimas,5 décimas,B
```

JSON (ejemplo)

```json
[
  {
    "id_pregunta": "1419",
    "pregunta": "En un final de cuarto…",
    "opciones": ["2 décimas", "3 décimas", "5 décimas"],
    "correcta": "B",
    "correcta_texto": "3 décimas"
  }
]
```

## Tildes y codificación

Si ves “balÃ³n” en lugar de “balón”, tu visor está interpretando UTF-8 como Latin-1 (mojibake).

Excel (Windows): usa `--csv-encoding utf-8-sig` (predeterminado). Abre el CSV directamente.

Visores antiguos: prueba `--csv-encoding latin-1` y/o --json-encoding latin-1.

Terminal: confirma locale UTF-8 (p. ej., es_ES.UTF-8).

# Depuración

Se guardan dos HTML:

debug_test.html: el test tal como se presenta.

debug_resultados.html: la página con “Tu respuesta / Respuesta correcta”.

Flags:

`--peek`: muestra un fragmento corto de los HTML.

`--print-test-html`, `--print-result-html`: imprimen HTML completo (muy verboso).

# Limitaciones

El script no “aprueba”: marca todo A solo para descubrir las correctas.

La estructura HTML puede cambiar. Si el parser no detecta preguntas/opciones:

Revisa debug_test.html y ajusta selectores, o comparte el fragmento para adaptar el parser.

Respeta los términos de uso del sitio. No evita CAPTCHAs ni límites anti-bot.

# Personalización

Heurística de matching: best_option_match (exacto → inclusión → fuzzy).

Normalización de texto (tildes/comillas/referencias): normalize_txt_strict.

Codificación/formatos de salida: write_csv_with_correct, write_json_with_correct.

Selectores DOM: parse_test_form, parse_correct_answers_from_results.

# Solución de problemas

403 Forbidden: cambia/agrega User-Agent, espera unos segundos, revisa conectividad/bloqueo IP.

No aparece “Respuesta correcta:”: inspecciona debug_resultados.html; puede que el marcado haya cambiado.

No coincide con ninguna opción:

El parser elimina notas tipo “(ART…)” antes de comparar.

Si un caso se resiste, compara opciones_texto vs. texto correcto exacto y ajusta la normalización.


# FAQ

¿Por qué “todo A”?
Para obtener la página de resultados con la “Respuesta correcta” visible y poder deducir la solución real por texto.

¿Puedo exportar solo la correcta en texto?
Sí: en JSON ya sale correcta_texto. Si la quieres también en CSV, se puede añadir una columna adicional.

¿Sirve para videotests?
Está orientado a testArb/testOf. Si el videotest usa otra estructura, habría que adaptar el parser.
