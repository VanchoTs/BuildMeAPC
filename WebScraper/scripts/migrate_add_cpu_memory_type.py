from sqlalchemy import inspect, text

from database.engine import engine


def main() -> None:
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("cpus")}
    if "memory_type" in cols:
        print("cpus.memory_type already exists; nothing to do.")
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE cpus ADD COLUMN memory_type VARCHAR"))

    print("Added cpus.memory_type column.")


if __name__ == "__main__":
    main()
