# ComputeNode

Węzeł obliczeniowy. Na tej maszynie **jednocześnie** działają:

- **backend pipeline** (odbiera ruch, robi tracking/analizę, generuje prompty do LLM)
- **serwer LLM** — baza `h2oai/h2o-danube3-4b-chat` (4B params) ładowana w 4-bit NF4 z double quant (`BitsAndBytesConfig`), adapter QLoRA z `backend_embedded/lora_adapters/danube_4b`, FastAPI na porcie 8000. W `adapter_config.json` widać `peft_type: "LORA"` bo biblioteka `peft` nie ma osobnego typu na QLoRA — QLoRA to metoda trenowania adaptera LoRA nad kwantyzowaną bazą, i tak jest tu wykorzystywana w czasie inference (`llm_use_4bit: true` w `config.json`).
- **manager/REST+WebSocket** dla `RemoteGUI` (FastAPI na porcie 8010)
- **emiter feedbacku VR** (UDP out)

RemoteGUI jest tylko klientem — nie musi być na tym samym komputerze, nie musi mieć GPU. Dane ruchowe też przychodzą z zewnątrz (Vicon/sender) przez UDP.

## Instalacja

Windows:
```bat
cd installers\windows
setup_compute_node.bat
```

macOS / Linux:
```bash
cd installers/mac
chmod +x *.sh
./setup_compute_node.sh
```

Instaluje się venv do `ComputeNode/.venv` i pakiety z `requirements.compute_node.txt`. Pierwsze uruchomienie LLM ściągnie bazowy model z HuggingFace do cache — adapter LoRA jest już w repo.

## Start

Windows: kliknij `installers\windows\start_compute_node.bat`
macOS / Linux: `installers/mac/start_compute_node.sh`

W terminalu powinno się pojawić:
```
[NODE] ComputeNode READY
[NODE] HTTP health: http://0.0.0.0:8010/health
[NODE] WebSocket: ws://0.0.0.0:8010/ws/events
[NODE] VR feedback UDP: 192.168.0.251:5007
[NODE] Backend i LLM uruchamiasz z RemoteGUI.
```

Linia `VR feedback UDP` pojawia się **tylko jeśli** `vr_feedback_enabled: true` w `config.json` — brak tej linii = VR feedback wyłączony. Sam backend i LLM nie startują same — uruchamia je RemoteGUI po połączeniu (albo bezpośrednim POST-em na `/backend/start`, `/llm/start`).

## Konfiguracja — `config.json`

Skrypt startowy wymusza `REALTIME_COMPUTE_CONFIG=<ROOT>/config.json`, więc to jest plik którego proces faktycznie używa. **JSON bez komentarzy** — `//` albo `/* */` wywalą parser i wszystkie ustawienia pójdą w las (silent fallback do defaultów z `realtime_studio/compute_settings.py`).

Pola które zwykle się zmienia:

| Pole | Do czego |
|---|---|
| `manager_host`, `manager_port` | adres REST/WS dla RemoteGUI (domyślnie `0.0.0.0:8010`) |
| `udp_host`, `udp_data_port` | gdzie backend słucha danych Vicona (domyślnie `0.0.0.0:5005`) |
| `udp_control_port` | gdzie backend słucha sterowania sesją (domyślnie `5006`) |
| `llm_host`, `llm_port` | lokalny endpoint LLM (zawsze `127.0.0.1:8000`) |
| `llm_adapter_dir`, `llm_use_4bit` | katalog adaptera QLoRA + kwantyzacja 4-bit NF4 (działa tylko na CUDA; na MPS/CPU leci pełna precyzja z samym LoRA na wierzchu) |
| `input_hz`, `window_seconds`, `stride_seconds` | parametry okna analizy (100 Hz, 4 s okno co 3 s) |
| `dance_id`, `sequence_name`, `gender` | kontekst sesji (`step_type` wyliczane automatycznie z `dance_id`) |
| `live_z_threshold`, `live_major_order_threshold` | progi detekcji live (kiedy wołać LLM) |
| `output_root` | gdzie zapisują się runy (`../runtime/realtime_e2e/<data>/<run_id>/`) |
| `vr_feedback_enabled`, `vr_feedback_host`, `vr_feedback_port` | wysyłka UDP z feedbackiem LLM do headsetu/klienta VR |

