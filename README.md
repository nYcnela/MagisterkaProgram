# Realtime Studio

Fancy desktop control panel for running the Polonaise realtime pipeline.

## Features

- Beautiful PySide6 UI with custom theme.
- Live control over UDP, LLM and feedback thresholds.
- One-click launch/stop of backend pipeline.
- Real-time process logs.
- Saved settings in local JSON.

## Install

Najbezpieczniej uruchamiac gotowy bootstrap projektu:

```bat
.\setup_once.bat
```

albo na Unix/macOS:

```bash
./setup_once.sh
```

Setup robi teraz komplet:

- tworzy `.venv`
- instaluje GPU build `torch` (`cu130`, z fallbackiem do `cu128` na Windows/Linux)
- instaluje pelny runtime UI + backend + LLM z `requirements.txt`
- instaluje `bitsandbytes` dla kwantyzacji 4-bit
- sprawdza na koncu, czy Python rzeczywiscie widzi GPU

Jesli trzeba wymusic inny kanal PyTorch przed setupem, w PowerShell:

```powershell
$env:REALTIME_STUDIO_TORCH_CHANNEL="cu128"
.\setup_once.bat
```

Na Unix/macOS:

```bash
REALTIME_STUDIO_TORCH_CHANNEL=cu128 ./setup_once.sh
```

## Run

Po setupie uruchamiaj aplikacje przez gotowy skrypt:

```bat
.\start_realtime_studio.bat
```

albo:

```bash
./start_realtime_studio.sh
```

## GPU / LLM

- Serwer LLM jest projektowany pod GPU i domyslnie korzysta z kwantyzacji 4-bit.
- Jesli log LLM pokazuje fallback do CPU, problem lezy w srodowisku Pythona / CUDA, nie w samym UI.
- Skrypt setupu zatrzymuje sie, jesli nie uda sie zainstalowac `bitsandbytes`, bo bez tego 4-bit nie bedzie gotowy zgodnie z zalozeniem projektu.

## Roles / Deploy

Repo wspiera teraz 3 role:

- `FullApp` - obecny tryb all-in-one
- `ComputeNode` - backend + LLM + manager API/WS na mocnym komputerze
- `RemoteGUI` - lekkie GUI, ktore laczy sie do ComputeNode i pokazuje logi / feedback / status

Foldery deploy generuje:

```bash
python tools/build_distributions.py
# albo:
python -m tools.build_distributions
```

Po wygenerowaniu pojawia sie katalog:

- `deploy/FullApp`
- `deploy/ComputeNode`
- `deploy/RemoteGUI`

W `ComputeNode` i `RemoteGUI` dostajesz:

- `1_INSTALUJ.bat`
- `2_KONFIGURACJA.bat`
- `3_START.bat`
- lokalny plik `config.json` dla danej roli

Model pracy:

- Kalman / VR lub testowy sender UDP wysyla dane bezposrednio do ComputeNode
- backend i LLM licza lokalnie na ComputeNode
- RemoteGUI pobiera stan przez HTTP + WebSocket

Przy tescie po Tailscale:

- `RemoteGUI/config.json` powinno miec `node_host` ustawione na adres ComputeNode
- `ComputeNode/config.json` moze miec `udp_host=0.0.0.0`, jesli dane przychodza z innej maszyny
- `llm_host` na ComputeNode zostaje lokalny, zwykle `127.0.0.1`

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
