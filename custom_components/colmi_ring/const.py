DOMAIN = "colmi_ring"
PLATFORMS = ["sensor"]

CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DB_PATH = "db_path"

DEFAULT_SCAN_INTERVAL = 3600
RECENT_ADVERTISEMENT_SECONDS = 300
DEFAULT_DB_FILENAME = "colmi_ring_history.sqlite3"

SERVICE_SCAN = "scan"
SERVICE_SYNC = "sync"
SERVICE_READ_REALTIME = "read_realtime"
SERVICE_TEST_CONNECTION = "test_connection"

ATTR_READING = "reading"
ATTR_START = "start"
ATTR_END = "end"

READING_HEART_RATE = "heart-rate"
READING_SPO2 = "spo2"

DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"
DATA_STORE = "store"