from sqlalchemy import text
from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.gpus') IS NOT NULL")
        ).scalar()
        if exists:
            print("gpus table already exists; nothing to do.")
            return
        conn.execute(text("""
                CREATE TABLE gpus (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    pcb_manufacturer VARCHAR,
                    pcb_series VARCHAR,
                    vram_gb INTEGER,
                    memory_type VARCHAR,
                    memory_bus_bit INTEGER,
                    base_clock_mhz FLOAT,
                    boost_clock_mhz FLOAT,
                    tdp_w INTEGER,
                    interface VARCHAR,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """))
        conn.commit()
        print("Created gpus table.")


if __name__ == "__main__":
    main()
