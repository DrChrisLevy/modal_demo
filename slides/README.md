# Talk slides

This directory contains the presentation, local images and fonts, and both Python demos.

From the repository root, serve the slides:

```bash
uv run python -m http.server 8765 --bind 127.0.0.1 --directory slides
```

Open http://127.0.0.1:8765/. Use the arrow keys to navigate, F for fullscreen, and Escape to exit fullscreen. Refresh keeps the current slide. You can also open `index.html` directly.

Run the demos from the repository root using the project’s Modal environment and your Modal authentication:

```bash
uv run modal run slides/simple.py
uv run modal run slides/trainer.py --smoke
uv run modal run slides/trainer.py
```

The training demo runs on a Modal GPU and saves its results to a Modal Volume. Its configuration is in `trainer.py`.
