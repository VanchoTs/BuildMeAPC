from sqlalchemy import text
from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.rams') IS NOT NULL")
        ).scalar()
        if exists:
            print("rams table already exists; nothing to do.")
            return
        conn.execute(text("""
                CREATE TABLE rams (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    memory_type VARCHAR,
                    memory_amount VARCHAR,
                    memory_speed_mhz INTEGER,
                    latency VARCHAR,
                    form_factor VARCHAR,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """))
        conn.commit()
        print("Created rams table.")


if __name__ == "__main__":
    main()
