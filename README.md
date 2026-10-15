# AutoMix

Mezclador DJ de dos decks hecho con Python y PySide6.

## Características
- Dos decks con crossfader, mezcla automática y auto-enganche con marca roja ajustable (la mezcla arranca exactamente en la marca)
- Análisis de BPM y tonalidad de la biblioteca, con lista inteligente que se ordena sola mientras analiza (BPM + clave delante del nombre)
- **Cruce por bandas**: el tema entrante entra al 100 % y los graves se traspasan aparte, en la línea del compás (filtro Linkwitz-Riley a 150 Hz), para que el enganche sea imperceptible
- **Recetas automáticas**: detecta dónde hay voz o melodía en cada tema y elige cómo traspasar graves y medios (voz nueva sobre la base vieja, base nueva con voz vieja, etc.)
- Ecualizador inteligente y multibanda automáticos, con sliders de golpe 43 Hz, medios y agudos
- Limitador por ganancia (sin recorte de la onda) y control de volumen general

## Instalación
    pip install -r requirements.txt
    python AutoMix.py

Requiere Python 3.10+.

## Datos locales
El programa crea una carpeta `cache/` junto al script (configuración, biblioteca y análisis). No se sube al repositorio.

## Créditos
Desarrollado por Gustavo con la ayuda de [Claude](https://claude.ai) (Anthropic), la herramienta de IA que se usó para programarlo.
