from sqlalchemy import text

from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.ssds') IS NOT NULL")).scalar()
        if exists:
            print("ssds table already exists; nothing to do.")
            return
        conn.execute(
            text(
                """
                CREATE TABLE ssds (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    type VARCHAR,
                    storage_size_gb INTEGER,
                    physical_size VARCHAR,
                    read_speed_mbps INTEGER,
                    write_speed_mbps INTEGER,
                    interface VARCHAR,
                    tbw_tb INTEGER,
                    nand_type VARCHAR,
                    has_heatsink BOOLEAN,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """
            )
        )
        conn.commit()
        print("Created ssds table.")


if __name__ == "__main__":
    main()
