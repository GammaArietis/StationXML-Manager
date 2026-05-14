# StationXML Manager

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![PyQt6](https://img.shields.io/badge/desktop-PyQt6-41CD52.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![NiceGUI](https://img.shields.io/badge/web-NiceGUI-589636.svg)](https://nicegui.io/)
[![ObsPy](https://img.shields.io/badge/StationXML-ObsPy-orange.svg)](https://docs.obspy.org/)
[![Pydantic v2](https://img.shields.io/badge/models-Pydantic-FF4B4B.svg)](https://docs.pydantic.dev/)
[![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC.svg)](https://pytest.org/)

**StationXML Manager** è un gestore avanzato multipiattaforma dei metadati sismici in formato **FDSN StationXML**. Consente di modellare reti, stazioni e canali in un database **SQLite**, arricchire i dati con cataloghi **NRL** (locale) e **AROL**, importare ed esportare inventari tramite **ObsPy**, sincronizzare le stazioni con **Yasmine** (SCADA) e operare sia da **applicazione desktop (PyQt6)** sia da **interfaccia web (NiceGUI)** e **API REST (FastAPI)**.

---

## Indice

1. [Architettura e tecnologie](#architettura-e-tecnologie)
2. [Requisiti](#requisiti)
3. [Installazione e setup](#installazione-e-setup)
4. [Configurazione](#configurazione)
5. [Avvio dell’applicazione](#avvio-dellapplicazione)
6. [Guida all’uso dettagliata](#guida-alluso-dettagliata)
7. [API REST](#api-rest)
8. [Testing](#testing)
9. [Struttura del repository](#struttura-del-repository)
10. [Contribuire](#contribuire)

---

## Architettura e tecnologie

### Pattern a layer (Clean Architecture orientata al dominio)

Il flusso dati e le regole di business seguono una catena coerente:

**UI (PyQt6 o NiceGUI) → Controller → Service → DAO → SQLite**

- **UI**: form, alberi di navigazione, dialoghi (desktop in `ui/`, web in `web_gui/`).
- **Controller**: adattano la UI allo stato dell’applicazione e invocano i servizi (`controllers/`).
- **Service**: logica di dominio condivisa (validazione geografica, hash di sincronizzazione Yasmine, regole su catalogo e canali) in `core/services/`.
- **DAO**: accesso ai dati e query SQL in `database/daos/`.
- **Database**: `DatabaseManager` (connessioni SQLite, WAL, foreign key) e schema in `database/schema.sql`.

L’**API REST** (`web_api/main_web.py`) espone le stesse operazioni passando dai **Service**, non dai DAO direttamente nelle route, così da mantenere allineamento tra desktop, web e integrazioni esterne.

### Stack principale

| Componente | Ruolo |
|------------|--------|
| **PyQt6** | Applicazione desktop nativa (`main.py`, `ui/`). |
| **NiceGUI** | UI web reattiva montata sull’app FastAPI (`main_nicegui.py`, `web_gui/`). |
| **FastAPI + Uvicorn** | API HTTP, OpenAPI `/docs`, middleware CORS e rate limiting opzionale. |
| **ObsPy** | Lettura/scrittura StationXML (`importer/`, `exporter/`). |
| **Pydantic / pydantic-settings** | Modelli tipizzati (`core/models/`) e configurazione da variabili d’ambiente (`.env`). |
| **SQLite** | Persistenza locale, adatta a laboratorio e campo. |
| **requests** | Client HTTP (Yasmine, servizi di arricchimento opzionali). |

Cataloghi strumentali:

- **NRL v2 (locale)**: cartella `utils/NRL_v2/` usata da `utils/nrl_client.py` (`NRLManager`).
- **AROL**: libreria YAML/JSON in `utils/AROL_Library/` e client in `utils/arol_client.py`.

---

## Requisiti

- **Python 3.10 o superiore** (allineato a `pyproject.toml` e alla CI su GitHub Actions).
- Spazio su disco per il database, i log e (opzionale) i dataset NRL/AROL.
- Per la sola **API** o la **Web GUI** è comunque consigliabile aver inizializzato il database almeno una volta (vedi sotto), perché lo schema viene creato in modo esplicito dall’app desktop o dagli script di test.

---

## Installazione e setup

### 1. Clonare il repository

```bash
git clone <URL-del-tuo-repository>
cd StationXML-Manager-V1
```

### 2. Ambiente virtuale (consigliato)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# oppure:  .venv\Scripts\activate   # Windows
```

### 3. Installare le dipendenze

Installazione completa (runtime + test, come in CI):

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

Per un ambiente solo operativo (senza suite di test), è sufficiente:

```bash
pip install -r requirements.txt
```

### 4. Prima inizializzazione del database

Il file SQLite e le tabelle vengono creati alla prima esecuzione dell’app **desktop**, che applica `database/schema.sql` (percorsi configurabili via `.env`).

```bash
python main.py
```

In assenza di questo passaggio, Web/API potrebbero puntare a un database non inizializzato. In alternativa si può importare uno StationXML valido subito dopo il primo avvio.

### 5. (Opzionale) File di ambiente

```bash
cp .env.example .env
```

Modificare `DATABASE_PATH`, `YASMINE_BASE_URL`, `CORS_ORIGINS`, ecc. secondo l’ambiente (vedi [Configurazione](#configurazione)).

---

## Configurazione

Le impostazioni sono caricate da variabili d’ambiente e dal file **`.env`** tramite `core.config.AppSettings`.

| Variabile | Descrizione |
|-----------|-------------|
| `DATABASE_PATH` | Percorso del file SQLite (default: `data/stationxml.db`). |
| `SCHEMA_PATH` | File SQL di creazione tabelle (default: `database/schema.sql`). |
| `YASMINE_BASE_URL` | URL base dell’istanza Yasmine (default: `http://127.0.0.1:1841`). |
| `CORS_ORIGINS` | Origini consentite per il browser, separate da virgole. Con `DEBUG=true` è possibile usare `*` solo in sviluppo locale. |
| `DEBUG` | Abilita comportamenti permissivi (es. CORS wildcard). |
| `API_RATE_LIMIT_PER_MINUTE` | Limite richieste per IP sul prefisso `/api/` (0 = disattivato). |
| `LOG_FILE_PATH` | File di log applicativo (default: `app.log`). |

---

## Avvio dell’applicazione

Tutti i comandi si intendono dalla **radice del repository**, con il virtualenv attivo.

### Desktop (PyQt6) — interfaccia completa

```bash
python main.py
```

Include albero Rete → Stazione → Canale, import/export StationXML, sincronizzazione Yasmine in blocco, cataloghi NRL/AROL, strumenti di deduplica matematica sul catalogo, ecc.

Variabile utile in ambienti senza display (CI, server headless):

```bash
export QT_QPA_PLATFORM=offscreen   # Linux: evita errori se Qt viene importato dai test
```

### Web GUI (NiceGUI + FastAPI)

L’interfaccia web registra le pagine sull’istanza FastAPI condivisa e avvia il runtime NiceGUI.

```bash
python main_nicegui.py
```

In alternativa, in produzione o dietro reverse proxy, si può servire la stessa app ASGI con Uvicorn (stesso modulo `app` esposto dopo il caricamento di `main_nicegui`):

```bash
uvicorn main_nicegui:app --host 0.0.0.0 --port 8080
```

L’URL predefinito in sviluppo è tipicamente **http://127.0.0.1:8080** (verificare l’output a console di NiceGUI/Uvicorn).

### Solo API REST (senza pagine NiceGUI)

```bash
uvicorn web_api.main_web:app --reload --host 0.0.0.0 --port 8000
```

Documentazione interattiva: **http://127.0.0.1:8000/docs**

> **Nota:** `web_api.main_web` e `main_nicegui` condividono lo stesso file di database configurato in `.env`. Assicurarsi che lo schema sia già stato creato (es. tramite `python main.py` almeno una volta).

---

## Guida all’uso dettagliata

### Navigazione e gerarchia Rete → Stazione → Canale

1. **Selezione**  
   - **Desktop**: usare l’albero a sinistra; selezionando un nodo si apre il tab corrispondente (Rete, Stazione, Canale).  
   - **Web**: struttura ad albero analoga; il pannello centrale mostra il form della risorsa selezionata.

2. **Creazione**  
   - Creare prima una **Rete** (codice univoco nel contesto operativo, descrizione, date, DOI e operatore se necessario).  
   - Aggiungere **Stazioni** associate alla rete (coordinate obbligatorie per la validazione di dominio).  
   - Aggiungere **Canali** sulla stazione (codice, location, orientamento, campionamento, collegamento a sensori/datalogger di catalogo).

3. **Modifica e salvataggio**  
   Compilare i campi nel form e usare il pulsante di salvataggio (etichette dipendono dalla vista). I controller aggiornano il database tramite i servizi; in caso di errori di validazione (es. coordinate) viene mostrato un messaggio esplicito.

4. **Date di inizio e fine (Start / End Date) — uso sicuro**  
   Per **Rete**, **Stazione** e **Canale** (desktop), le date non sono sempre obbligatorie: accanto agli editor data/ora trovate le caselle **«Set»** (checkbox).

   - Se **Start Date** non è spuntata come «Set», il valore inviato al modello può restare vuoto / nullo, evitando di forzare un’epoca fittizia.  
   - Stessa logica per **End Date**: attivare «Set» solo quando si intende chiudere formalmente il periodo di validità (epoch FDSN).  
   Questo riduce il rischio di serializzare date non volute negli export StationXML.

5. **Eliminazione**  
   Rispettare l’ordine gerarchico imposto dalle foreign key: rimuovere prima canali, poi stazioni, poi reti, oppure usare le funzioni di cancellazione guidata dall’interfaccia che tengono conto dei vincoli.

### Import ed export StationXML

#### Import

- **Desktop**: dal menu principale / azioni di import (file `.xml` o inventario multi-rete). Il modulo `importer/stationxml_parser.py` usa **ObsPy** (`read_inventory`), normalizza i metadati (inclusi valori opzionali FDSN come `restrictedStatus`) e salva su SQLite tramite i controller.  
- **Web**: voce di import con **upload** del file; il file viene analizzato lato server e l’albero viene ricostruito al termine.

In caso di file molto grandi, attendere il completamento della notifica o del dialogo di progresso.

#### Export

- **Desktop** (`Export XML` nella barra strumenti): si apre un dialogo con due modalità principali:

  - **Inventario unico**: un file StationXML che raccoglie le stazioni selezionate secondo le regole dell’export classico.  
  - **Archivio ZIP**: un file **`.xml` per stazione** (nomi basati sul codice stazione), utile per pacchetti da caricare su sistemi che richiedono file separati.

- **Web** (`Esportazione selettiva`): tabella delle stazioni con selezione multipla e selettore **Modalità export**:

  - **Un unico file** (`inventory_export.xml`): comportamento analogo all’inventario singolo; con più righe selezionate può essere generato un inventario aggregato secondo la logica implementata in `StationXMLWebExportController`.  
  - **ZIP per stazione** (`stations_export.zip`): contiene un XML per ogni stazione selezionata.

La generazione byte avviene tramite `exporter/stationxml_builder.py` (`StationXMLExporter`).

### Catalogo strumenti, NRL e AROL

#### Catalogo locale (Sensori, Datalogger, preamplificatori, operatori)

- Le schede **catalogo** (desktop e web) permettono di **creare**, **modificare**, **clonare** e **eliminare** voci.  
- L’**eliminazione** può essere bloccata se un canale referenzia ancora lo strumento (errore di dominio `EquipmentInUseError`).

#### NRL (Network Reference Libraries) integrato

- Il client locale `NRLManager` carica la copia in **`utils/NRL_v2/`**.  
- Dalle schede catalogo si può navigare la gerarchia NRL e applicare i coefficienti al modello selezionato o ai canali (flussi «refresh» / applicazione dati secondo la vista).  
- Funzioni di **aggiornamento massivo** da NRL (dove presenti nel menu desktop) ricalcolano i modelli collegati e possono invalidare la sincronizzazione Yasmine delle stazioni interessate.

#### AROL (libreria locale)

- I componenti in **`utils/AROL_Library/objects`** sono esplorabili tramite **AROL Browser** (dialogo desktop o pannello web).  
- Per i **datalogger** AROL richiede spesso una composizione **a più stadi** (es. analogico + digitale/FIR): seguire la procedura guidata fino al salvataggio nel catalogo.

#### Deduplica e qualità dati

- Il dialogo **deduplica matematica** confronta modelli di catalogo (hash / equivalenza funzionale) per ridurre duplicati accidentali. È disponibile in varianti desktop e web a seconda del modulo caricato.

### Sincronizzazione Yasmine

**Yasmine** è un sistema esterno (tipicamente in ascolto su `YASMINE_BASE_URL`) che riceve file StationXML per stazione.

1. **Invio dati**  
   Dalla vista stazione (desktop) è possibile inviare l’XML corrente verso Yasmine (upload multipart). Dopo un invio riuscito, l’applicazione tenta di recuperare l’**ID nodo** Yasmine e salvarlo in `yasmine_sync_state`.

2. **Stato di allineamento (icone)**  
   - **Verde**: hash locale registrato in sync coincide con l’impronta calcolata sui campi chiave della stazione (allineato).  
   - **Rosso**: la stazione è stata modificata dopo l’ultimo invio; l’archivio Yasmine è considerato obsoleto.  
   - **Bianco / non sincronizzato**: mai inviata o senza record di sync.

3. **Hash SHA-256**  
   La funzione `calculate_station_hash` in `core/services/station_service.py` costruisce una stringa normalizzata da codice rete, coordinate, quota, data di inizio, ecc., e ne calcola l’**SHA-256** esadecimale. Questo valore viene confrontato con `local_xml_hash` memorizzato dopo l’ultimo sync riuscito.

4. **Sincronizzazione in blocco (desktop)**  
   È disponibile un’azione per inviare in sequenza tutte le stazioni «rosse», con barra di avanzamento e possibilità di annullamento.

5. **Arricchimento metadati (web)**  
   La Web GUI può offrire flussi di **arricchimento** (es. geografia/geologia da coordinate) prima o indipendentemente dall’upload Yasmine; consultare le notifiche nell’interfaccia per l’esito.

Assicurarsi che Yasmine sia raggiungibile dalla macchina che esegue StationXML Manager e che `YASMINE_BASE_URL` sia corretto.

---

## API REST

- Prefisso risorse: `/api/networks`, `/api/stations`, `/api/channels`, endpoint di catalogo (sensori, datalogger, preamplificatori, operatori), in linea con i modelli Pydantic esposti in OpenAPI.  
- Autenticazione: secondo quanto eventualmente aggiunto in deployment (l’istanza di default è pensata per rete attendibile / laboratorio).  
- **Rate limiting**: configurabile con `API_RATE_LIMIT_PER_MINUTE`.

Per dettagli su payload e codici di risposta usare la documentazione **Swagger** su `/docs`.

---

## Testing

La suite di test usa **pytest** e database temporanei (fixture `app_stack` in `tests/conftest.py`).

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -v --tb=short
```

La pipeline GitHub Actions (`.github/workflows/pytest.yml`) esegue gli stessi comandi su **Python 3.11** con `QT_QPA_PLATFORM=offscreen` per evitare dipendenze da display.

---

## Struttura del repository

| Percorso | Contenuto |
|----------|-----------|
| `main.py` | Entry point desktop. |
| `main_nicegui.py` | Entry point web (NiceGUI + FastAPI). |
| `web_api/` | Applicazione FastAPI, servizi e middleware. |
| `ui/` | Finestre e viste PyQt6. |
| `web_gui/` | Pagine e componenti NiceGUI. |
| `controllers/` | Controller UI / export web. |
| `core/` | Modelli Pydantic, servizi, validatori, configurazione. |
| `database/` | `DatabaseManager`, DAO, `schema.sql`. |
| `importer/` / `exporter/` | Parser e builder StationXML (ObsPy). |
| `utils/` | NRL, AROL, client Yasmine, logging, client geocoding/geologia. |
| `tests/` | Test di integrazione e unitari. |

---

## Contribuire

Linee guida operative in **[CONTRIBUTING.md](CONTRIBUTING.md)** (setup, stile, test e pull request).

---

## Licenza e crediti

Eventuale licenza del progetto va definita dal maintainer (nel repository è presente materiale di terze parti sotto `utils/AROL_Library/` con licenza dedicata: vedere i file `LICENSE` nella sottocartella ove applicabile).
