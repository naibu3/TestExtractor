# Extractor y Solver de Tests Anónimos (Club del Árbitro FEB)

Scripts en Python para extraer, consolidar y resolver automáticamente tests anónimos de la web del Club del Árbitro FEB.

---

## 1. test_extractor_score.py — Extractor de Tests Anónimos

Script en Python que genera un test anónimo, extrae todas las preguntas y opciones, envía respuestas “todo A”, deduce las respuestas correctas (incluso cuando no se muestran en la web) y exporta los resultados completos a CSV y/o JSON, manteniendo todas las opciones del test original.

### Funcionamiento
1. Solicita un test desde `configurarTestAnonimo.php`.
2. Carga el formulario en `mostrarTestAnonimo.php` y extrae:
   - ID de cada pregunta
   - Texto de la pregunta
   - Todas las opciones (A, B, C, …)
3. Envía un intento con todas las respuestas “A” para obtener el resultado base.
4. Analiza la página de resultados:
   - Si aparece “Respuesta correcta:”, guarda la opción correcta.
   - Si no aparece (porque la “A” era correcta), deduce la correcta repitiendo la corrección una por una y comparando el número de aciertos.
5. Exporta toda la información a CSV y/o JSON.

### Exportación

**CSV:** mantiene todas las columnas de opciones (A, B, C, … hasta el máximo encontrado).

```csv
idx,id_pregunta,pregunta,A,B,C,correcta,correcta_texto
0,1419,En un final de cuarto...,2 décimas,3 décimas,5 décimas,B,3 décimas
```

**JSON:** lista de preguntas con todas las opciones y la correcta.

```json
[
  {
    "idx": 0,
    "id_pregunta": "1419",
    "pregunta": "En un final de cuarto…",
    "opciones": ["2 décimas", "3 décimas", "5 décimas"],
    "correcta": "B",
    "correcta_texto": "3 décimas"
  }
]
```

### Requisitos
- Python 3.9+ (recomendado 3.10 o superior)
- Librerías necesarias:
  ```bash
  pip install requests beautifulsoup4
  ```

### Uso rápido

**Exportar JSON y CSV:**
```bash
python3 test_extractor_score.py --tipo testArb --preguntas 25   --export-json test_con_correcta.json --export-csv test_con_correcta.csv
```

**Solo JSON:**
```bash
python3 test_extractor_score.py --tipo testOf --preguntas 10 --export-json test.json
```

**Solo CSV:**
```bash
python3 test_extractor_score.py --tipo testArb --preguntas 25 --export-csv test.csv
```

### Opciones CLI

| Opción | Valores | Predeterminado | Descripción |
|:-------|:---------|:---------------|:-------------|
| `--tipo` | `testArb`, `testOf` | `testArb` | Tipo de test (árbitros u oficiales) |
| `--preguntas` | `1`, `5`, `10`, `25` | `25` | Número de preguntas |
| `--export-json` | ruta | – | Archivo JSON de salida |
| `--export-csv` | ruta | – | Archivo CSV de salida |
| `--sleep` | segundos | `0.3` | Retardo entre peticiones |

---

## 2. collector.py — Colector de Banco de Preguntas

Script auxiliar que invoca repetidamente el extractor para reunir todas las preguntas únicas en un único archivo JSON.

### Funcionamiento
1. Ejecuta `test_extractor.py` múltiples veces (máx. 25 preguntas por iteración).
2. Fusiona todas las preguntas sin duplicados (por `id_pregunta` o texto).
3. Guarda el banco completo en `all_answers.json`.
4. Permite imprimir las preguntas mientras se agregan (`--print-batch`) o al final (`--print-final`).

### Ejemplo de uso
```bash
python3 collector.py --extractor test_extractor.py   --out all_answers.json   --preguntas 25   --target 300   --print-batch   --print-final
```

### Parámetros principales

| Opción | Descripción |
|:--------|:-------------|
| `--extractor` | Ruta a `test_extractor.py` |
| `--out` | Archivo JSON donde se guarda el banco completo |
| `--preguntas` | Nº de preguntas por iteración (máx. 25) |
| `--target` | Nº objetivo de preguntas únicas |
| `--delay` | Espera entre ejecuciones del extractor |
| `--print-batch` | Muestra las nuevas preguntas en cada iteración |
| `--print-final` | Muestra todas las preguntas al finalizar |

---

## 3. exam_solver.py — Resolver tests reales con el banco de respuestas

Script que resuelve automáticamente tests reales en la web usando el banco generado (`all_answers.json`).

### Funcionamiento
1. Solicita un nuevo test en la web (`configurarTestAnonimo.php`).
2. Extrae todas las preguntas y opciones.
3. Busca las respuestas correctas en `all_answers.json`:
   - Primero por `id_pregunta`.
   - Si no existe, por texto normalizado.
4. Envía las respuestas correctas y obtiene el resultado del test.
5. Imprime las preguntas falladas y la nota final.
6. (Opcional) exporta el examen completo a JSON con detalle de elegida/correcta.

### Ejemplos de uso

**Resolver un test de 25 preguntas de árbitros:**
```bash
python3 exam_solver.py --kb all_answers.json --tipo testArb --preguntas 25 --print
```

**Resolver y exportar el examen a JSON:**
```bash
python3 exam_solver.py --kb all_answers.json --tipo testArb   --preguntas 25 --print --export-json examen_resuelto.json
```

### Opciones CLI

| Opción | Predeterminado | Descripción |
|:--------|:---------------|:-------------|
| `--kb` | – | Archivo JSON con el banco de respuestas |
| `--tipo` | `testArb` | Tipo de test (árbitros u oficiales) |
| `--preguntas` | `25` | Número de preguntas |
| `--sleep` | `0.3` | Retardo entre peticiones |
| `--print` | – | Muestra por pantalla las falladas y la nota |
| `--export-json` | – | Guarda el examen completo en JSON |

---

## Características comunes

- Deducción automática de todas las respuestas.
- Integración entre extractor, collector y solver.
- Exportación a JSON y CSV (UTF-8).
- Evita duplicados y mantiene todas las opciones originales.
- Scripts modulares y combinables (pueden correrse por separado).

---

## Limitaciones

- No simula un usuario humano; interactúa directamente con el backend del test.
- Si cambia el HTML o los nombres de campos en la web, será necesario ajustar los selectores.
- No evade captchas ni restricciones automáticas.

---

## Solución de problemas

| Problema | Posible causa / solución |
|:----------|:--------------------------|
| No detecta preguntas | Cambió el HTML → revisar selectores de `<tr>` e inputs `name="idN"` |
| Faltan respuestas correctas | Usa el extractor con deducción de puntuación (`test_extractor_score.py`) |
| 403 Forbidden | Espera unos segundos o cambia el `User-Agent` |
| Resultados incoherentes | Aumenta `--sleep` a 0.5 o 1.0 s |

---

## Flujo recomendado (uso integrado)

1. Extraer y deducir respuestas correctas:
   ```bash
   python3 test_extractor_score.py --tipo testArb --preguntas 25 --export-json test.json
   ```

2. Unificar todas las preguntas del banco:
   ```bash
   python3 collector.py --extractor test_extractor.py --out all_answers.json --target 300
   ```

3. Resolver automáticamente un examen real:
   ```bash
   python3 exam_solver.py --kb all_answers.json --tipo testArb --preguntas 25 --print
   ```

---

Autor: Naibu  
Propósito: automatización de extracción, consolidación y resolución de tests de la FEB (uso académico y de análisis).
