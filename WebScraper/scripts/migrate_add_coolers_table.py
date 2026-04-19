from sqlalchemy import text

from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.coolers') IS NOT NULL")).scalar()
        if exists:
            print("coolers table already exists; nothing to do.")
            return
        conn.execute(
            text(
                """
                CREATE TABLE coolers (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    cooler_type VARCHAR,
                    socket_compatibility VARCHAR,
                    cooler_height_mm INTEGER,
                    tdp_w INTEGER,
                    fan_size_mm INTEGER,
                    fan_count INTEGER,
                    noise_db FLOAT,
                    rpm_max INTEGER,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """
            )
        )
        conn.commit()
        print("Created coolers table.")


if __name__ == "__main__":
    main()
