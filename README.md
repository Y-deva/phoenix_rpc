# Installation guide
1. Unzip archive to any folder
2. Select project folder in terminal:
    `cd phoenix_rpc`
3. Initialize virtual environment
    `python -m venv ./`
4. Install dependencies
    `./bin/pip install -r requirements.txt`
5. Run main script
    `./bin/python main.py`

It can take couple minutes to compile liboqs first time.
That's it. Enjoy.

## Graphical interface

The PyQt6 wallet lives in `phoenix_gui` and talks to the same local proxy:

```bash
python -m phoenix_gui
python -m phoenix_gui --demo
```

Install its lighter dependency set with `pip install -r requirements-gui.txt`.
See [README_GUI.md](README_GUI.md) for screenshots, hotkeys and architecture notes.
