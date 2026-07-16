import json
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "state.json"
STATIC_DIR = BASE_DIR / "static"

VALID_IDS = {
    "m1", "m2", "m3", "m4", "m5", "m6", "m7",
    "p1", "p2", "p3", "p4", "p5", "p6",
    "b1", "b2", "b3", "b4", "b5",
    "f1", "f2", "f3",
    "n1", "n2", "n3",
    "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10", "c11",
}
VALID_STATUS = {"a-fazer", "em-andamento", "concluido"}

# Tarefa 21/f3 (LOAS e Bolsa Família) já nasce atribuída ao Kayo.
DEFAULT_STATE = {
    "f3": {"name": "Kayo", "phone": "", "status": "em-andamento", "ts": 0},
}

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 20

app = Flask(__name__, static_folder=None)
_hits: dict[str, dict[str, float]] = {}


def load_state() -> dict:
    if not DATA_FILE.exists():
        return dict(DEFAULT_STATE)
    try:
        loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_STATE)
    merged = dict(DEFAULT_STATE)
    merged.update(loaded)
    return merged


def save_state(current_state: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(current_state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(DATA_FILE)


state = load_state()


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_rate_limited(ip: str) -> bool:
    now = time.time()
    entry = _hits.get(ip)
    if entry is None or now > entry["reset_at"]:
        entry = {"count": 0, "reset_at": now + RATE_LIMIT_WINDOW_SECONDS}
    entry["count"] += 1
    _hits[ip] = entry
    return entry["count"] > RATE_LIMIT_MAX_REQUESTS


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/state")
def get_state():
    return jsonify(state)


@app.post("/api/state/<task_id>")
def set_task_state(task_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()[:60]
    phone = str(body.get("phone", "")).strip()[:30]
    status = body.get("status") if body.get("status") in VALID_STATUS else "a-fazer"

    state[task_id] = {"name": name, "phone": phone, "status": status, "ts": int(time.time() * 1000)}
    save_state(state)
    return jsonify(state[task_id])


@app.delete("/api/state/<task_id>")
def clear_task_state(task_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    state.pop(task_id, None)
    save_state(state)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
