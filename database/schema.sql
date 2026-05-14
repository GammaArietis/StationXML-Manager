PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS operator_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agency TEXT NOT NULL,
    contact_name TEXT,
    contact_email TEXT,
    phone_country_code INTEGER DEFAULT 39,
    phone_area_code INTEGER DEFAULT 0,
    phone_number TEXT,
    website TEXT,
    UNIQUE(agency, contact_name, contact_email)
);

CREATE TABLE IF NOT EXISTS sensor_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer TEXT NOT NULL,
    model TEXT NOT NULL UNIQUE,
    type TEXT,
    description TEXT,
    sensitivity REAL,
    frequency REAL,
    normalization_factor REAL,
    normalization_freq REAL,
    input_units TEXT DEFAULT 'm/s',
    output_units TEXT DEFAULT 'V',
    pz_transfer_function_type TEXT DEFAULT 'LAPLACE (RADIANS/SECOND)',
    nrl_path TEXT
);

CREATE TABLE IF NOT EXISTS sensor_zero (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL,
    real_val REAL NOT NULL,
    imag_val REAL NOT NULL,
    FOREIGN KEY(sensor_id) REFERENCES sensor_catalog(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sensor_pole (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL,
    real_val REAL NOT NULL,
    imag_val REAL NOT NULL,
    FOREIGN KEY(sensor_id) REFERENCES sensor_catalog(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS datalogger_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer TEXT NOT NULL,
    model TEXT NOT NULL UNIQUE,
    description TEXT,
    gain REAL,
    max_clock_drift REAL,
    base_hardware_delay REAL DEFAULT 0.0,
    base_hardware_correction REAL DEFAULT 0.0,
    nrl_path TEXT
);

CREATE TABLE IF NOT EXISTS datalogger_filter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datalogger_id INTEGER NOT NULL,
    stage_number INTEGER NOT NULL,
    filter_type TEXT,
    coefficients TEXT,
    decimation_factor INTEGER DEFAULT 1,
    input_sample_rate REAL,
    output_sample_rate REAL,
    estimated_delay REAL DEFAULT 0.0,
    correction_applied REAL DEFAULT 0.0,
    FOREIGN KEY(datalogger_id) REFERENCES datalogger_catalog(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS network (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    description TEXT,
    comments TEXT,
    start_date TEXT,
    end_date TEXT,
    doi TEXT,
    operator_id INTEGER,
    restricted_status TEXT DEFAULT 'open',
    UNIQUE(code, start_date),
    FOREIGN KEY (operator_id) REFERENCES operator_catalog(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS station (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    elevation REAL NOT NULL,
    water_level REAL,
    description TEXT,
    comments TEXT,
    town TEXT,
    county TEXT,
    region TEXT,
    country TEXT,
    site_name TEXT,
    start_date TEXT,
    end_date TEXT,
    creation_date TEXT,
    operator_id INTEGER,
    vault TEXT,
    geology TEXT,
    restricted_status TEXT DEFAULT 'open',
    UNIQUE(network_id, code, start_date),
    FOREIGN KEY (network_id) REFERENCES network (id) ON DELETE CASCADE,
    FOREIGN KEY (operator_id) REFERENCES operator_catalog(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS channel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    location_code TEXT DEFAULT '',
    latitude REAL,
    longitude REAL,
    elevation REAL, 
    depth REAL NOT NULL DEFAULT 0.0,
    azimuth REAL,
    dip REAL,
    sample_rate REAL NOT NULL,
    clock_drift REAL DEFAULT 0.0,
    calibration_units TEXT,
    pre_amplifier_id INTEGER,
    pre_amplifier_serial_number TEXT,
    pre_amplifier_gain REAL DEFAULT 1.0,
    sensor_id INTEGER,
    datalogger_id INTEGER,
    start_date TEXT,
    end_date TEXT,
    overall_sensitivity REAL,
    sensor_serial_number TEXT,
    datalogger_serial_number TEXT,
    comments TEXT,
    types TEXT DEFAULT 'CONTINUOUS,GEOPHYSICAL',
    UNIQUE(station_id, code, location_code, start_date),
    FOREIGN KEY (station_id) REFERENCES station (id) ON DELETE CASCADE,
    FOREIGN KEY (sensor_id) REFERENCES sensor_catalog(id) ON DELETE SET NULL,
    FOREIGN KEY (datalogger_id) REFERENCES datalogger_catalog(id) ON DELETE SET NULL,
    FOREIGN KEY (pre_amplifier_id) REFERENCES preamplifier_catalog(id) ON DELETE SET NULL
);

-- Preamplifier models catalog
CREATE TABLE IF NOT EXISTS preamplifier_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer TEXT NOT NULL,
    model TEXT NOT NULL UNIQUE,
    description TEXT,
    type TEXT DEFAULT 'PRE-AMPLIFIER'
);

-- Preamplifier Poles
CREATE TABLE IF NOT EXISTS preamplifier_pole (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preamplifier_id INTEGER NOT NULL,
    real_val REAL NOT NULL,
    imag_val REAL NOT NULL,
    FOREIGN KEY(preamplifier_id) REFERENCES preamplifier_catalog(id) ON DELETE CASCADE
);

-- Preamplifier Zeros
CREATE TABLE IF NOT EXISTS preamplifier_zero (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preamplifier_id INTEGER NOT NULL,
    real_val REAL NOT NULL,
    imag_val REAL NOT NULL,
    FOREIGN KEY(preamplifier_id) REFERENCES preamplifier_catalog(id) ON DELETE CASCADE
);

-- ==========================================
-- SCADA TABLE: Yasmine Synchronization State
-- ==========================================
CREATE TABLE IF NOT EXISTS yasmine_sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id INTEGER NOT NULL UNIQUE,
    yasmine_node_id TEXT,
    sync_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    local_xml_hash TEXT,
    FOREIGN KEY(station_id) REFERENCES station(id) ON DELETE CASCADE
);

-- NEW: Multiple analog stages for the preamplifier
CREATE TABLE IF NOT EXISTS preamplifier_stage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preamplifier_id INTEGER NOT NULL,
    stage_sequence INTEGER NOT NULL,
    stage_gain REAL DEFAULT 1.0,
    input_units TEXT DEFAULT 'V',
    output_units TEXT DEFAULT 'V',
    name TEXT,
    FOREIGN KEY(preamplifier_id) REFERENCES preamplifier_catalog(id) ON DELETE CASCADE
);

-- Poles associated with the single analog stage
CREATE TABLE IF NOT EXISTS preamplifier_stage_pole (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL,
    real_val REAL NOT NULL,
    imag_val REAL NOT NULL,
    FOREIGN KEY(stage_id) REFERENCES preamplifier_stage(id) ON DELETE CASCADE
);

-- Zeros associated with the single analog stage
CREATE TABLE IF NOT EXISTS preamplifier_stage_zero (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL,
    real_val REAL NOT NULL,
    imag_val REAL NOT NULL,
    FOREIGN KEY(stage_id) REFERENCES preamplifier_stage(id) ON DELETE CASCADE
);