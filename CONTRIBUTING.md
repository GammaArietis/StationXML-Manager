# Contribuire a StationXML Manager

Grazie per l’interesse nel migliorare **StationXML Manager**. Questo documento descrive come allinearsi allo stack esistente e proporre modifiche in modo sicuro e revisionabile.

## Ambiente di sviluppo

1. **Python 3.10+** (3.11 è la versione usata in CI).
2. Clonare il repository e creare un virtualenv (vedi [README.md](README.md#installazione-e-setup)).
3. Installare le dipendenze complete:

   ```bash
   python -m pip install --upgrade pip
   pip install -r requirements.txt -r requirements-dev.txt
   ```

4. Eseguire i test prima di aprire una PR:

   ```bash
   python -m pytest tests/ -v --tb=short
   ```

5. Per sviluppo UI **PyQt6** su Linux senza display fisico, esportare `QT_QPA_PLATFORM=offscreen` se importi moduli Qt da script o test.

## Architettura da rispettare

- **Non aggirare i layer**: la UI non deve chiamare i DAO direttamente; preferire **Controller → Service → DAO**. Eccezioni documentate (es. wiring in `main_nicegui.py`) vanno discusse prima di estenderle.
- **Modelli**: usare i tipi Pydantic in `core/models/base_models.py` (o moduli dedicati) per dati che attraversano servizi e API.
- **Condivisione logica**: se una regola è usata da desktop, web e REST, implementarla in `core/services/` e richiamarla dai controller o dalle route FastAPI.
- **Import StationXML**: modifiche al parsing in `importer/stationxml_parser.py` devono considerare valori FDSN assenti o `None` (come da ObsPy), normalizzando prima della validazione Pydantic.
- **Database**: ogni modifica allo schema richiede aggiornamento di `database/schema.sql` e, se necessario, migrazioni manuali o script documentati nel messaggio di commit.

## Stile del codice

- Preferire **type hints** su funzioni e metodi pubblici dei servizi e dei controller.
- Seguire lo stile già presente nel file che si modifica (naming, import assoluti da radice progetto, livello di logging).
- Evitare refactor massivi non richiesti nella stessa PR di una correzione mirata.
- Messaggi di commit in **inglese o italiano** coerente con la storia del repository; devono descrivere il *perché* oltre al *cosa*.

## Test

- Aggiungere o aggiornare test in `tests/` per ogni correzione di bug nella logica di dominio o nel parser/export.
- Usare le fixture `temp_db` e `app_stack` da `tests/conftest.py` per integrazione con SQLite in isolamento.
- I test che dipendono da **ObsPy** devono usare `pytest.importorskip("obspy")` se applicabile, così ambienti minimali possono saltarli in modo esplicito.

## Pull request

1. Una PR per argomento logico (es. «fix hash Yasmine» separato da «nuovo campo API»).
2. Descrizione chiara: contesto, approccio, limiti noti.
3. Confermare che `pytest` passa localmente (o indicare se un fallimento è noto e tracciato).
4. Allegare screenshot solo per cambiamenti UI rilevanti.

## Segnalazione bug

Includere: versione di Python, sistema operativo, comandi di avvio, passi per riprodurre, messaggio di errore completo o traceback, e se possibile un file StationXML **anonimizzato** che scatena il problema.

## Domande

Per decisioni architetturali ampie, aprire una discussione (issue) prima di investire tempo su refactor di larga scala.
