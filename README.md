# AutoMix

Mezclador DJ de dos decks hecho con Python y PySide6.

## Características
- Dos decks con crossfader, mezcla automática y auto-enganche con marca ajustable
- Análisis de BPM y tonalidad de la biblioteca y orden automático por BPM
- Ecualizador inteligente y multibanda automáticos, con sliders de golpe 43 Hz, medios y agudos
- Limitador suave y control de volumen general

## Instalación
    pip install -r requirements.txt
    python AutoMix.py

Requiere Python 3.10+.

## Datos locales
El programa crea una carpeta `cache/` junto al script (configuración, biblioteca y análisis). No se sube al repositorio.
