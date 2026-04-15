"""WebSocket endpoint."""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend import aggregation, config, constants, database, metrics, ollama

router = APIRouter()

_active_ws: list[WebSocket] = []


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    time_range: str = "1d",
    start: str | None = None,
    end: str | None = None,
    project: str | None = None,
):
    from datetime import datetime

    # Validate custom date params before accepting
    if start:
        try:
            datetime.fromisoformat(start)
        except ValueError:
            await ws.close(code=1008, reason="Invalid start date")
            return
    if end:
        try:
            datetime.fromisoformat(end)
        except ValueError:
            await ws.close(code=1008, reason="Invalid end date")
            return

    if time_range not in constants.TIME_RANGE_HOURS:
        time_range = "1d"
    await ws.accept()
    _active_ws.append(ws)
    upsert_task: asyncio.Task | None = None
    try:
        while True:
            sess = aggregation.get_sessions_for_range(time_range, start=start, end=end)
            if project:
                sess = [s for s in sess if s.get("project_name") == project]
            hours = constants.TIME_RANGE_HOURS.get(time_range)
            stats = aggregation.compute_global_stats(sess, hours if hours is not None else constants.LIVE_HOURS)
            metrics._update_prometheus(stats)
            if hours is not None and hours <= constants.LIVE_HOURS and (
                upsert_task is None or upsert_task.done()
            ):
                upsert_task = asyncio.create_task(database._upsert_in_background(sess))
            cfg = config.read_config()
            budget_status = config.check_budget_status(stats, cfg)

            # Optional flag file
            raw_flag = cfg.get("budget_flag_path")
            if raw_flag:
                try:
                    flag_path = config.validate_flag_path(raw_flag)
                    if flag_path:
                        any_exceeded = (
                            (budget_status["daily"] and budget_status["daily"]["exceeded"]) or
                            (budget_status["weekly"] and budget_status["weekly"]["exceeded"])
                        )
                        if any_exceeded:
                            flag_path.touch()
                        elif flag_path.exists():
                            with contextlib.suppress(FileNotFoundError):
                                flag_path.unlink()
                except (ValueError, OSError):
                    pass

            await ws.send_json({
                "sessions": sess,
                "stats": stats,
                "savings": ollama.compute_ollama_savings(),
                "truncation": ollama.compute_truncation_savings(),
                "time_range": time_range,
                "budget_status": budget_status,
            })
            # Live ranges poll fast; historical/all/custom ranges poll slower
            if hours is not None and hours <= constants.LIVE_HOURS:
                interval = 2
            elif start or end or hours is None:
                interval = 30
            else:
                interval = 10
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in _active_ws:
            _active_ws.remove(ws)
