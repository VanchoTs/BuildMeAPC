from sqlalchemy import text

from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.cases') IS NOT NULL")).scalar()
        if exists:
            print("cases table already exists; nothing to do.")
            return
        conn.execute(
            text(
                """
                CREATE TABLE cases (
                    id SERIAL PRIMARY KEY,
                    brand VARCHAR,
                    model VARCHAR,
                    case_size VARCHAR,
                    motherboard_form_factors VARCHAR,
                    included_fans INTEGER,
                    max_cpu_cooler_mm INTEGER,
                    max_gpu_length_mm INTEGER,
                    max_psu_length_mm INTEGER,
                    max_radiator_mm INTEGER,
                    io_json JSONB,
                    price_eur FLOAT,
                    product_url VARCHAR,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now()
                )
                """
            )
        )
        conn.commit()
        print("Created cases table.")


if __name__ == "__main__":
    main()
