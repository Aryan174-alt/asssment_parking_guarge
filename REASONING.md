# Design Decisions & Reasoning

## Problem Understanding
The system manages a busy multi-level parking garage where vehicles arrive and leave throughout the day. The attendant must:
- Quickly check vehicles in/out with automatic spot assignment
- Calculate fees based on a tiered pricing model (first hour premium, subsequent hours discounted, daily cap)
- Enforce that EV vehicles only park in EV-equipped spots and regular vehicles never occupy EV spots
- Handle simultaneous check-in requests without ever double-booking a spot

## Architecture Decisions

### 1. Database-Level Concurrency Safety
**Problem:** A naive `if not spot.is_occupied` check in Python is vulnerable to race conditions. Two requests could read `is_occupied = False` at the same instant and both succeed.

**Solution:** I implemented **partial unique indexes** in SQLite:
```sql
CREATE UNIQUE INDEX uix_active_spot ON tickets(spot_id) WHERE status = 'active';
CREATE UNIQUE INDEX uix_active_vehicle ON tickets(vehicle_id) WHERE status = 'active';
```
If two simultaneous requests try to create an active ticket for the same spot, the database will throw an `IntegrityError`. Flask catches this and returns a `409 Conflict`.

### 2. Fee Calculation as a Pure Function
The fee calculator is isolated in `parking_logic.py` with no Flask or database dependencies. This makes it trivially unit-testable. I included 5 inline assertions that verify the logic for:
- Exactly 1 hour (first-hour rate)
- 1hr 1min (rounds up to 2 hours)
- Multi-day stays (daily cap applied per 24-hour period)
- Stays that exceed the daily cap within a single day

### 3. Spot Allocation Strategy
- **EV vehicles** are strictly routed to EV spots only.
- **Regular vehicles** are first assigned to Standard spots. If none are available, they fall back to Compact. They are **never** placed in EV spots.

### 4. Session-Based Authentication
I chose Flask sessions over JWT for simplicity. The `login_required` decorator checks `session['user_id']` and returns `401 Unauthorized` if missing. The frontend's `api()` wrapper intercepts 401 responses and redirects to the login page automatically.

### 5. Premium Dark-Mode UI
The V2 frontend uses:
- A custom CSS design system with glassmorphism cards, gradient accents, and micro-animations
- Toast notifications for real-time feedback on check-in/check-out operations
- Live stat cards that update immediately after every action
- Inline vehicle search results with full history
- Paginated, sortable ticket history with status filter

## Testing Approach
- **Unit Tests:** Fee calculator assertions in `parking_logic.py`
- **Integration Tests:** Automated API test script (`test_api.py`) hitting all endpoints
- **Visual Tests:** Browser-based walkthrough of the full check-in/check-out flow
- **Edge Cases Verified:**
  - No available spot → clear error
  - EV into non-EV → rejected
  - Regular into EV → rejected
  - Duplicate check-in → rejected
  - Check-out with no active ticket → clear error
  - Pagination beyond available data → empty results, no crash
