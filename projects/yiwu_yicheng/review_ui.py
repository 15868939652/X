import os
import threading
import webbrowser

import bootstrap_shared  # noqa: F401
import common.review_core as core

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
core.BASE_DIR = BASE_DIR
core.OUTPUT_DIR = os.path.join(BASE_DIR, "output")
core.EX_DIR = os.path.join(BASE_DIR, "prompts", "examples")
core.NEG_DIR = os.path.join(BASE_DIR, "prompts", "negatives")
core.NEG_FILE = os.path.join(core.NEG_DIR, "issues.jsonl")
core.REVIEW_STATE_FILE = os.path.join(core.NEG_DIR, "review_state.json")
app = core.app


if __name__ == "__main__":
    os.makedirs(core.EX_DIR, exist_ok=True)
    os.makedirs(core.NEG_DIR, exist_ok=True)
    port = 5050

    def _open():
        webbrowser.open(f"http://localhost:{port}")

    threading.Timer(0.5, _open).start()
    print(f"审阅台已启动 -> http://localhost:{port}")
    app.run(port=port, debug=False, use_reloader=False)
