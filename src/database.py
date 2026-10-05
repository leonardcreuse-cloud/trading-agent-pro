import sqlite3
import os
from datetime import datetime

class Database:
    """
    Database for Trading Agent Pro
    CRITICAL: Separate data_date (when data refers to) from retrieval_date (when we got it)
    """
    
    def __init__(self, db_path="../data/trading_pro.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.create_tables()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def create_tables(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                id INTEGER PRIMARY KEY,
                ticker TEXT NOT NULL,
                period TEXT NOT NULL,
                data_date DATE NOT NULL,
                publication_timestamp TIMESTAMP,
                revenue REAL,
                operating_income REAL,
                net_income REAL,
                free_cash_flow REAL,
                total_debt REAL,
                cash_and_equivalents REAL,
                source TEXT NOT NULL,
                retrieval_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_confidence INTEGER DEFAULT 95,
                UNIQUE(ticker, period, publication_timestamp),
                CHECK(publication_timestamp <= retrieval_timestamp)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insider_transactions (
                id INTEGER PRIMARY KEY,
                ticker TEXT NOT NULL,
                insider_name TEXT,
                transaction_type TEXT,
                transaction_date DATE NOT NULL,
                transaction_publication_timestamp TIMESTAMP,
                shares_count REAL,
                price_per_share REAL,
                transaction_value REAL,
                source TEXT DEFAULT 'SEC Form 4',
                discovered_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                retrieval_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK(transaction_publication_timestamp <= discovered_timestamp),
                CHECK(discovered_timestamp <= retrieval_timestamp)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY,
                ticker TEXT NOT NULL,
                price_date DATE NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                adjusted_close REAL,
                volume INTEGER,
                adjustment_date DATE,
                source TEXT DEFAULT 'yfinance',
                retrieval_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, price_date),
                CHECK(price_date <= retrieval_timestamp)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY,
                ticker TEXT,
                event_type TEXT NOT NULL,
                event_date DATE NOT NULL,
                event_time TIME,
                description TEXT,
                source TEXT,
                publication_timestamp TIMESTAMP,
                retrieval_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK(event_date <= date(retrieval_timestamp))
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS macro_indicators (
                id INTEGER PRIMARY KEY,
                indicator_name TEXT NOT NULL,
                data_date DATE NOT NULL,
                data_value REAL,
                source TEXT DEFAULT 'FRED',
                publication_timestamp TIMESTAMP,
                retrieval_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(indicator_name, data_date),
                CHECK(publication_timestamp <= retrieval_timestamp)
            )
        """)

        conn.commit()
        conn.close()
        print(f"Database: {self.db_path}")

if __name__ == "__main__":
    db = Database()
    print("Database created with PHASE 2 integrity checks")
