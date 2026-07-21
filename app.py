import json
import os
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "state.json"
AUDIT_LOG_FILE = BASE_DIR / "data" / "audit.log"
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
VALID_LABOR = {"nao-se-aplica", "vou-executar", "vou-encontrar"}
VALID_FINANCE = {"nao-se-aplica", "doar-parcial", "encontrar-doadores", "doar-integral"}
VALID_AUX_TIPO = {"mao-de-obra", "financeiro", "ambos"}
MAX_AUXILIARES = 3

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 20

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
_hits: dict[str, dict[str, float]] = {}


def empty_task_state() -> dict:
    return {"status": "a-fazer", "responsavel": None, "auxiliares": []}


# Tarefa 21/f3 (LOAS e Bolsa Família) já nasce atribuída ao Kayo.
DEFAULT_STATE = {
    "f3": {
        "status": "em-andamento",
        "responsavel": {"name": "Kayo", "phone": "", "labor": "vou-executar", "finance": "nao-se-aplica", "ts": 0},
        "auxiliares": [],
    },
}


def migrate_legacy_entry(entry: dict) -> dict:
    """Converte o formato antigo (um único name/phone/status/labor/finance por tarefa)
    para o novo formato com responsavel + auxiliares, preservando dados já salvos."""
    if "responsavel" in entry or "auxiliares" in entry:
        migrated = dict(empty_task_state())
        migrated.update(entry)
        if migrated.get("responsavel") is None:
            migrated["responsavel"] = None
        migrated.setdefault("auxiliares", [])
        return migrated

    has_legacy_owner = bool(entry.get("name") or entry.get("phone"))
    return {
        "status": entry.get("status") if entry.get("status") in VALID_STATUS else "a-fazer",
        "responsavel": {
            "name": entry.get("name", ""),
            "phone": entry.get("phone", ""),
            "labor": entry.get("labor") if entry.get("labor") in VALID_LABOR else "nao-se-aplica",
            "finance": entry.get("finance") if entry.get("finance") in VALID_FINANCE else "nao-se-aplica",
            "ts": entry.get("ts", 0),
        } if has_legacy_owner else None,
        "auxiliares": [],
    }


def load_state() -> dict:
    if not DATA_FILE.exists():
        return {k: json.loads(json.dumps(v)) for k, v in DEFAULT_STATE.items()}
    try:
        loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        loaded = {}
    merged = {k: json.loads(json.dumps(v)) for k, v in DEFAULT_STATE.items()}
    for task_id, entry in loaded.items():
        merged[task_id] = migrate_legacy_entry(entry)
    return merged


def save_state(current_state: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(current_state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(DATA_FILE)


state = load_state()


def get_task(task_id: str) -> dict:
    return state.setdefault(task_id, empty_task_state())


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def audit_log(action: str, task_id: str, detail: str = "") -> None:
    try:
        AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | ip={client_ip()} | {action} | {task_id} | {detail}\n"
        with AUDIT_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


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


@app.post("/api/state/<task_id>/status")
def set_status(task_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in VALID_STATUS:
        return jsonify({"error": "Status inválido."}), 400

    task = get_task(task_id)
    audit_log("status", task_id, f"{task.get('status')} -> {status}")
    task["status"] = status
    save_state(state)
    return jsonify(task)


@app.post("/api/state/<task_id>/responsavel")
def set_responsavel(task_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()[:60]
    phone = str(body.get("phone", "")).strip()[:30]
    labor = body.get("labor")
    finance = body.get("finance")

    if not name or not phone or labor not in VALID_LABOR or finance not in VALID_FINANCE:
        return jsonify({"error": "Preencha nome, celular, mão de obra e financeiro antes de salvar."}), 400

    task = get_task(task_id)
    previous = task.get("responsavel")
    audit_log("set_responsavel", task_id, f"{previous.get('name') if previous else '(vazio)'} -> {name}")
    task["responsavel"] = {"name": name, "phone": phone, "labor": labor, "finance": finance, "ts": int(time.time() * 1000)}
    save_state(state)
    return jsonify(task)


@app.delete("/api/state/<task_id>/responsavel")
def clear_responsavel(task_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    task = get_task(task_id)
    previous = task.get("responsavel")
    audit_log("clear_responsavel", task_id, f"removido: {previous.get('name') if previous else '(já vazio)'}")
    task["responsavel"] = None
    save_state(state)
    return jsonify(task)


@app.post("/api/state/<task_id>/auxiliares")
def add_auxiliar(task_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    task = get_task(task_id)
    if len(task["auxiliares"]) >= MAX_AUXILIARES:
        return jsonify({"error": "Limite de 3 auxiliares já atingido para esta tarefa."}), 400

    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()[:60]
    phone = str(body.get("phone", "")).strip()[:30]
    tipo = body.get("tipo")

    if not name or not phone or tipo not in VALID_AUX_TIPO:
        return jsonify({"error": "Preencha nome, celular e como pretende auxiliar antes de salvar."}), 400

    auxiliar = {"id": uuid.uuid4().hex[:8], "name": name, "phone": phone, "tipo": tipo, "ts": int(time.time() * 1000)}
    audit_log("add_auxiliar", task_id, f"adicionado: {name}")
    task["auxiliares"].append(auxiliar)
    save_state(state)
    return jsonify(task)


@app.post("/api/state/<task_id>/auxiliares/<aux_id>")
def update_auxiliar(task_id: str, aux_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    task = get_task(task_id)
    auxiliar = next((a for a in task["auxiliares"] if a.get("id") == aux_id), None)
    if auxiliar is None:
        return jsonify({"error": "Auxiliar não encontrado."}), 404

    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()[:60]
    phone = str(body.get("phone", "")).strip()[:30]
    tipo = body.get("tipo")

    if not name or not phone or tipo not in VALID_AUX_TIPO:
        return jsonify({"error": "Preencha nome, celular e como pretende auxiliar antes de salvar."}), 400

    audit_log("update_auxiliar", task_id, f"{auxiliar.get('name')} -> {name}")
    auxiliar["name"] = name
    auxiliar["phone"] = phone
    auxiliar["tipo"] = tipo
    auxiliar["ts"] = int(time.time() * 1000)
    save_state(state)
    return jsonify(task)


@app.delete("/api/state/<task_id>/auxiliares/<aux_id>")
def remove_auxiliar(task_id: str, aux_id: str):
    if task_id not in VALID_IDS:
        return jsonify({"error": "Tarefa não encontrada."}), 404
    if is_rate_limited(client_ip()):
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes."}), 429

    task = get_task(task_id)
    removed = next((a for a in task["auxiliares"] if a.get("id") == aux_id), None)
    if removed is None:
        return jsonify({"error": "Auxiliar não encontrado."}), 404

    audit_log("remove_auxiliar", task_id, f"removido: {removed.get('name')}")
    task["auxiliares"] = [a for a in task["auxiliares"] if a.get("id") != aux_id]
    save_state(state)
    return jsonify(task)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
