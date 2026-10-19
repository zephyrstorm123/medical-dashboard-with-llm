from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def create_encrypted_engine(data_key: bytes, db_path: str) -> Engine:


    if len(data_key) != 32:
        raise ValueError(f"Data key must be 32 bytes long, got {len(data_key)} bytes.")

    #Convert key to SQLCipher hex format: x'<64 hexadecimal characters>'
    key_hex = data_key.hex().upper()

    db_url = f"sqlite:///{db_path}"

    engine = create_engine(      
        db_url, 
        connect_args={"uri": False}, #Use pysqlite (bundled sqlite 3) backend
        pool_pre_ping=True,  # Ensure connections are alive before using them
        echo=False #Echo SQL statements for debugging
    )

    @event.listens_for(engine, "connect")
    def set_sqlcipher_key(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # Step 1: Unlock database with key
        cursor.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        # Step 2: Pin encryption compatibility to SQLCipher v4
        cursor.execute("PRAGMA cipher_compatibility = 4")
        # Step 3: Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON")
        # Step 4: Set journal mode to WAL for better concurrency
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    return engine
    