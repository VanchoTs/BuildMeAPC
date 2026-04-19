import json

from database.session import SessionLocal
from models.case import Case
from ai.case_normalization import (
    _clean_str,
    normalize_case_brand,
    normalize_case_model,
    normalize_case_size,
    normalize_motherboard_form_factors,
    normalize_included_fans,
    normalize_max_mm,
    normalize_max_radiator_mm,
    normalize_io_json,
)


def _normalize_brand(value):
    return normalize_case_brand(value)


def _normalize_model(value, brand=None):
    return normalize_case_model(value, brand=brand)


def _normalize_case_size(value):
    return normalize_case_size(value)


def _normalize_motherboard_form_factors(value):
    return normalize_motherboard_form_factors(value)


def _normalize_included_fans(value):
    return normalize_included_fans(value)


def _normalize_max_mm(value):
    return normalize_max_mm(value)


def _normalize_max_radiator_mm(value):
    return normalize_max_radiator_mm(value)


def _normalize_io_json(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return normalize_io_json(value)
    return normalize_io_json(value)


def upsert_case(case_data: dict) -> int | None:
    session = SessionLocal()
    try:
        product_url = _clean_str(case_data.get("url") or case_data.get("product_url"))
        brand = _normalize_brand(case_data.get("brand"))
        model = _normalize_model(case_data.get("model"), brand=brand)
        case_size = _normalize_case_size(case_data.get("case_size"))
        motherboard_form_factors = _normalize_motherboard_form_factors(
            case_data.get("motherboard_form_factors")
        )
        included_fans = _normalize_included_fans(case_data.get("included_fans"))
        max_cpu_cooler_mm = _normalize_max_mm(case_data.get("max_cpu_cooler_mm"))
        max_gpu_length_mm = _normalize_max_mm(case_data.get("max_gpu_length_mm"))
        max_psu_length_mm = _normalize_max_mm(case_data.get("max_psu_length_mm"))
        max_radiator_mm = _normalize_max_radiator_mm(case_data.get("max_radiator_mm"))
        io_json = _normalize_io_json(case_data.get("io_json"))
        price_raw = case_data.get("price") if case_data.get("price") is not None else case_data.get("price_eur")
        price_eur = float(price_raw) if price_raw is not None else None

        row = None
        if product_url:
            row = session.query(Case).filter(Case.product_url == product_url).first()

        dedupe_ready = brand is not None and model is not None
        if row is None and dedupe_ready:
            row = (
                session.query(Case)
                .filter(
                    Case.brand == brand,
                    Case.model == model,
                )
                .first()
            )

        if row is None:
            row = Case()
            session.add(row)

        row.brand = brand
        row.model = model
        row.case_size = case_size
        row.motherboard_form_factors = motherboard_form_factors
        row.included_fans = included_fans
        row.max_cpu_cooler_mm = max_cpu_cooler_mm
        row.max_gpu_length_mm = max_gpu_length_mm
        row.max_psu_length_mm = max_psu_length_mm
        row.max_radiator_mm = max_radiator_mm
        row.io_json = io_json
        row.price_eur = price_eur
        row.product_url = product_url

        session.commit()
        return row.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