Zmiana `vr_feedback_*` wymaga restartu **całego procesu ComputeNode** (Ctrl+C w terminalu + start ponownie). Przyciski Stop/Start w RemoteGUI restartują tylko subproces backendu i LLM, a socket VR jest tworzony raz w managerze przy starcie `node_manager.py`.

## Jakie dane dostaje backend

Klient (Vicon Nexus albo `bin/replay_csv_over_udp.py`) strzela pakiety UDP na `udp_data_port` (domyślnie `5005`). Format jest binarny, little-endian, jeden pakiet = jedna klatka:

```
HEADER:   uint32 frame_number       (4 B)
          uint16 marker_count       (2 B)
MARKER:   uint16 marker_id          (2 B)    ← powtórzone marker_count razy
          float64 x                 (8 B)
          float64 y                 (8 B)
          float64 z                 (8 B)
```

Struktury Pythona: `<IH` nagłówek, `<Hddd` marker (`pipeline_core/realtime/udp_protocol.py:53-54`).

`marker_id` to indeks do listy markerów Vicona (`DEFAULT_MARKER_NAMES` w tym samym pliku). Fragment:

```
 0: LFHD    5: T10    10: LUPA   23: LASI   27: LTHI
 1: RFHD    6: CLAV   11: LELB   24: RASI   28: LKNE
 2: LBHD    7: STRN   12: LFRM   25: LPSI   29: LTIB
 3: RBHD    8: RBAK   ...        26: RPSI   ...
 4: C7      9: LSHO   ...                   38: RTOE
```

39 markerów full-body, XYZ w milimetrach, układ współrzędnych Vicona. Frame rate zwykle 100 Hz (ustawiane przez `input_hz`).

Przykład jednej klatki (hex, skrót dla 3 markerów — w praktyce leci ~39):
```
01 00 00 00        frame_number = 1
03 00              marker_count = 3
00 00              marker_id = 0  (LFHD)
00 00 00 00 00 00 78 40    x = 384.0
00 00 00 00 00 00 74 40    y = 320.0
00 00 00 00 00 80 ce 40    z = 15600.0
01 00              marker_id = 1  (RFHD)
...
```

CSV Vicona (`Trajectories` section) konwertujesz tym skryptem:
```bash
python backend_embedded/bin/replay_csv_over_udp.py \
  --csv <plik.csv> \
  --dst-host 127.0.0.1 \
  --dst-port 5005
```
Respektuje fps z nagłówka CSV, pomija marker jeśli xyz=NaN.

## Sterowanie sesją (UDP control, port 5006)

Oddzielny kanał UDP na `udp_control_port` — JSON-em, nie binarką. Trzy typy eventów:

```json
{"type": "session_prepare", "session_id": "S1", "dance_id": "k_krok_podstawowy_polonez",
 "gender": "female", "step_type": "step", "sequence_name": "udp_sequence"}

{"type": "session_start",   "session_id": "S1", "dance_id": "k_krok_podstawowy_polonez",
 "gender": "female", "step_type": "step", "sequence_name": "udp_sequence"}

{"type": "session_end",     "reason": "manual"}
```

Pola `dance_id`, `gender`, `step_type` mówią backendowi z których wzorców i progów korzystać. `step_type` można pominąć — będzie wyliczony jako `"step"` jeśli w `dance_id` jest substring `"krok"`, w przeciwnym razie `"static"` (`bin/send_control_event.py:39`).

RemoteGUI wysyła te eventy automatycznie przez REST managera (`/session/start`, `/session/stop`) — manager potem lokalnie wstrzykuje pakiet na `127.0.0.1:5006`. Jak chcesz ręcznie do testów:
```bash
python backend_embedded/bin/send_control_event.py \
  --host 127.0.0.1 --port 5006 \
  --type session_start --session-id S1 \
  --dance-id k_krok_podstawowy_polonez
```

