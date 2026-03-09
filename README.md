# Realtime Studio

Fancy desktop control panel for running the Polonaise realtime pipeline.

## Features

- Beautiful PySide6 UI with custom theme.
- Live control over UDP, LLM and feedback thresholds.
- One-click launch/stop of backend pipeline.
- Real-time process logs.
- Saved settings in local JSON.

## Run

```bash
python -m pip install PySide6
python -m realtime_studio
```

## Embedded Backend Mode

App can run without external Magisterka path discovery by using local bundle:

- `backend_embedded/` (next to this README)

Backend auto-discovery now checks this folder first.

### Refresh embedded bundle from source repo

```bash
python tools/sync_embedded_backend.py --source-root /path/to/Magisterka --clean
```

Example:

```bash
python tools/sync_embedded_backend.py --source-root /Users/maciek/PycharmProjects/Magisterka --clean
```

After sync, GUI should show backend root:

- `<realtime_studio>/backend_embedded`

Notes:

- LLM adapter path is still configurable in GUI (`LLM Runtime -> Adapter dir`).
- If adapter weights are not copied into embedded bundle, point adapter path to existing location.
