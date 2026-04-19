from sqlalchemy import text
from database.engine import engine


def main():
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.psus') IS NOT NULL")
        ).scalar()
        if not exists:
            print("psus table does not exist; run migrate_add_psus_table.py first.")
            return

        conn.execute(text("""
                ALTER TABLE psus
                DROP COLUMN IF EXISTS atx_standard
                """))
        conn.execute(text("""
                ALTER TABLE psus
                DROP COLUMN IF EXISTS pcie5_ready
                """))
        conn.execute(text("""
                ALTER TABLE psus
                DROP COLUMN IF EXISTS has_12vhpwr
                """))
        conn.execute(text("""
                ALTER TABLE psus
                DROP COLUMN IF EXISTS warranty_months
                """))
        conn.commit()
        print("Dropped non-essential PSU fields (atx_standard, pcie5_ready, has_12vhpwr, warranty_months).")


if __name__ == "__main__":
    main()
