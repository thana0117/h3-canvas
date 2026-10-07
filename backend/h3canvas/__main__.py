"""python -m h3canvas [--port 5180] [--comfy http://home-pc:8188]"""

import argparse
import webbrowser

import uvicorn

from .main import create_app


def main():
    ap = argparse.ArgumentParser(prog="h3canvas")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5180)
    ap.add_argument("--comfy", help="ComfyUI URL on the engine PC, e.g. http://home-pc:8188")
    ap.add_argument("--data", help="Where projects and assets are stored (default ~/H3Canvas)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    app = create_app(data_dir=args.data, comfy_url=args.comfy)
    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
