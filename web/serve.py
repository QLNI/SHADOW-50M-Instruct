"""serve.py: a static server for the browser page, with the cross-origin isolation headers WebAssembly threads need.

Without those two headers the browser refuses SharedArrayBuffer and the page falls back to the single-thread build.
Serves the repository root, so the page reaches the container in deployment/ and the tokenizer in tokenizer/ as they are.

  python web/serve.py [port]        then open http://localhost:8000/web/
"""
import sys, os, http.server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("", PORT), Handler) as s:   # threaded: the page's workers fetch in parallel
        print(f"http://localhost:{PORT}/web/  (cross-origin isolated, serving {ROOT})")
        s.serve_forever()
