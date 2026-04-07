# ComputeNode

Ten folder zawiera wezel obliczeniowy.

Co robi:
- uruchamia backend realtime
- uruchamia lokalny serwer LLM
- wystawia HTTP API i WebSocket dla `RemoteGUI`
- przyjmuje dane ruchowe i sterowanie sesja

Ten wariant uruchamiasz na mocniejszym komputerze, na ktorym maja liczyc sie backend i LLM.

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

## Start

Windows:

```bat
cd installers\windows
start_compute_node.bat
```

macOS / Linux:

```bash
cd installers/mac
./start_compute_node.sh
```

Po starcie w terminalu powinien pojawic sie komunikat `ComputeNode READY`.

## Konfiguracja

Plik:

```text
config.json
```

Najwazniejsze pola:
- `manager_host`, `manager_port`: adres i port API dla `RemoteGUI`
- `udp_host`, `udp_data_port`: gdzie backend odbiera dane ruchowe
- `udp_control_port`: gdzie backend odbiera `session_start` / `session_end`
- `llm_host`, `llm_port`: lokalny adres serwera LLM
- `llm_adapter_dir`: katalog adaptera LoRA
- `llm_use_4bit`: czy uzywac kwantyzacji 4-bit
- `live_z_threshold`, `live_major_order_threshold`: progi live

Domyslny uklad:
- backend data: `5005`
- backend control: `5006`
- LLM lokalnie: `127.0.0.1:8000`
- API managera: `8010`
- dane runtime: `runtime/realtime_e2e`, `runtime/realtime_candidate`, `runtime/offline_runs`

## Jak to dziala

- dane ruchowe trafiaja do backendu na tym komputerze
- backend pyta lokalny LLM
- `RemoteGUI` laczy sie tylko do API managera
- `RemoteGUI` nie laczy sie bezposrednio do LLM

## Typowy scenariusz

- Windows z GPU: `ComputeNode`
- drugi komputer: `RemoteGUI`
- sender danych / VR wysyla dane na adres `ComputeNode`

Jesli dane przychodza z innej maszyny, `udp_host` moze zostac ustawione na `0.0.0.0`.
Jesli dane sa lokalne, mozna uzyc `127.0.0.1`.
