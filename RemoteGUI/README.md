# RemoteGUI

Ten folder zawiera zdalny panel sterowania dla `ComputeNode`.

Co robi:
- laczy sie z `ComputeNode` przez HTTP i WebSocket
- pokazuje status backendu i LLM
- pokazuje logi i ostatni feedback
- pozwala uruchomic i zatrzymac backend, LLM i sesje

Ten wariant uruchamiasz na komputerze, ktory ma byc tylko panelem sterowania i podgladu.

## Instalacja

Windows:

```bat
cd windows
setup_remote_gui.bat
```

macOS / Linux:

```bash
cd mac
chmod +x *.sh
./setup_remote_gui.sh
```

## Start

Windows:

```bat
cd windows
start_remote_gui.bat
```

macOS / Linux:

```bash
cd mac
./start_remote_gui.sh
```

## Konfiguracja

Plik:

```text
config.json
```

Najwazniejsze pola:
- `node_host`, `node_port`: adres `ComputeNode`
- `auto_connect`: czy laczyc automatycznie po starcie
- `dance_id`, `sequence_name`, `gender`, `step_type`: domyslne dane sesji
- `dancer_first_name`, `dancer_last_name`: dane osoby
- `live_z_threshold`, `live_major_order_threshold`: progi live wysylane przy starcie sesji
- `auto_start_llm`: czy przed backendem uruchamiac LLM

## Jak to dziala

- `RemoteGUI` nie uruchamia backendu ani LLM lokalnie.
- Wszystkie operacje wykonuje `ComputeNode`.
- `RemoteGUI` tylko wysyla polecenia i odbiera status, logi i feedback.

## Typowy scenariusz

- `ComputeNode` dziala na mocniejszym komputerze
- `RemoteGUI` dziala na drugim komputerze
- w `config.json` ustawiasz `node_host` na adres `ComputeNode`

Przyklad po Tailscale:

```json
{
  "node_host": "100.90.0.102",
  "node_port": 8010
}
```
