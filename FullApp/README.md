# FullApp

Ten folder zawiera pelna wersje aplikacji uruchamiana lokalnie na jednym komputerze.

Co robi:
- uruchamia GUI
- uruchamia lokalny backend realtime
- uruchamia lokalny serwer LLM
- pokazuje logi i ostatni feedback w jednym oknie

Ten wariant wybierasz wtedy, gdy wszystko ma dzialac na jednej maszynie.

## Instalacja

Windows:

```bat
.\setup_once.bat
```

macOS / Linux:

```bash
./setup_once.sh
```

## Start

Windows:

```bat
.\start_realtime_studio.bat
```

macOS / Linux:

```bash
./start_realtime_studio.sh
```

## Jak to dziala

- GUI, backend i LLM dzialaja lokalnie.
- Dane ruchowe trafiaja do lokalnego backendu.
- Backend wysyla zapytania do lokalnego LLM.
- Feedback i logi sa widoczne od razu w tym samym oknie.

## Kiedy nie uzywac tego folderu

Nie uzywaj `FullApp`, jesli:
- backend i LLM maja dzialac na innym komputerze
- chcesz miec osobny komputer tylko do podgladu GUI

W takim przypadku uzyj:
- `ComputeNode`
- `RemoteGUI`