## Pełny przepływ danych

```
┌──────────────┐    UDP 5005 (bin Vicon)     ┌─────────────────────────────┐
│ Vicon/Sender │ ──────────────────────────► │ backend_embedded pipeline   │
└──────────────┘                             │  (pose → analiza okien →    │
                                             │   prompt)                   │
┌──────────────┐    UDP 5006 (JSON control)  │                             │
│ RemoteGUI    │ ──────────────────────────► │                             │
│ (przez mgr)  │                             │                             │
└──────────────┘                             └─────────────┬───────────────┘
       ▲                                                   │ HTTP POST
       │ WebSocket 8010 (events)                           ▼ 127.0.0.1:8000/generate
       │                                             ┌──────────────┐
       │                                             │ llm_server        │
       │                                             │ (Danube3-4B +     │
       │                                             │  QLoRA nf4/4-bit) │
       │                                             └──────┬────────────┘
       │                                                    │ JSON {feedback, score, latency_s}
       │                                                    ▼
       │                                             backend stdout → „[FEEDBACK] ...”
       │                                                    │
       │                              ┌─────────────────────┴───────────────────┐
       │                              │ node_manager parsuje [FEEDBACK]          │
       │                              │  1) publish WS event "feedback" → GUI    │
       │                              │  2) sendto(vr_feedback_host:5007)        │
       │                              └─────────────────────┬───────────────────┘
       │                                                    │
       └────────────────────────────────────────────────────┤
                                                            ▼
                                                 ┌──────────────────┐
                                                 │ VR klient / odb. │
                                                 │ UDP 5007         │
                                                 └──────────────────┘
```

Backend pisze feedback jako linię na stdout w formacie:
```
[FEEDBACK] Trzymaj prostą sylwetkę i wyższe kolano. Score: 4 (score=4, 0.873s)
```
`node_manager` łapie każdą linię subprocesu, wyciąga tekst po `[FEEDBACK]` przez `extract_feedback_text()` (`realtime_studio/launch.py:135`) i dalej rozsyła go dwoma kanałami: do GUI przez WebSocket, do VR przez UDP.

## Co idzie do RemoteGUI (WebSocket `ws://<host>:8010/ws/events`)

Każdy event to JSON `{type, payload}`. Najważniejsze typy:

```json
{"type": "log", "payload": {"source": "backend", "line": "[BACKEND] ..."}}

{"type": "feedback", "payload": {"text": "Trzymaj prostą sylwetkę i wyższe kolano. Score: 4"}}

{"type": "session_prepared", "payload": {"run_id": "studio_20260407_163036", "dance_id": "k_krok_podstawowy_polonez"}}
{"type": "session_started",  "payload": {"session_id": "S1", "dance_id": "k_krok_podstawowy_polonez", "run_id": "studio_20260407_163036"}}
{"type": "session_stopped",  "payload": {"reason": "manual"}}

{"type": "backend_state", "payload": {"state": "READY", "details": "listening", "pid": 35123}}
{"type": "llm_state",     "payload": {"state": "READY", "details": "model loaded", "pid": 35992}}
```

Tekst feedbacku jest surowy z LLM — GUI nie robi żadnego post-processingu.

## Co idzie do VR (UDP out, port 5007)

Emiter: `node_manager._send_vr_packet` (`realtime_studio/node_manager.py:152-159`). Payload to `json.dumps(...)` w UTF-8, **jeden pakiet UDP = jeden JSON**, bez ramkowania, bez długości z przodu. Klient VR ma po prostu `recvfrom()`, `json.loads(data)`.

Dwa typy pakietów:

**Feedback (leci w trakcie sesji, za każdym razem gdy LLM dorzuci odpowiedź):**
```json
{"type": "feedback", "text": "Trzymaj prostą sylwetkę i wyższe kolano. Score: 4"}
```

