from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlcipher3 import dbapi2 as sqlcipher


def create_encrypted_engine(data_key: bytes, db_path: str) -> Engine:
    """Open (or create) the SQLCipher database at db_path with a raw 256-bit key."""
    if len(data_key) != 32:
        raise ValueError(f"Data key must be 32 bytes long, got {len(data_key)} bytes.")

    # Convert key to SQLCipher hex format: x'<64 hexadecimal characters>'
    key_hex = data_key.hex().upper()

    engine = create_engine(
        f"sqlite:///{db_path}",
        module=sqlcipher,  # SQLCipher's driver; plain sqlite3 would silently ignore PRAGMA key
        pool_pre_ping=True,  # Ensure connections are alive before using them
    )

    @event.listens_for(engine, "connect")
    def set_sqlcipher_key(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # Step 0: Refuse to continue if this connection can't encrypt (e.g. wrong driver)
        cursor.execute("PRAGMA cipher_version")
        if not cursor.fetchone():
            cursor.close()
            raise RuntimeError("SQLCipher is not active; refusing to open an unencrypted database")
        # Step 1: Unlock database with key
        cursor.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        # Step 2: Pin encryption compatibility to SQLCipher v4
        cursor.execute("PRAGMA cipher_compatibility = 4")
        # Step 3: Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON")
        # Step 4: Set journal mode to WAL (first read: fails here if the key is wrong)
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    return engine
