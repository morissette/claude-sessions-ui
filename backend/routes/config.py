"""Config HTTP endpoints."""

from fastapi import APIRouter

from backend import config as config_module

router = APIRouter()


@router.get("/api/config")
async def get_config():
    return config_module.read_config()


@router.put("/api/config")
async def put_config(body: dict):
    allowed_keys = {"daily_budget_usd", "weekly_budget_usd", "budget_flag_path"}
    cfg = config_module.read_config()
    for k, v in body.items():
        if k in allowed_keys:
            if k == "budget_flag_path":
                cfg[k] = str(v) if v is not None else None
            else:
                cfg[k] = float(v) if v is not None else None
    config_module.write_config(cfg)
    return cfg