**Summary (leci raz, przy `session_end`):**
```json
{"type": "summary", "text": "3.67"}
```
`text` summary to średni score z całej sesji, zaokrąglony do 2 miejsc — konkretnie `round(sum(scores)/len(scores), 2)` gdzie `scores` to wszystkie wartości `score=X` wydłubane z linii `[FEEDBACK]` w trakcie sesji (`node_manager._extract_feedback_score` + `_send_vr_summary`).

Odbieranie po stronie VR (minimalny przykład):
```python
import socket, json
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 5007))
while True:
    data, addr = sock.recvfrom(65536)
    msg = json.loads(data.decode("utf-8"))
    if msg["type"] == "feedback":
        display_toast(msg["text"])
    elif msg["type"] == "summary":
        show_final_score(float(msg["text"]))
```

Do podglądu bez klienta VR jest w repo `udp_feedback_receiver.py`:
```bash
python udp_feedback_receiver.py --port 5007
```
Pamiętaj: to działa tylko jeśli `vr_feedback_host` w configu wskazuje na adres **tego komputera** na którym odpalasz receiver. Jeśli `vr_feedback_host` jest adresem headsetu, pakiety tam wyjdą i lokalnie ich nie zobaczysz.

## REST API managera (port 8010)

Dla RemoteGUI, ale dostępne też z curla:

```
GET  /health                    → snapshot
GET  /snapshot                  → snapshot
POST /llm/start                 → odpala/reużywa llm_server.py
POST /llm/stop
POST /backend/start             → odpala controlled_session, zwraca run_id
POST /backend/stop
POST /session/start {body}      → wstrzykuje session_start na UDP 5006
POST /session/stop  {body}      → wstrzykuje session_end na UDP 5006
GET  /analysis/runs             → lista runów z output_root
GET  /analysis/run/{run_id}     → analiza (stage7) konkretnego runu
WS   /ws/events                 → stream eventów (patrz wyżej)
```

## Gdzie zapisują się wyniki

`runtime/realtime_e2e/<YYYY-MM-DD>/<run_id>/` — tam lądują pliki per sesja:
- `raw/` — zrzut surowych pakietów UDP
- `pipeline/json/...` — wyniki kolejnych stage'ów pipeline'u
- `analysis/stage7/*.json` — finalna analiza (używana przez `/analysis/run/{run_id}`)
- `offline_runs/` — logi promptów LLM-a dla tego runu
- `session_meta.json` — metadane sesji

## Typowe problemy

**Brak `[NODE] VR feedback UDP: ...` przy starcie** — `vr_feedback_enabled: false` w configu, **albo** JSON się nie sparsował (sprawdź czy nie masz `//` komentarzy, literówek, brakującego przecinka). Gdy `load_compute_config` poleci na wyjątku, po cichu wraca defaultem dataklasy gdzie `vr_feedback_enabled=False`.

**Feedback widać w GUI, ale nie dociera do receivera VR** — restartowałeś tylko backend z GUI, nie cały proces ComputeNode. Socket VR jest tworzony raz przy starcie node_managera. Ctrl+C w terminalu + `start_compute_node.bat` ponownie.

**GUI nie łączy się do managera** — sprawdź `manager_host`. `0.0.0.0` jest OK do bindu ale w RemoteGUI/config.json `node_host` musi być konkretnym adresem IP tej maszyny (albo `127.0.0.1` jeśli wszystko lokalnie).

**LLM startuje, ale pipeline nie dostaje odpowiedzi** — sprawdź w logach GUI linijkę `[LLM] Model ready [OK]` i `[LLM] Starting server on 127.0.0.1:8000`. Dopóki model się ładuje, `backend_state` jest READY ale requesty do `/generate` dostają 503.

**Port 5005/5006/8000/8010 zajęty** — manager próbuje wykryć już działający LLM na `llm_host:llm_port` i reużyć go. Dla pozostałych portów trzeba posprzątać ręcznie (`netstat -ano | findstr 5005` + `taskkill /PID ...` na Windowsie).
