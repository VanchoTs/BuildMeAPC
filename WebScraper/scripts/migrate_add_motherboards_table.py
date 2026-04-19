from sqlalchemy import text
from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.motherboards') IS NOT NULL")
        ).scalar()
        if exists:
            print("motherboards table already exists; nothing to do.")
            return
        conn.execute(text("""
                CREATE TABLE motherboards (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    form_factor VARCHAR,
                    chipset VARCHAR,
                    socket VARCHAR,
                    memory_type VARCHAR,
                    ram_slots INTEGER,
                    max_ram_speed_mhz INTEGER,
                    max_ram_amount_gb INTEGER,
                    onboard_wifi VARCHAR DEFAULT 'Not present',
                    io_json JSONB,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """))
        conn.commit()
        print("Created motherboards table.")


if __name__ == "__main__":
    main()
