# Multi-Level Parking Garage Management System

## Overview

A Flask and SQLite parking garage application with a browser dashboard, vehicle check-in and check-out, automatic spot assignment, tiered pricing, session authentication, and database-level protection against double booking.

## Project Structure

```text
app.py              Flask application and API routes
models.py           SQLAlchemy database models
parking_logic.py    Spot assignment, fee calculation, and rate cleaning
seed.py             Creates the database and default garage layout
templates/          HTML pages
static/             CSS and frontend assets
test_api.py         API smoke-test script
test_twists.py      Tests for the three twist requirements
REASONING.md        Design decisions and testing notes
requirements.txt    Python dependencies
```

## Setup

Use Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python seed.py
python app.py
```

Open `http://127.0.0.1:5000` in a browser.

Default account:

```text
Username: admin
Password: password123
```

The SQLite database is created at `instance/parking_v2.db`. It is local runtime data and is excluded from source control by `.gitignore`.

## Main API Routes

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register` | Register an account |
| POST | `/api/auth/login` | Start a session |
| POST | `/api/parking/check-in` | Park a regular or EV vehicle |
| POST | `/api/parking/check-out` | Complete a session and calculate its fee |
| GET | `/api/parking/vehicle/<plate>` | View vehicle status and history |
| GET | `/api/spots/summary` | View garage capacity |
| GET | `/api/tickets` | View paginated ticket history |

## Twist Requirements

### T4: Messy Rate Card Import

`POST /rates` accepts messy rate-card fields such as currency symbols, units, inconsistent names, and extra whitespace. The response returns canonical `standard`, `compact`, and `ev` rate cards.

### T2: Nightly Auto-Close

`POST /clock` closes and bills every active session parked for at least 24 hours. It accepts an ISO timestamp, for example:

```json
{"timestamp": "2026-09-18T12:00:00+00:00"}
```

### T6: Valet Transfer

`POST /tickets/transfer` moves an active session to a new plate while preserving its spot and check-in time:

```json
{"old_plate": "ABC-123", "new_plate": "VALET-456"}
```

## Testing

Start the server in one terminal, then run the twist tests in another:

```bash
python test_twists.py
```

The general API smoke test can be run with:

```bash
python test_api.py
```

Fee-calculation assertions can be run directly with:

```bash
python parking_logic.py
```

## Garage Layout

The seed script creates 18 spots across three levels: 3 EV, 8 standard, and 7 compact spots. Regular vehicles use standard spots first and compact spots as a fallback; EV vehicles use EV spots only.

## Database Safety

Partial unique indexes allow only one active ticket per spot and per vehicle. This protects against double-booking even when simultaneous requests reach the application.
