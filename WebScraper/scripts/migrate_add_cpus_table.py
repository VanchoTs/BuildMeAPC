from sqlalchemy import text
from database.engine import engine

def main():
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.cpus') IS NOT NULL")
        ).scalar()
        if exists:
            print("cpus table already exists; nothing to do.")
            return
        conn.execute(text("""
                CREATE TABLE cpus (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    socket VARCHAR,
                    cores INTEGER,
                    threads INTEGER,
                    base_clock_ghz FLOAT,
                    boost_clock_ghz FLOAT,
                    tdp_w INTEGER,
                    memory_type VARCHAR,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """))
        conn.commit()
        print("Created cpus table.")

if __name__ == "__main__":
    main()
