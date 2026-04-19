from sqlalchemy import text

from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.psus') IS NOT NULL")).scalar()
        if exists:
            print("psus table already exists; nothing to do.")
            return
        conn.execute(
            text(
                """
                CREATE TABLE psus (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    physical_size VARCHAR,
                    power_w INTEGER,
                    efficiency VARCHAR,
                    certificate VARCHAR,
                    modularity VARCHAR,
                    fan_size_mm INTEGER,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """
            )
        )
        conn.commit()
        print("Created psus table.")


if __name__ == "__main__":
    main()
