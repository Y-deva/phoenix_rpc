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
After that, `python -m phoenix_gui` starts `novacoind` and the local proxy in
hidden processes and asks for the key-store password once. Existing processes
are reused. See [README_GUI.md](README_GUI.md) for screenshots, hotkeys,
legacy `wallet.dat` migration and launch details.


## Project links

- Repository: [Y-deva/phoenix_rpc](https://github.com/Y-deva/phoenix_rpc)
- [FurryDrag0n](https://github.com/FurryDrag0n)
- [Y-deva](https://github.com/Y-deva)
