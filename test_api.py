import urllib.request
import urllib.parse
import urllib.error
import json
import http.cookiejar
import time

# Give the server a moment to start
time.sleep(2)

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
urllib.request.install_opener(opener)

def api_call(endpoint, data=None, method=None):
    url = f"http://127.0.0.1:5000/api/{endpoint}"
    headers = {'Content-Type': 'application/json'}
    
    if data:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    else:
        req = urllib.request.Request(url, headers=headers, method=method or 'GET')
    
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))
    except Exception as e:
        return 500, str(e)

print("Starting API Tests...\n")

# 1. Register
status, res = api_call("auth/register", {"username": "testuser", "password": "testpassword"})
print(f"Register: [{status}] {res}")

# 2. Login
status, res = api_call("auth/login", {"username": "testuser", "password": "testpassword"})
print(f"Login: [{status}] {res}")

# 3. EV Availability
status, res = api_call("parking/ev-availability")
print(f"EV Spots Available: [{status}] {res}")

# 4. Check-In Regular
status, res = api_call("parking/check-in", {"plate_number": "ABC-123", "vehicle_type": "regular"})
print(f"Check-In Regular: [{status}] {res}")

# 5. Check-In EV
status, res = api_call("parking/check-in", {"plate_number": "EV-999", "vehicle_type": "ev"})
print(f"Check-In EV: [{status}] {res}")

# 6. Check-Out Regular
status, res = api_call("parking/check-out", {"plate_number": "ABC-123"})
print(f"Check-Out Regular: [{status}] {res}")

# 7. Get Tickets (Pagination & Sorting)
status, res = api_call("tickets?limit=2")
print(f"Tickets List: [{status}] {res}")

print("\nAll tests completed.")
