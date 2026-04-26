import argparse
import os
from sqlalchemy import create_engine, text

# Database URL logic:
# 1. Use DATABASE_URL if provided in environment
# 2. Else, check if we are inside a docker container (host 'db')
# 3. Else, default to 'localhost'
if "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]
else:
    # Simple check for docker environment
    db_host = "db" if os.path.exists("/.dockerenv") else "localhost"
    DATABASE_URL = f"postgresql://pc_user:pc_password@{db_host}:5432/pc_builder"

def make_admin(full_name):
    """Update a user's role to admin if they exist in the DB."""
    engine = create_engine(DATABASE_URL)
    
    # We use a parameterized query to prevent SQL injection
    query = text("UPDATE users SET role = 'admin' WHERE full_name = :name RETURNING id, email")
    
    try:
        with engine.connect() as conn:
            # PostgreSQL requires explicit commit for connection-level execution in SQLAlchemy 2.0+
            result = conn.execute(query, {"name": full_name})
            conn.commit()
            
            row = result.fetchone()
            
            if row:
                user_id, email = row
                print(f"SUCCESS: User '{full_name}' (ID: {user_id}, Email: {email}) has been promoted to admin.")
            else:
                print(f"FAILED: No user found with the full name '{full_name}'.")
                
    except Exception as e:
        print(f"ERROR: Could not connect to database or execute query.\n{e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Promote a user to admin role by their full name.")
    parser.add_argument("name", help="The exact full name of the user to promote.")
    
    args = parser.parse_args()
    make_admin(args.name)
