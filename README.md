# Extractor de Tests Anónimos (Club del Árbitro FEB)

Script en Python que genera un test anónimo, extrae todas las preguntas y opciones, envía respuestas “todo A”, deduce las respuestas correctas (incluso cuando no se muestran en la web) y exporta los resultados completos a **CSV y/o JSON**, manteniendo **todas las opciones del test original**.

## Funcionamiento

1. El script solicita un test desde `configurarTestAnonimo.php`.
2. Carga el formulario en `mostrarTestAnonimo.php` y extrae:
   - ID de cada pregunta  
   - Texto de la pregunta  
   - Todas las opciones (A, B, C, …)
3. Envía un intento con todas las respuestas “A” para obtener el resultado base.
4. Analiza la página de resultados:
   - Si aparece “Respuesta correcta:”, guarda la opción correcta.
   - Si no aparece (porque la “A” era correcta), **deduce la correcta** repitiendo la corrección una por una y comparando el número de aciertos.
5. Exporta toda la información a CSV y/o JSON.

## Exportación

- **CSV**: mantiene todas las columnas de opciones (A, B, C, … hasta el número máximo encontrado).  
  Ejemplo:

```csv
idx,id_pregunta,pregunta,A,B,C,correcta,correcta_texto
0,1419,En un final de cuarto...,2 décimas,3 décimas,5 décimas,B,3 décimas
```

- **JSON**: cada pregunta con su lista de opciones completa.  
  Ejemplo:

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

## Requisitos

- Python 3.9+ (recomendado 3.10 o superior)
- Librerías necesarias:

```bash
pip install requests beautifulsoup4
```

## Uso rápido

Exportar **JSON y CSV**:

```bash
python3 test_extractor_score.py   --tipo testArb   --preguntas 25   --export-json test_con_correcta.json   --export-csv test_con_correcta.csv
```

Solo JSON:

```bash
python3 test_extractor_score.py --tipo testOf --preguntas 10 --export-json test.json
```

Solo CSV:

```bash
python3 test_extractor_score.py --tipo testArb --preguntas 25 --export-csv test.csv
```

## Opciones CLI

| Opción | Valores | Predeterminado | Descripción |
|:--|:--|:--|:--|
| `--tipo` | `testArb`, `testOf` | `testArb` | Tipo de test (árbitros u oficiales) |
| `--preguntas` | 1, 5, 10, 25 | 25 | Número de preguntas a generar |
| `--export-json` | ruta | – | Archivo JSON de salida |
| `--export-csv` | ruta | – | Archivo CSV de salida |
| `--sleep` | segundos | 0.3 | Retardo entre peticiones (para evitar bloqueo) |

## Cómo funciona la deducción de respuestas

- La web **solo muestra las “Respuestas correctas” en las que fallas**.  
- Para el resto, el script compara la **puntuación total de aciertos** (“Tienes X aciertos sobre Y”) variando una pregunta cada vez:
  - Si la puntuación sube → la nueva opción es la correcta.  
  - Si no cambia → la “A” era la correcta.

Así obtiene la solución completa sin depender del marcado HTML.

## Características

✅ Deducción automática de TODAS las respuestas  
✅ Mantiene todas las opciones del test original  
✅ CSV dinámico (A..Z según el máximo de opciones)  
✅ Compatible con UTF-8  
✅ Sin dependencias externas más allá de `requests` y `bs4`  

## Limitaciones

- El script no simula un usuario real (envía peticiones HTTP directamente).  
- Si la estructura HTML de la web cambia, puede ser necesario ajustar los selectores.  
- No evade captchas ni límites automáticos.  

## Solución de problemas

| Problema | Posible causa / solución |
|:--|:--|
| No detecta preguntas | Cambió el HTML → revisa el `tr` y los `input name="idN"` |
| Faltan respuestas correctas | Usa la versión con deducción por puntuación (este script) |
| 403 Forbidden | Espera unos segundos o cambia el `User-Agent` en el encabezado |
| Resultados incoherentes | Ajusta `--sleep` a 0.5 o 1.0 para ralentizar peticiones |
