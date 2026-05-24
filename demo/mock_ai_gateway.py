#!/usr/bin/env python3
"""
Mock AI Gateway for Qubiva demo mode.

Mimics the LiteLLM proxy management API endpoints used by Qubiva's AI
Governance feature.  Runs as a lightweight FastAPI service on port 4000
alongside the main app in docker-compose.

All data is pre-generated at start-up from a fixed random seed so every
demo run produces the same numbers.
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import FastAPI, Query

app = FastAPI(title="Mock AI Gateway (demo)", docs_url=None, redoc_url=None)

# ── Deterministic seed for reproducible demo data ─────────────────────────────
rng = random.Random(42)
NOW = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
DAY_0 = NOW - timedelta(days=90)

# ── Models ────────────────────────────────────────────────────────────────────
MODELS = [
    {
        "model_id": "model-demo-0001",
        "model_name": "gpt-4o",
        "litellm_params": {
            "model": "gpt-4o",
            "api_base": "https://api.openai.com/v1",
        },
        "model_info": {
            "id": "model-demo-0001",
            "db_model": True,
            "created_at": (NOW - timedelta(days=88)).isoformat(),
            "updated_at": (NOW - timedelta(days=2)).isoformat(),
        },
    },
    {
        "model_id": "model-demo-0002",
        "model_name": "claude-3-5-sonnet",
        "litellm_params": {"model": "anthropic/claude-3-5-sonnet-20241022"},
        "model_info": {
            "id": "model-demo-0002",
            "db_model": True,
            "created_at": (NOW - timedelta(days=75)).isoformat(),
            "updated_at": (NOW - timedelta(days=5)).isoformat(),
        },
    },
    {
        "model_id": "model-demo-0003",
        "model_name": "llama-3.3-70b",
        "litellm_params": {
            "model": "groq/llama-3.3-70b-versatile",
            "api_base": "https://api.groq.com/openai/v1",
        },
        "model_info": {
            "id": "model-demo-0003",
            "db_model": True,
            "created_at": (NOW - timedelta(days=60)).isoformat(),
            "updated_at": (NOW - timedelta(days=1)).isoformat(),
        },
    },
]

# ── Virtual key definitions ───────────────────────────────────────────────────
_KEY_DEFS = [
    {
        "token": "sk-demo-platform-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "alias": "platform-team",
        "max_budget": 2000.0,
        "rpm_limit": 1000,
        "tpm_limit": 500_000,
        "models": ["gpt-4o", "claude-3-5-sonnet", "llama-3.3-70b"],
        "days_ago": 88,
        "model_weights": [("gpt-4o", 0.5), ("claude-3-5-sonnet", 0.3), ("llama-3.3-70b", 0.2)],
        "daily_calls": 18,
    },
    {
        "token": "sk-demo-datateam-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "alias": "data-team",
        "max_budget": 1000.0,
        "rpm_limit": 500,
        "tpm_limit": 200_000,
        "models": ["gpt-4o", "llama-3.3-70b"],
        "days_ago": 75,
        "model_weights": [("gpt-4o", 0.4), ("llama-3.3-70b", 0.6)],
        "daily_calls": 10,
    },
    {
        "token": "sk-demo-frontend-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "alias": "frontend-team",
        "max_budget": 500.0,
        "rpm_limit": 200,
        "tpm_limit": 100_000,
        "models": ["gpt-4o"],
        "days_ago": 60,
        "model_weights": [("gpt-4o", 1.0)],
        "daily_calls": 4,
    },
    {
        "token": "sk-demo-pipeline-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "alias": "ci-pipeline",
        "max_budget": None,
        "rpm_limit": 300,
        "tpm_limit": 150_000,
        "models": ["llama-3.3-70b"],
        "days_ago": 80,
        "model_weights": [("llama-3.3-70b", 1.0)],
        "daily_calls": 7,
    },
    {
        "token": "sk-demo-research-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "alias": "research",
        "max_budget": 250.0,
        "rpm_limit": 100,
        "tpm_limit": 50_000,
        "models": ["claude-3-5-sonnet", "llama-3.3-70b"],
        "days_ago": 45,
        "model_weights": [("claude-3-5-sonnet", 0.6), ("llama-3.3-70b", 0.4)],
        "daily_calls": 2,
    },
]

# ── Cost rates (USD per 1k tokens): input, output ─────────────────────────────
_RATES = {
    "gpt-4o":           (0.0025, 0.010),
    "claude-3-5-sonnet":(0.003,  0.015),
    "llama-3.3-70b":    (0.00059, 0.00079),
}


def _weighted_pick(choices):
    items, weights = zip(*choices)
    r = rng.random() * sum(weights)
    for item, w in zip(items, weights):
        r -= w
        if r <= 0:
            return item
    return items[-1]


# ── Generate spend logs ───────────────────────────────────────────────────────
SPEND_LOGS = []
_key_spend_totals = {kd["token"]: 0.0 for kd in _KEY_DEFS}

for _day_idx in range(90):
    _day = DAY_0 + timedelta(days=_day_idx)
    _is_weekend = _day.weekday() >= 5
    _multiplier = 0.3 if _is_weekend else 1.0

    for _kd in _KEY_DEFS:
        _base = _kd["daily_calls"]
        _n = max(0, int(rng.gauss(_base * _multiplier, max(1, _base * 0.25))))

        for _ in range(_n):
            _model = _weighted_pick(_kd["model_weights"])
            _in_rate, _out_rate = _RATES[_model]
            _prompt = max(50, int(rng.gauss(800, 300)))
            _completion = max(20, int(rng.gauss(400, 150)))
            _spend = (_prompt / 1000) * _in_rate + (_completion / 1000) * _out_rate

            _hour = rng.randint(7, 22) if not _is_weekend else rng.randint(9, 19)
            _ts = _day.replace(
                hour=_hour,
                minute=rng.randint(0, 59),
                second=rng.randint(0, 59),
                microsecond=0,
            )

            _key_spend_totals[_kd["token"]] += _spend

            SPEND_LOGS.append({
                "request_id": str(uuid.UUID(int=rng.getrandbits(128))),
                "startTime": _ts.isoformat(),
                "endTime": (_ts + timedelta(seconds=rng.randint(1, 8))).isoformat(),
                "model": _model,
                "api_key": _kd["token"],
                "user": f"{_kd['alias']}@demo.local",
                "spend": round(_spend, 6),
                "total_tokens": _prompt + _completion,
                "prompt_tokens": _prompt,
                "completion_tokens": _completion,
                "metadata": {},
                "status": "success",
            })

# Newest first — matches LiteLLM default ordering
SPEND_LOGS.sort(key=lambda x: x["startTime"], reverse=True)

# ── Derived aggregates ────────────────────────────────────────────────────────
GLOBAL_SPEND = round(sum(_key_spend_totals.values()), 4)

KEYS = [
    {
        "token": kd["token"],
        "key_alias": kd["alias"],
        "key_name": kd["alias"],
        "spend": round(_key_spend_totals[kd["token"]], 4),
        "max_budget": kd["max_budget"],
        "rpm_limit": kd["rpm_limit"],
        "tpm_limit": kd["tpm_limit"],
        "models": kd["models"],
        "user_id": f"{kd['alias']}@demo.local",
        "team_id": kd["alias"],
        "created_at": (NOW - timedelta(days=kd["days_ago"])).isoformat(),
        "expires": None,
        "metadata": {"team": kd["alias"]},
    }
    for kd in _KEY_DEFS
]

_model_agg = {}
for _log in SPEND_LOGS:
    _m = _log["model"]
    if _m not in _model_agg:
        _model_agg[_m] = {"model": _m, "total_spend": 0.0, "total_tokens": 0, "request_count": 0}
    _model_agg[_m]["total_spend"] += _log["spend"]
    _model_agg[_m]["total_tokens"] += _log["total_tokens"]
    _model_agg[_m]["request_count"] += 1

SPEND_BY_MODEL = [
    {**v, "total_spend": round(v["total_spend"], 4)}
    for v in _model_agg.values()
]

SPEND_BY_KEY = [
    {
        "api_key": k["token"],
        "key_alias": k["key_alias"],
        "total_spend": k["spend"],
    }
    for k in KEYS
]

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health/readiness")
async def health():
    return {"status": "healthy"}


# Models
@app.get("/model/info")
async def model_info():
    return {"data": MODELS}

@app.post("/model/new")
async def model_new():
    return {"model_id": f"model-demo-{rng.randint(1000, 9999)}"}

@app.post("/model/delete")
async def model_delete():
    return {"deleted": True}

@app.post("/model/update")
async def model_update():
    return {"updated": True}


# Virtual keys
@app.get("/key/list")
async def key_list():
    # Return full objects — client skips /key/info fetch for non-string entries
    return {"keys": KEYS}

@app.get("/key/info")
async def key_info(key: str = Query(...)):
    match = next((k for k in KEYS if k["token"] == key), None)
    return {"info": match or {}}

@app.post("/key/generate")
async def key_generate():
    return {"key": f"sk-demo-new-{uuid.uuid4().hex[:16]}"}

@app.post("/key/update")
async def key_update():
    return {"updated": True}

@app.delete("/key/delete")
async def key_delete():
    return {"deleted": True}


# Spend
@app.get("/global/spend")
async def global_spend():
    return {"spend": GLOBAL_SPEND, "max_budget": None, "budget_duration": None}

@app.get("/spend/keys")
async def spend_keys():
    return SPEND_BY_KEY

@app.get("/global/spend/models")
async def spend_models():
    return SPEND_BY_MODEL

@app.get("/spend/logs")
async def spend_logs(
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    logs = SPEND_LOGS
    if start_date:
        logs = [lg for lg in logs if lg["startTime"][:10] >= start_date]
    if end_date:
        logs = [lg for lg in logs if lg["startTime"][:10] < end_date]
    return logs[offset: offset + limit]


if __name__ == "__main__":
    print(f"Mock AI Gateway: {len(SPEND_LOGS)} spend log entries across 90 days")
    print(f"  Global spend: ${GLOBAL_SPEND:,.2f}")
    print(f"  Keys: {len(KEYS)}  Models: {len(MODELS)}")
    uvicorn.run(app, host="0.0.0.0", port=4000, log_level="warning")
