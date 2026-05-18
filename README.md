# StationXML Manager

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Desktop](https://img.shields.io/badge/desktop-PyQt6-41CD52.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![Web](https://img.shields.io/badge/web-NiceGUI-589636.svg)](https://nicegui.io/)
[![API](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![StationXML](https://img.shields.io/badge/StationXML-ObsPy-orange.svg)](https://docs.obspy.org/)
[![Models](https://img.shields.io/badge/models-Pydantic_v2-FF4B4B.svg)](https://docs.pydantic.dev/)

**StationXML Manager** è un gestore production-ready per metadati sismici in formato **FDSN StationXML**. L'applicazione consente di curare reti, stazioni, canali, cataloghi strumentali, operatori, risposte strumentali e flussi di sincronizzazione usando un'architettura ibrida composta da **Desktop PyQt6**, **Web NiceGUI** e **API FastAPI** sopra lo stesso modello dati SQLite.

Il progetto nasce per un uso operativo reale: importazione assistita da ObsPy, validazione dei metadati, deduplicazione matematica degli strumenti, generazione FDSN dei canali triassiali, Triad Epoch Sync, sincronizzazione con Yasmine ed esportazione StationXML atomica per singola stazione.

---

## Indice

1. [Panoramica](#panoramica)
2. [Funzionalita avanzate](#funzionalita-avanzate)
3. [Architettura e concorrenza](#architettura-e-concorrenza)
4. [Import ed export StationXML](#import-ed-export-stationxml)
5. [Configurazione](#configurazione)
6. [Setup e installazione](#setup-e-installazione)
7. [Avvio dell'applicazione](#avvio-dellapplicazione)
8. [Struttura del repository](#struttura-del-repository)
9. [Testing](#testing)
10. [Note operative](#note-operative)

---

## Panoramica

StationXML Manager adotta una **architettura ibrida cooperativa**:

- **Desktop PyQt6**: interfaccia nativa per workstation, ideale per catalogazione locale, editing intensivo, dialoghi guidati, import/export manuale e uso offline o di laboratorio.
- **NiceGUI Web Server**: interfaccia browser per accesso multiutente su rete locale o server headless, senza richiedere un desktop environment sulla macchina host.
- **FastAPI REST API**: backend HTTP per integrazioni, automazioni e strumenti esterni.

Le tre superfici non duplicano la logica di dominio. Desktop, Web e API condividono controller, servizi, DAO, modelli Pydantic e database SQLite. Questo significa che una regola importante, come il salvataggio atomico di una terna di canali o la normalizzazione di un import StationXML, viene implementata una sola volta e beneficia tutti gli entry point.

Il vantaggio operativo della soluzione duale e' concreto:

- un operatore puo' usare l'app Desktop per manutenzione dettagliata e controlli locali;
- un team puo' usare l'interfaccia Web da browser mantenendo la stessa base dati;
- un server headless puo' inizializzare database e Web UI senza avviare Qt;
- le integrazioni possono usare FastAPI senza bypassare le regole di business;
- gli interventi di robustezza, concorrenza e validazione hanno effetto uniforme su tutta l'app.

---

## Funzionalita avanzate

### Triad Epoch Sync atomico e idempotente

Il **Triad Epoch Sync** mantiene coerenti le date di fine validita' dei canali fratelli di una terna triassiale, ad esempio `HHZ`, `HHN`, `HHE`. Quando viene impostata una `end_date` su un canale, il servizio cerca i canali fratelli nella stessa stazione con lo stesso prefisso a due lettere e la stessa `start_date` normalizzata, quindi applica la stessa `end_date`.

La logica e' stata resa production-ready:

- **atomica**: salvataggio del canale corrente, invalidazione dello stato di sync e aggiornamento dei fratelli avvengono nella stessa transazione SQLite;
- **idempotente**: se il form Web modifica l'oggetto in-place o la data risulta gia' presente sul canale corrente, il sync puo' comunque riallineare i fratelli;
- **difensiva sulle date**: vengono normalizzate differenze comuni come `T` ISO, spazio tra data/ora e secondi mancanti;
- **visibile all'utente**: il backend restituisce l'elenco dei canali aggiornati, cosi' Desktop e Web possono notificare cosa e' stato sincronizzato.

Questo evita una delle regressioni piu' pericolose nei metadati sismici: chiudere un componente della terna e lasciare aperti gli altri due, generando epoche incoerenti nell'export StationXML.

### Deduplicatore matematico di strumenti

Il deduplicatore non si limita a confrontare marca e modello. Confronta rappresentazioni funzionali degli strumenti:

- poli, zeri e sensibilita' dei sensori;
- catene di filtri, decimazioni, gain, delay e correction dei datalogger;
- stadi analogici dei preamplificatori.

Questa scelta e' importante perche' StationXML importati da fonti diverse, cataloghi NRL locali e definizioni AROL possono descrivere lo stesso strumento con testi non identici. La deduplicazione matematica riduce il rumore del catalogo, favorisce una libreria strumentale piu' pulita e consente di sostituire riferimenti duplicati con un modello master.

### Importazione assistita con ObsPy e errori trasparenti

L'import StationXML passa da `importer/stationxml_parser.py` e usa ObsPy per leggere l'inventario. Il parser converte reti, stazioni, canali, operatori, sensori, datalogger, preamplificatori e risposte strumentali nei modelli interni, salvandoli tramite controller e DAO.

La gestione degli errori e' ora esplicita:

- gli errori critici vengono loggati con stack trace completo tramite `logger.exception`;
- i fallimenti vengono propagati come `StationXMLImportError`;
- la Web UI mostra notifiche negative con messaggio specifico;
- il Desktop mostra dialoghi di errore con il dettaglio ricevuto dal worker;
- i fallback su lookup strumentali registrano warning espliciti, invece di assegnare silenziosamente `None`.

In produzione questo riduce drasticamente il tempo di diagnosi: un file StationXML malformato o un'incompatibilita' ObsPy non viene piu' nascosta dietro un generico "import failed".

### Export atomico per singola stazione

L'export e' stato rifattorizzato: la **singola stazione** e' ora l'unita' minima di generazione StationXML.

Il builder espone API dedicate:

- `build_station_inventory(station_id)`;
- `build_stationxml_bytes(station_id)`;
- `station_xml_filename(station_id)`.

Il nome file usa solo il codice stazione in maiuscolo: `ZOE.xml`, `MDN.xml`, `ABCD.xml`. Il codice rete resta correttamente dentro il contenuto XML, ma non compare nel filename.

La distribuzione dipende dall'interfaccia:

- **Web, una stazione selezionata**: download diretto di `STATION.xml`;
- **Web, due o piu' stazioni**: download di `stations_export.zip` con un XML per stazione;
- **Desktop**: selezione tramite checkbox inizialmente deselezionate, pulsanti rapidi "Seleziona Tutto" e "Deseleziona Tutto", scelta di una cartella e scrittura di file individuali.

Questa strategia elimina il costo del vecchio inventario globale. Costruire un unico oggetto ObsPy con tutte le stazioni puo' consumare molta RAM, amplificare i tempi di serializzazione e rendere difficile isolare l'errore se una sola stazione e' problematica. Il modello per-stazione mantiene l'uso memoria prevedibile, riduce i colli di bottiglia e produce file piu' adatti a Yasmine o a sistemi che archiviano metadati per stazione.

### Wizard FDSN per canali triassiali

Il wizard di auto-generazione canali collega la UI alla logica fisica FDSN:

- ricava il sample rate finale dal datalogger;
- propone il Band Code SEED in base a frequenza e natura del sensore;
- forza correttamente gli accelerometri come broadband per il calcolo della prima lettera;
- deduce l'Instrument Code da `input_units`;
- permette override manuale di Band Code, Instrument Code e Sensor Type;
- assegna `start_time` ai tre canali generati;
- calcola la Total Sensitivity dagli stadi associati.

Il risultato e' una generazione assistita, ma non rigida: l'operatore mantiene il controllo finale prima del salvataggio.

---

## Architettura e concorrenza

### Pattern Service-DAO

Il flusso logico principale e':

```text
PyQt6 UI / NiceGUI UI / FastAPI
        |
Controller
        |
Service
        |
DAO
        |
SQLite
```

- Le **UI** raccolgono input, mostrano feedback e delegano le azioni.
- I **Controller** traducono eventi di interfaccia in chiamate di dominio.
- I **Service** contengono regole condivise, validazioni, sincronizzazioni e transazioni multi-step.
- I **DAO** eseguono query SQL e trasformano righe SQLite in modelli applicativi.
- Il **DatabaseManager** centralizza connessioni, PRAGMA SQLite, schema e transazioni.

Questo pattern limita la duplicazione. La UI Desktop e la UI Web possono essere diverse nell'esperienza utente, ma condividono la stessa semantica di salvataggio, import, export e validazione.

### Thread-safety SQLite

SQLite permette molte letture concorrenti ma un solo writer alla volta. StationXML Manager puo' ricevere scritture da piu' sorgenti:

- salvataggi manuali Desktop;
- sessioni browser NiceGUI;
- route FastAPI;
- worker di import/export;
- ricalcoli globali di sensibilita';
- sincronizzazioni Yasmine o operazioni NRL.

Per evitare `database is locked`, corruzioni logiche e mezze scritture, `database/db_manager.py` introduce un **write-lock globale applicativo**:

- le query `SELECT` restano libere e parallele;
- le query mutanti (`INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, `DROP`, `BEGIN`, ecc.) acquisiscono il lock;
- `commit`, `rollback` e `close` rilasciano il lock;
- le operazioni multi-step possono usare `write_transaction()`.

Le transazioni esplicite usano `BEGIN IMMEDIATE`. Questo riserva subito lo slot di scrittura SQLite, evitando che una procedura lunga inizi a leggere/modificare e fallisca solo a meta'. Nel Triad Epoch Sync, ad esempio, se l'aggiornamento di un fratello fallisce, l'intera terna torna allo stato precedente tramite rollback.

### Isolamento sessioni Web

La Web UI NiceGUI usa `app.storage.user` per salvare stato di navigazione per singola sessione browser:

- rete corrente;
- stazione corrente;
- canale corrente;
- nodi dell'albero espansi;
- nodo selezionato.

Lo storage e' firmato con `NICEGUI_STORAGE_SECRET`. Per questo la variabile e' critica in produzione: protegge l'integrita' del session storage multiutente ed evita che utenti diversi si sovrascrivano lo stato di navigazione. I controller Web vengono istanziati per sessione/pagina quando necessario, evitando un oggetto globale mutabile condiviso tra browser diversi.

---

## Import ed export StationXML

### Import

Il flusso di import e':

```text
File StationXML -> ObsPy Inventory -> Modelli Pydantic -> Service/DAO -> SQLite
```

Il parser prova a preservare e normalizzare:

- Network, Station e Channel;
- epoche di validita';
- operatori e contatti;
- restricted status e metadati FDSN opzionali;
- sensori con poli/zeri;
- datalogger con stadi, delay e correction;
- preamplificatori e sensibilita'.

In caso di errore, l'importer non fallisce piu' in modo silenzioso. La UI riceve un messaggio specifico e il log contiene lo stack trace completo.

### Export

Il flusso di export e':

```text
station_id -> ObsPy Inventory della singola stazione -> bytes XML -> file/download
```

L'export per-stazione e' intenzionale per tre motivi:

- **memoria**: il builder mantiene in RAM un inventario piccolo e circoscritto;
- **debug**: se una stazione produce XML non valido, l'errore e' isolato;
- **operativita'**: i sistemi esterni spesso accettano o archiviano StationXML per stazione.

Il Web usa ZIP solo come contenitore di trasporto per selezioni multiple. Il Desktop scrive direttamente i file nella cartella scelta, senza creare archivi intermedi.

---

## Configurazione

Creare il file locale:

```bash
cp .env.example .env
```

Variabili principali:

| Variabile | Descrizione |
| --- | --- |
| `DATABASE_PATH` | Percorso del database SQLite, default `data/stationxml.db`. |
| `SCHEMA_PATH` | Percorso dello schema SQL, default `database/schema.sql`. |
| `LOG_FILE_PATH` | File di log applicativo. |
| `LOG_LEVEL` | Livello di verbosita' desiderato per il deployment (`INFO`, `DEBUG`, ecc.). |
| `NICEGUI_STORAGE_SECRET` | Segreto per firmare lo storage utente NiceGUI. Deve essere lungo, casuale e privato in produzione. |
| `YASMINE_BASE_URL` | URL dell'istanza Yasmine. |
| `CORS_ORIGINS` | Origini browser consentite, separate da virgola. |
| `API_RATE_LIMIT_PER_MINUTE` | Rate limit opzionale sulle API sotto `/api/`. |

Generare un secret sicuro:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

---

## Setup e installazione

### 1. Clonare il repository

```bash
git clone <repository-url>
cd StationXML-Manager-V1
```

### 2. Creare un ambiente virtuale

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Installare le dipendenze runtime

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Per sviluppo e test, se presente:

```bash
python -m pip install -r requirements-dev.txt
```

### 4. Preparare la configurazione

```bash
cp .env.example .env
```

Modificare almeno:

- `DATABASE_PATH`;
- `LOG_FILE_PATH`;
- `NICEGUI_STORAGE_SECRET`;
- `YASMINE_BASE_URL`, se si usa Yasmine.

L'inizializzazione del database e' centralizzata e idempotente. Sia l'entrypoint Desktop sia quello Web chiamano la procedura di init all'avvio, quindi il primo avvio crea automaticamente file SQLite e tabelle necessarie.

---

## Avvio dell'applicazione

Eseguire i comandi dalla root del repository con virtualenv attivo.

### Desktop PyQt6

Nel repository attuale l'entrypoint Desktop e':

```bash
python main.py
```

Se la distribuzione o il packaging espone un alias `main_desktop.py`, il comando equivalente e':

```bash
python main_desktop.py
```

La modalita' Desktop e' consigliata per editing locale intensivo, gestione cataloghi, import manuali ed export in cartella.

### Server Web NiceGUI

```bash
python main_nicegui.py
```

NiceGUI avvia il server e mostra l'URL in console. In produzione impostare sempre `NICEGUI_STORAGE_SECRET` prima dell'avvio.

### Solo API FastAPI

```bash
uvicorn web_api.main_web:app --host 0.0.0.0 --port 8000
```

Documentazione OpenAPI:

```text
http://127.0.0.1:8000/docs
```

---

## Struttura del repository

| Percorso | Contenuto |
| --- | --- |
| `main.py` | Entry point Desktop PyQt6. |
| `main_nicegui.py` | Entry point Web NiceGUI montato su FastAPI. |
| `web_api/` | Route API, middleware, CORS e rate limiting. |
| `ui/` | Finestre, tab, dialoghi e widget PyQt6. |
| `web_gui/` | Viste e componenti NiceGUI. |
| `controllers/` | Adattatori tra UI e servizi di dominio. |
| `core/models/` | Modelli Pydantic. |
| `core/services/` | Logica condivisa, validazioni e transazioni. |
| `database/` | `DatabaseManager`, DAO e `schema.sql`. |
| `importer/` | Parser StationXML basato su ObsPy. |
| `exporter/` | Builder StationXML e utility di export per-stazione. |
| `utils/` | NRL, AROL, Yasmine, logging, geocoding e helper FDSN. |
| `tests/` | Test pytest e fixture. |

---

## Testing

Eseguire la suite:

```bash
python -m pytest tests/ -v --tb=short
```

Su ambienti CI/headless che importano PyQt6:

```bash
export QT_QPA_PLATFORM=offscreen
python -m pytest tests/ -v --tb=short
```

---

## Note operative

- Eseguire backup regolari di `data/stationxml.db`.
- Usare un `NICEGUI_STORAGE_SECRET` forte e diverso per ogni deployment Web.
- Evitare merge distruttivi del catalogo mentre sono attivi import massivi o ricalcoli globali.
- Preferire l'export per-stazione per scambi operativi e sincronizzazione Yasmine.
- Consultare `app.log` quando import, export o validazioni segnalano anomalie.

---

## Contribuire

Le linee guida operative sono in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Licenza e crediti

La licenza del progetto viene definita dal maintainer. Alcuni materiali di riferimento in `utils/AROL_Library/` possono avere licenze proprie; verificare i file `LICENSE` nelle sottocartelle prima della redistribuzione.
