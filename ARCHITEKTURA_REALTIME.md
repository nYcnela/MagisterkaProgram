# Architektura realtime

Diagram: [ARCHITEKTURA_REALTIME.svg](./ARCHITEKTURA_REALTIME.svg)

## Docelowy przeplyw danych

1. `VR` wybiera taniec i wysyla do `ComputeNode` komunikat sterujacy `session_start` na port UDP `5006`.
2. Ten sam sygnal `VR` wysyla do procesu `Kalman`, aby rozpoczal streamowanie klatek.
3. Po okolo `3 s` `Kalman` zaczyna wysylac klatki ruchu do backendu w `ComputeNode` na port UDP `5005`.
4. Docelowo `Kalman` i backend dzialaja na tym samym komputerze, wiec klatki moga isc lokalnie na `127.0.0.1:5005`.
5. Backend w `ComputeNode` zbiera strumien do okien czasowych `4.0 s` ze skokiem `3.0 s`.
6. Dla kazdego pelnego okna backend liczy metryki ruchu i przygotowuje wejscie dla modelu jezykowego.
7. Backend wysyla zapytanie do lokalnego serwera `LLM` po HTTP na `127.0.0.1:8000`.
8. `LLM` zwraca tekst feedbacku i wynik punktowy. `ComputeNode` zapisuje artefakty runu, aktualizuje logi i ostatni feedback.
9. `RemoteGUI` na drugim komputerze laczy sie tylko z `ComputeNode`, nie z `LLM`.
10. `RemoteGUI` pobiera stan po HTTP `8010` i odbiera logi / status / ostatni feedback przez WebSocket `ws://<compute-node>:8010/ws/events`.
11. Po zakonczeniu tanca `VR` wysyla `session_end` na `5006`, a `Kalman` zatrzymuje stream klatek.

## Czas pojawienia sie pierwszego feedbacku

Przy zalozeniu:
- opoznienie startu streamu z `Kalman`: okolo `3 s`
- dlugosc pierwszego okna backendu: `4 s`

pierwszy feedback pojawi sie po mniej wiecej:
- `3 s` oczekiwania na start streamu
- `4 s` zbierania pierwszego pelnego okna
- `+` czas obliczen backendu i odpowiedzi `LLM`

W praktyce pierwszy feedback pojawi sie po okolo `7 s + czas przetwarzania`.
Kazdy kolejny feedback moze pojawiac sie mniej wiecej co `3 s + czas przetwarzania`, bo stride backendu wynosi `3.0 s`.

## Porty w aktualnej konfiguracji

- `5005/UDP` - klatki ruchu z `Kalman` do backendu
- `5006/UDP` - sterowanie sesja: `session_prepare`, `session_start`, `session_end`
- `8000/HTTP` - lokalny serwer `LLM` na komputerze z `ComputeNode`
- `8010/HTTP + WebSocket` - API i monitoring dla `RemoteGUI`

## Wariant testowy

Jesli `Kalman` dziala na innym komputerze niz `ComputeNode`, wtedy:
- klatki wysylane sa na `IP_ComputeNode:5005`
- sterowanie sesja wysylane jest na `IP_ComputeNode:5006`

Reszta przeplywu pozostaje taka sama: backend pyta lokalny `LLM`, a `RemoteGUI` laczy sie tylko z portem `8010`.
