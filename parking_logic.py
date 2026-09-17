import math
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from models import ParkingSpot

# ── Default Rate Configuration ─────────────────────────────────────
DEFAULT_RATE_CARDS = {
    'standard': {'first_hour': 10.0, 'additional_hour': 5.0, 'daily_cap': 50.0},
    'compact': {'first_hour': 8.0, 'additional_hour': 4.0, 'daily_cap': 40.0},
    'ev': {'first_hour': 12.0, 'additional_hour': 6.0, 'daily_cap': 60.0}
}

ACTIVE_RATE_CARDS = dict(DEFAULT_RATE_CARDS)


# ── Messy Rate Card Cleaner (Twist 1 / Level 1 — T4) ────────────────
def clean_numeric_value(val: Any, default: float = 0.0) -> float:
    """Extracts a clean float from messy string representations ($10.50/hr, USD 5, etc.)."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    
    val_str = str(val).strip().replace(',', '.')
    match = re.search(r'[-+]?\d+(?:\.\d+)?', val_str)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return default
    return default


def normalize_spot_type(raw_type: str) -> str:
    """Maps various messy names to canonical spot types: standard, compact, ev."""
    t = str(raw_type).strip().lower()
    if 'ev' in t or 'elec' in t or 'charge' in t:
        return 'ev'
    if 'comp' in t or 'small' in t:
        return 'compact'
    return 'standard'


def clean_rate_card(raw_data: Any) -> Dict[str, Dict[str, float]]:
    """
    Parses and cleans messy rate card data per spot type.
    Accepts lists of dicts, nested dicts, raw text rows, etc.
    """
    cleaned: Dict[str, Dict[str, float]] = {
        'standard': dict(DEFAULT_RATE_CARDS['standard']),
        'compact': dict(DEFAULT_RATE_CARDS['compact']),
        'ev': dict(DEFAULT_RATE_CARDS['ev'])
    }

    if not raw_data:
        return cleaned

    # If raw_data is a list of entries
    entries = raw_data if isinstance(raw_data, list) else [raw_data]
    if isinstance(raw_data, dict) and not any(k in ('type', 'spot_type', 'rates') for k in raw_data.keys()):
        # Nested dict like {'standard': {'first_hour': '$10'}}
        for s_type_key, s_values in raw_data.items():
            s_type = normalize_spot_type(s_type_key)
            if isinstance(s_values, dict):
                first_hr = None
                add_hr = None
                d_cap = None
                for k, v in s_values.items():
                    kl = str(k).lower()
                    if 'first' in kl or '1st' in kl or 'initial' in kl or 'start' in kl:
                        first_hr = clean_numeric_value(v)
                    elif 'add' in kl or 'extra' in kl or 'subseq' in kl or 'hour' in kl:
                        add_hr = clean_numeric_value(v)
                    elif 'cap' in kl or 'max' in kl or 'day' in kl or 'daily' in kl:
                        d_cap = clean_numeric_value(v)
                
                if first_hr is not None: cleaned[s_type]['first_hour'] = first_hr
                if add_hr is not None: cleaned[s_type]['additional_hour'] = add_hr
                if d_cap is not None: cleaned[s_type]['daily_cap'] = d_cap
        return cleaned

    for item in entries:
        if not isinstance(item, dict):
            continue
        
        # Spot type resolution
        raw_type = item.get('spot_type') or item.get('type') or item.get('category') or item.get('spot') or 'standard'
        s_type = normalize_spot_type(raw_type)

        first_hr = None
        add_hr = None
        d_cap = None

        for k, v in item.items():
            kl = str(k).lower()
            if 'first' in kl or '1st' in kl or 'initial' in kl:
                first_hr = clean_numeric_value(v)
            elif 'add' in kl or 'extra' in kl or 'subseq' in kl or ('hour' in kl and 'first' not in kl and '1st' not in kl):
                add_hr = clean_numeric_value(v)
            elif 'cap' in kl or 'max' in kl or 'day' in kl or 'daily' in kl:
                d_cap = clean_numeric_value(v)
            elif kl in ('rate', 'flat_rate', 'price') and first_hr is None:
                first_hr = clean_numeric_value(v)
                if add_hr is None:
                    add_hr = clean_numeric_value(v)

        if first_hr is not None: cleaned[s_type]['first_hour'] = first_hr
        if add_hr is not None: cleaned[s_type]['additional_hour'] = add_hr
        if d_cap is not None: cleaned[s_type]['daily_cap'] = d_cap

    return cleaned


def set_active_rate_cards(new_rates: Dict[str, Dict[str, float]]):
    global ACTIVE_RATE_CARDS
    ACTIVE_RATE_CARDS = new_rates


# ── Fee Calculation ────────────────────────────────────────────────
def calculate_fee(check_in_time: datetime, check_out_time: datetime, spot_type: str = 'standard', custom_rates: Optional[Dict[str, Any]] = None) -> float:
    """
    Tiered fee calculator for given spot type.
    - First hour: flat first_hour
    - Each additional hour (partial hours round UP): flat additional_hour
    - Daily cap: daily_cap per 24-hour period
    """
    # Normalize datetimes to UTC if one is timezone aware and the other is not
    if check_in_time.tzinfo is None and check_out_time.tzinfo is not None:
        check_in_time = check_in_time.replace(tzinfo=timezone.utc)
    elif check_in_time.tzinfo is not None and check_out_time.tzinfo is None:
        check_out_time = check_out_time.replace(tzinfo=timezone.utc)

    if check_out_time <= check_in_time:
        return 0.0

    rates_source = custom_rates or ACTIVE_RATE_CARDS
    s_type = normalize_spot_type(spot_type)
    rates = rates_source.get(s_type, DEFAULT_RATE_CARDS['standard'])

    first_hour_fee = rates.get('first_hour', 10.0)
    additional_hour_fee = rates.get('additional_hour', 5.0)
    daily_cap = rates.get('daily_cap', 50.0)

    total_seconds = (check_out_time - check_in_time).total_seconds()
    total_hours = math.ceil(total_seconds / 3600.0)

    if total_hours == 0:
        total_hours = 1

    full_days = total_hours // 24
    remaining_hours = total_hours % 24

    fee = full_days * daily_cap

    if remaining_hours > 0:
        daily_fee = first_hour_fee
        if remaining_hours > 1:
            daily_fee += (remaining_hours - 1) * additional_hour_fee
        fee += min(daily_fee, daily_cap)

    return float(round(fee, 2))


def find_available_spot(vehicle_type: str) -> Optional[ParkingSpot]:
    """
    Spot-matching logic with strict type enforcement:
    - EV vehicles → EV spots only
    - Regular vehicles → Standard first, then Compact. Never EV.
    """
    if vehicle_type.lower() == 'ev':
        return ParkingSpot.query.filter_by(type='ev', is_occupied=False).first()
    else:
        spot = ParkingSpot.query.filter_by(type='standard', is_occupied=False).first()
        if not spot:
            spot = ParkingSpot.query.filter_by(type='compact', is_occupied=False).first()
        return spot


# ── Self-test assertions (run with: python parking_logic.py) ──────
if __name__ == '__main__':
    from datetime import timedelta

    now = datetime.now(timezone.utc)

    # Test clean rate card
    messy_sample = [
        {"spot_type": "  cOMPACT  ", "1st_hour_rate": " $ 6.50 / hr ", "extra_hour": " $3.00 ", "daily_max": "USD 30.00"},
        {"type": "⚡ EV_Charger", "first": "€ 15.00", "subsequent": "7.50 / hr", "daily_cap": " $75.00 "}
    ]
    cleaned = clean_rate_card(messy_sample)
    assert cleaned['compact']['first_hour'] == 6.50
    assert cleaned['compact']['additional_hour'] == 3.00
    assert cleaned['compact']['daily_cap'] == 30.00
    assert cleaned['ev']['first_hour'] == 15.00
    assert cleaned['ev']['additional_hour'] == 7.50
    assert cleaned['ev']['daily_cap'] == 75.00

    # Exactly 1 hour standard
    assert calculate_fee(now, now + timedelta(hours=1)) == 10.0

    # 1 hour 1 minute standard → rounds up to 2 hours ($10 + $5 = $15)
    assert calculate_fee(now, now + timedelta(hours=1, minutes=1)) == 15.0

    # Compact rate with custom rates
    assert calculate_fee(now, now + timedelta(hours=2), spot_type='compact', custom_rates=cleaned) == 9.50

    print("All fee calculation & messy rate cleaner assertions passed!")
