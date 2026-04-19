import re

from database.session import SessionLocal
from models.psu import PSU
from ai.psu_normalization import (
    _clean_str,
    normalize_psu_brand,
    normalize_psu_model,
    normalize_psu_physical_size,
    normalize_psu_power_w,
    normalize_psu_efficiency,
    normalize_psu_certificate,
    normalize_psu_modularity,
    normalize_psu_fan_size_mm,
)

def _normalize_brand(value):
    return normalize_psu_brand(value)


def _normalize_model(value):
    return normalize_psu_model(value)


def _normalize_physical_size(value):
    return normalize_psu_physical_size(value)


def _normalize_power_w(value):
    return normalize_psu_power_w(value)


def _normalize_efficiency(value):
    return normalize_psu_efficiency(value)


def _normalize_certificate(value):
    return normalize_psu_certificate(value)


def _normalize_modularity(value):
    return normalize_psu_modularity(value)


def _normalize_fan_size_mm(value):
    return normalize_psu_fan_size_mm(value)


def upsert_psu(psu_data: dict):
    session = SessionLocal()
    try:
        product_url = _clean_str(psu_data.get("url") or psu_data.get("product_url"))
        brand = _normalize_brand(psu_data.get("brand"))
        model = _normalize_model(psu_data.get("model"))
        physical_size = _normalize_physical_size(psu_data.get("physical_size"))
        power_w = _normalize_power_w(psu_data.get("power_w") or psu_data.get("power"))
        efficiency = _normalize_efficiency(psu_data.get("efficiency"))
        certificate = _normalize_certificate(psu_data.get("certificate"))
        modularity = _normalize_modularity(psu_data.get("modularity"))
        fan_size_mm = _normalize_fan_size_mm(psu_data.get("fan_size_mm"))
        price_raw = psu_data.get("price") if psu_data.get("price") is not None else psu_data.get("price_eur")
        price_eur = float(price_raw) if price_raw is not None else None

        row = None
        if product_url:
            row = session.query(PSU).filter(PSU.product_url == product_url).first()

        dedupe_ready = all(
            value is not None
            for value in (brand, model, power_w)
        )
        if row is None and dedupe_ready:
            row = (
                session.query(PSU)
                .filter(
                    PSU.brand == brand,
                    PSU.model == model,
                    PSU.power_w == power_w,
                    PSU.physical_size == physical_size,
                    PSU.certificate == certificate,
                    PSU.modularity == modularity,
                )
                .first()
            )

        if row is None:
            row = PSU()
            session.add(row)

        row.brand = brand
        row.model = model
        row.physical_size = physical_size
        row.power_w = power_w
        row.efficiency = efficiency
        row.certificate = certificate
        row.modularity = modularity
        row.fan_size_mm = fan_size_mm
        row.price_eur = price_eur
        row.product_url = product_url

        session.commit()
        return row.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
