import requests
import json
from datetime import datetime, timezone, timedelta

BASE_URL = "http://127.0.0.1:5000"

def test_twist_level_1_messy_rates():
    print("\n=== Testing Level 1 (T4): Messy Rate Card Import ===")
    messy_payload = [
        {"spot_type": "  cOMPACT  ", "1st_hour_rate": " $ 7.50 / hr ", "extra_hour": " $3.50 ", "daily_max": "USD 35.00"},
        {"type": "Standard / Regular", "first": " $ 11.00 ", "subsequent": "5.50", "daily_cap": " $55.00 "},
        {"type": "⚡ EV_Charger", "first": "€ 14.00", "subsequent": "7.00 / hr", "daily_cap": " $70.00 "}
    ]
    res = requests.post(f"{BASE_URL}/rates", json=messy_payload)
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    print("Cleaned Rates:", json.dumps(data, indent=2))
    assert data["rates"]["compact"]["first_hour"] == 7.50
    assert data["rates"]["standard"]["first_hour"] == 11.00
    assert data["rates"]["ev"]["first_hour"] == 14.00
    print("Level 1 (T4) Passed!")

def test_twist_level_3_valet_transfer():
    print("\n=== Testing Level 3 (T6): Valet Session Transfer ===")
    # 1. Check in a vehicle
    plate_old = f"VALET-{int(datetime.now().timestamp()) % 10000:04d}"
    plate_new = f"HANDOFF-{int(datetime.now().timestamp()) % 10000:04d}"
    
    ci_res = requests.post(f"{BASE_URL}/api/parking/check-in", json={
        "plate_number": plate_old,
        "vehicle_type": "regular"
    })
    assert ci_res.status_code == 200, f"Check-in failed: {ci_res.text}"
    ci_data = ci_res.json()
    orig_spot = ci_data["spot"]
    orig_time = ci_data["check_in_time"]
    print(f"Vehicle {plate_old} checked in at Spot {orig_spot}")

    # 2. Transfer session to plate_new
    transfer_res = requests.post(f"{BASE_URL}/tickets/transfer", json={
        "old_plate": plate_old,
        "new_plate": plate_new
    })
    assert transfer_res.status_code == 200, f"Transfer failed: {transfer_res.text}"
    t_data = transfer_res.json()
    print(f"Transfer Response: {t_data['message']}")
    assert t_data["new_plate"] == plate_new
    assert t_data["spot"] == orig_spot
    assert t_data["check_in_time"] == orig_time

    # 3. Verify old plate is free and new plate is in the spot
    v_new_res = requests.get(f"{BASE_URL}/api/parking/vehicle/{plate_new}")
    assert v_new_res.status_code == 200
    assert v_new_res.json()["currently_parked"] == True
    assert v_new_res.json()["current_spot"] == orig_spot

    # Check out new plate
    co_res = requests.post(f"{BASE_URL}/api/parking/check-out", json={"plate_number": plate_new})
    assert co_res.status_code == 200, f"Checkout failed: {co_res.text}"
    print(f"Vehicle {plate_new} checked out successfully with fee ${co_res.json()['fee']:.2f}")
    print("Level 3 (T6) Passed!")

def test_twist_level_2_nightly_clock():
    print("\n=== Testing Level 2 (T2): Nightly Auto-Close via POST /clock ===")
    # 1. Check in a vehicle
    plate = f"NIGHT-{int(datetime.now().timestamp()) % 10000:04d}"
    ci_res = requests.post(f"{BASE_URL}/api/parking/check-in", json={
        "plate_number": plate,
        "vehicle_type": "regular"
    })
    assert ci_res.status_code == 200, f"Check-in failed: {ci_res.text}"
    ci_data = ci_res.json()
    spot = ci_data["spot"]
    print(f"Vehicle {plate} parked at Spot {spot}")

    # 2. Advance clock by 25 hours
    sim_time = (datetime.now(timezone.utc) + timedelta(hours=25)).isoformat()
    clock_res = requests.post(f"{BASE_URL}/clock", json={"timestamp": sim_time})
    assert clock_res.status_code == 200, f"Clock call failed: {clock_res.text}"
    clock_data = clock_res.json()
    print(f"Clock Response: {clock_data['message']}")
    print(f"Auto-closed count: {clock_data['auto_closed_count']}, Total billed: ${clock_data['total_billed']:.2f}")

    # Verify that the vehicle's session is now completed
    v_res = requests.get(f"{BASE_URL}/api/parking/vehicle/{plate}")
    assert v_res.status_code == 200
    assert v_res.json()["currently_parked"] == False
    print("Level 2 (T2) Passed!")

if __name__ == '__main__':
    test_twist_level_1_messy_rates()
    test_twist_level_3_valet_transfer()
    test_twist_level_2_nightly_clock()
    print("\nALL 3 TWIST LEVELS PASSED AUTOMATED TESTS SUCCESSFULLY!")
