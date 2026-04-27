import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.base import Base
from models.cpu import CPU
from storage.cpu_repository import upsert_cpu
import database.engine as db_engine

@pytest.fixture
def test_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(db_engine, "engine", engine)
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    monkeypatch.setattr("storage.cpu_repository.SessionLocal", Session)
    # Also need to monkeypatch other repositories if tested
    
    yield session
    session.close()

def test_upsert_cpu(test_db):
    cpu_data = {
        "model": "Ryzen 5 5600X",
        "brand": "AMD",
        "socket": "AM4",
        "cores": 6,
        "threads": 12,
        "base_clock": 3.7,
        "boost_clock": 4.6,
        "tdp": 65,
        "price": 299.99,
        "url": "https://example.com/cpu",
        "name": "AMD Ryzen 5 5600X"
    }
    
    # First insert
    upsert_cpu(cpu_data)
    cpu = test_db.query(CPU).filter_by(model="Ryzen 5 5600X").first()
    assert cpu is not None
    assert cpu.price_eur == 299.99
    
    # Update
    cpu_data["price"] = 280.0
    upsert_cpu(cpu_data)
    test_db.expire_all()
    cpu = test_db.query(CPU).filter_by(model="Ryzen 5 5600X").first()
    assert cpu.price_eur == 280.0
