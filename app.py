from flask import Flask, jsonify, request, session, render_template, redirect, url_for
from config import Config
from models import db, User, ParkingSpot, Vehicle, Ticket
from parking_logic import calculate_fee, find_available_spot, clean_rate_card, set_active_rate_cards, ACTIVE_RATE_CARDS
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta
from functools import wraps
import os

# ── App Factory ────────────────────────────────────────────────────
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config.from_object(Config)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///parking_v2.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.urandom(24).hex()

db.init_app(app)


# ── Auth Decorator ─────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════
#  FRONTEND ROUTES
# ══════════════════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/dashboard')
def dashboard_page():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('dashboard.html')


# ══════════════════════════════════════════════════════════════════
#  AUTH API
# ══════════════════════════════════════════════════════════════════
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 409

    user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User registered successfully", "user_id": user.id}), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    user = User.query.filter_by(username=data.get('username', '')).first()
    if user and check_password_hash(user.password_hash, data.get('password', '')):
        session['user_id'] = user.id
        session['username'] = user.username
        return jsonify({"message": "Logged in", "username": user.username}), 200
    return jsonify({"error": "Invalid credentials"}), 401


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"}), 200


@app.route('/api/auth/me', methods=['GET'])
def me():
    if 'user_id' in session:
        return jsonify({"logged_in": True, "username": session.get('username')}), 200
    return jsonify({"logged_in": False}), 200


# ══════════════════════════════════════════════════════════════════
#  PARKING API
# ══════════════════════════════════════════════════════════════════
@app.route('/api/parking/check-in', methods=['POST'])
@login_required
def check_in():
    data = request.json or {}
    plate = data.get('plate_number', '').strip().upper()
    v_type = data.get('vehicle_type', 'regular').strip().lower()

    if not plate:
        return jsonify({"error": "License plate is required"}), 400
    if v_type not in ('regular', 'ev'):
        return jsonify({"error": "Vehicle type must be 'regular' or 'ev'"}), 400

    # Get or create the vehicle
    vehicle = Vehicle.query.filter_by(plate_number=plate).first()
    if not vehicle:
        vehicle = Vehicle(plate_number=plate, vehicle_type=v_type)
        db.session.add(vehicle)
        db.session.flush()

    # Reject if already checked in
    active = Ticket.query.filter_by(vehicle_id=vehicle.id, status='active').first()
    if active:
        return jsonify({"error": f"Vehicle {plate} is already checked in (Spot {active.spot.spot_number})"}), 400

    # Find a compatible spot
    spot = find_available_spot(v_type)
    if not spot:
        return jsonify({"error": f"No available {v_type.upper()} compatible spots"}), 400

    # Create ticket and mark spot occupied
    ticket = Ticket(vehicle_id=vehicle.id, spot_id=spot.id)
    spot.is_occupied = True
    db.session.add(ticket)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Race condition: spot was taken simultaneously. Please retry."}), 409

    return jsonify({
        "message": "Vehicle checked in successfully",
        "ticket_id": ticket.id,
        "spot": spot.spot_number,
        "level": spot.level,
        "spot_type": spot.type,
        "check_in_time": ticket.check_in_time.isoformat()
    }), 200


@app.route('/api/parking/check-out', methods=['POST'])
@login_required
def check_out():
    data = request.json or {}
    plate = data.get('plate_number', '').strip().upper()

    if not plate:
        return jsonify({"error": "License plate is required"}), 400

    vehicle = Vehicle.query.filter_by(plate_number=plate).first()
    if not vehicle:
        return jsonify({"error": f"Vehicle {plate} not found in the system"}), 404

    ticket = Ticket.query.filter_by(vehicle_id=vehicle.id, status='active').first()
    if not ticket:
        return jsonify({"error": f"No active ticket for vehicle {plate}"}), 400

    spot = db.session.get(ParkingSpot, ticket.spot_id)
    spot_type = spot.type if spot else 'standard'
    ticket.check_out_time = datetime.now(timezone.utc)
    ticket.fee = calculate_fee(ticket.check_in_time, ticket.check_out_time, spot_type)
    ticket.status = 'completed'

    if spot:
        spot.is_occupied = False

    db.session.commit()

    return jsonify({
        "message": "Vehicle checked out successfully",
        "plate": plate,
        "spot": spot.spot_number,
        "fee": ticket.fee,
        "duration_minutes": round((ticket.check_out_time - ticket.check_in_time).total_seconds() / 60, 1),
        "check_in_time": ticket.check_in_time.isoformat(),
        "check_out_time": ticket.check_out_time.isoformat()
    }), 200


# ══════════════════════════════════════════════════════════════════
#  SEARCH & AVAILABILITY API
# ══════════════════════════════════════════════════════════════════
@app.route('/api/parking/vehicle/<plate>', methods=['GET'])
@login_required
def get_vehicle(plate):
    plate = plate.strip().upper()
    vehicle = Vehicle.query.filter_by(plate_number=plate).first()
    if not vehicle:
        return jsonify({"error": f"Vehicle {plate} not found"}), 404

    tickets = Ticket.query.filter_by(vehicle_id=vehicle.id) \
        .order_by(Ticket.check_in_time.desc()).all()

    active = next((t for t in tickets if t.status == 'active'), None)

    return jsonify({
        "plate": vehicle.plate_number,
        "type": vehicle.vehicle_type,
        "currently_parked": active is not None,
        "current_spot": active.spot.spot_number if active else None,
        "total_visits": len(tickets),
        "history": [{
            "id": t.id,
            "spot": t.spot.spot_number,
            "status": t.status,
            "fee": t.fee,
            "check_in": t.check_in_time.isoformat(),
            "check_out": t.check_out_time.isoformat() if t.check_out_time else None
        } for t in tickets]
    }), 200


@app.route('/api/parking/ev-availability', methods=['GET'])
def ev_availability():
    total = ParkingSpot.query.filter_by(type='ev').count()
    available = ParkingSpot.query.filter_by(type='ev', is_occupied=False).count()
    return jsonify({
        "total_ev_spots": total,
        "available_ev_spots": available,
        "occupied_ev_spots": total - available
    }), 200


@app.route('/api/spots', methods=['GET'])
def get_spots():
    s_type = request.args.get('type')
    available = request.args.get('available')

    query = ParkingSpot.query
    if s_type:
        query = query.filter_by(type=s_type.lower())
    if available is not None:
        is_avail = available.lower() == 'true'
        query = query.filter_by(is_occupied=not is_avail)

    spots = query.order_by(ParkingSpot.level, ParkingSpot.spot_number).all()
    return jsonify({
        "count": len(spots),
        "spots": [{
            "id": s.id,
            "spot_number": s.spot_number,
            "level": s.level,
            "type": s.type,
            "is_occupied": s.is_occupied
        } for s in spots]
    }), 200


@app.route('/api/spots/summary', methods=['GET'])
def spots_summary():
    """Quick summary of garage capacity by type."""
    summary = {}
    for s_type in ['compact', 'standard', 'ev']:
        total = ParkingSpot.query.filter_by(type=s_type).count()
        occupied = ParkingSpot.query.filter_by(type=s_type, is_occupied=True).count()
        summary[s_type] = {"total": total, "occupied": occupied, "available": total - occupied}
    return jsonify(summary), 200


@app.route('/api/spots/full-map', methods=['GET'])
def get_spots_full_map():
    """Returns 2D map visualization data categorized by floor level with active tickets."""
    spots = ParkingSpot.query.order_by(ParkingSpot.level, ParkingSpot.spot_number).all()
    now = datetime.now(timezone.utc)
    
    levels_map = {}
    for s in spots:
        lvl = s.level
        if lvl not in levels_map:
            levels_map[lvl] = []
        
        active_ticket = Ticket.query.filter_by(spot_id=s.id, status='active').first()
        ticket_info = None
        if active_ticket and s.is_occupied:
            chk_in = active_ticket.check_in_time
            if chk_in.tzinfo is None:
                chk_in = chk_in.replace(tzinfo=timezone.utc)
            duration_sec = int((now - chk_in).total_seconds())
            ticket_info = {
                "ticket_id": active_ticket.id,
                "plate": active_ticket.vehicle.plate_number,
                "vehicle_type": active_ticket.vehicle.vehicle_type,
                "check_in_time": chk_in.isoformat(),
                "duration_seconds": max(0, duration_sec)
            }
            
        levels_map[lvl].append({
            "id": s.id,
            "spot_number": s.spot_number,
            "level": s.level,
            "type": s.type,
            "is_occupied": s.is_occupied,
            "vehicle": ticket_info
        })
        
    sorted_levels = []
    for lvl in sorted(levels_map.keys()):
        level_spots = levels_map[lvl]
        total = len(level_spots)
        occ = sum(1 for item in level_spots if item['is_occupied'])
        sorted_levels.append({
            "level": lvl,
            "total_spots": total,
            "occupied_spots": occ,
            "available_spots": total - occ,
            "spots": level_spots
        })
        
    return jsonify({"levels": sorted_levels}), 200


@app.route('/api/spots/add', methods=['POST'])
@login_required
def add_spot():
    data = request.json or {}
    spot_num = data.get('spot_number', '').strip().upper()
    level = data.get('level', 1, type=int)
    sType = data.get('type', 'standard').strip().lower()
    
    if not spot_num:
        return jsonify({"error": "Spot number is required"}), 400
    if sType not in ('compact', 'standard', 'ev'):
        return jsonify({"error": "Spot type must be compact, standard, or ev"}), 400
    if ParkingSpot.query.filter_by(spot_number=spot_num).first():
        return jsonify({"error": f"Spot number '{spot_num}' already exists"}), 409
        
    spot = ParkingSpot(spot_number=spot_num, level=level, type=sType, is_occupied=False)
    db.session.add(spot)
    db.session.commit()
    return jsonify({"message": f"Spot {spot_num} added to Level {level}", "spot_id": spot.id}), 201


@app.route('/api/spots/delete/<int:spot_id>', methods=['DELETE'])
@login_required
def delete_spot(spot_id):
    spot = db.session.get(ParkingSpot, spot_id)
    if not spot:
        return jsonify({"error": "Spot not found"}), 404
    if spot.is_occupied:
        return jsonify({"error": "Cannot delete occupied spot. Please check out vehicle first."}), 400
    db.session.delete(spot)
    db.session.commit()
    return jsonify({"message": f"Spot {spot.spot_number} deleted successfully"}), 200


@app.route('/api/spots/configure-layout', methods=['POST'])
@login_required
def configure_layout():
    data = request.json or {}
    levels_count = max(1, min(10, data.get('levels', 3)))
    spots_per_level = max(1, min(30, data.get('spots_per_level', 6)))
    ev_per_level = max(0, min(spots_per_level, data.get('ev_per_level', 2)))
    compact_per_level = max(0, min(spots_per_level - ev_per_level, data.get('compact_per_level', 2)))
    
    active_count = Ticket.query.filter_by(status='active').count()
    if active_count > 0:
        return jsonify({"error": f"Cannot reconfigure layout while {active_count} vehicle(s) are parked. Check out all vehicles first!"}), 400
        
    Ticket.query.delete()
    Vehicle.query.delete()
    ParkingSpot.query.delete()
    db.session.commit()
    
    new_spots = []
    for l in range(1, levels_count + 1):
        spot_idx = 1
        # EV
        for _ in range(ev_per_level):
            spot_num = f"E{l}{spot_idx:02d}"
            new_spots.append(ParkingSpot(spot_number=spot_num, level=l, type='ev'))
            spot_idx += 1
        # Compact
        for _ in range(compact_per_level):
            spot_num = f"C{l}{spot_idx:02d}"
            new_spots.append(ParkingSpot(spot_number=spot_num, level=l, type='compact'))
            spot_idx += 1
        # Standard
        remaining = spots_per_level - ev_per_level - compact_per_level
        for _ in range(remaining):
            spot_num = f"S{l}{spot_idx:02d}"
            new_spots.append(ParkingSpot(spot_number=spot_num, level=l, type='standard'))
            spot_idx += 1
            
    db.session.add_all(new_spots)
    db.session.commit()
    
    return jsonify({
        "message": f"Garage reconfigured! {len(new_spots)} spots created across {levels_count} levels.",
        "levels": levels_count,
        "spots_created": len(new_spots)
    }), 200


# ══════════════════════════════════════════════════════════════════
#  TICKET HISTORY API (Pagination + Sorting)
# ══════════════════════════════════════════════════════════════════
@app.route('/api/tickets', methods=['GET'])
@login_required
def get_tickets():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    sort_by = request.args.get('sort_by', 'check_in_time')
    order = request.args.get('order', 'desc')
    status_filter = request.args.get('status')

    query = Ticket.query

    if status_filter and status_filter in ('active', 'completed'):
        query = query.filter_by(status=status_filter)

    # Sorting
    sort_col = Ticket.fee if sort_by == 'fee' else Ticket.check_in_time
    query = query.order_by(sort_col.asc() if order == 'asc' else sort_col.desc())

    pagination = query.paginate(page=page, per_page=limit, error_out=False)

    return jsonify({
        "data": [{
            "id": t.id,
            "plate": t.vehicle.plate_number,
            "vehicle_type": t.vehicle.vehicle_type,
            "spot": t.spot.spot_number,
            "level": t.spot.level,
            "spot_type": t.spot.type,
            "check_in": t.check_in_time.isoformat(),
            "check_out": t.check_out_time.isoformat() if t.check_out_time else None,
            "fee": t.fee,
            "status": t.status
        } for t in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev
    }), 200


# ══════════════════════════════════════════════════════════════════
#  PHASE 3 TWISTS: RATES, CLOCK AUTOMATION, VALET TRANSFER
# ══════════════════════════════════════════════════════════════════

# ── Level 1 — T4: Messy Rate Card Import & Pricing ─────────────────
@app.route('/rates', methods=['GET', 'POST'])
@app.route('/api/rates', methods=['GET', 'POST'])
@app.route('/api/rates/import', methods=['POST'])
def handle_rates():
    if request.method == 'POST':
        raw_payload = request.json or request.form.to_dict() or {}
        cleaned = clean_rate_card(raw_payload)
        set_active_rate_cards(cleaned)
        return jsonify({
            "message": "Rate card imported and cleaned successfully",
            "rates": cleaned
        }), 200
    else:
        return jsonify({"rates": ACTIVE_RATE_CARDS}), 200


# ── Level 2 — T2: Nightly Auto-Close Graded via POST /clock ────────
@app.route('/clock', methods=['POST'])
@app.route('/api/clock', methods=['POST'])
def clock_tick():
    data = request.json or {}
    ts_val = data.get('timestamp') or data.get('current_time') or data.get('now') or data.get('time')
    advance_hours = data.get('advance_hours')
    
    if ts_val:
        try:
            sim_time_str = str(ts_val).replace('Z', '+00:00')
            sim_time = datetime.fromisoformat(sim_time_str)
            if sim_time.tzinfo is None:
                sim_time = sim_time.replace(tzinfo=timezone.utc)
        except Exception:
            sim_time = datetime.now(timezone.utc)
    elif advance_hours is not None:
        try:
            sim_time = datetime.now(timezone.utc) + timedelta(hours=float(advance_hours))
        except Exception:
            sim_time = datetime.now(timezone.utc)
    else:
        # Default: simulate 24h+ tick if no args provided
        sim_time = datetime.now(timezone.utc) + timedelta(hours=25)

    active_tickets = Ticket.query.filter_by(status='active').all()
    closed_sessions = []
    total_billed = 0.0

    for t in active_tickets:
        chk_in = t.check_in_time
        if chk_in.tzinfo is None:
            chk_in = chk_in.replace(tzinfo=timezone.utc)
        
        diff_sec = (sim_time - chk_in).total_seconds()
        # Auto-close sessions parked over 24 hours
        if diff_sec >= 24 * 3600:
            t.status = 'completed'
            t.check_out_time = sim_time
            spot = db.session.get(ParkingSpot, t.spot_id)
            spot_type = spot.type if spot else 'standard'
            fee = calculate_fee(chk_in, sim_time, spot_type)
            t.fee = fee
            if spot:
                spot.is_occupied = False
            total_billed += fee
            closed_sessions.append({
                "ticket_id": t.id,
                "plate": t.vehicle.plate_number,
                "spot": spot.spot_number if spot else "UNKNOWN",
                "check_in_time": chk_in.isoformat(),
                "check_out_time": sim_time.isoformat(),
                "duration_hours": round(diff_sec / 3600.0, 2),
                "fee": fee
            })

    db.session.commit()

    return jsonify({
        "message": f"Nightly clock processed at {sim_time.isoformat()}. {len(closed_sessions)} session(s) parked over 24h auto-closed and billed.",
        "simulated_time": sim_time.isoformat(),
        "auto_closed_count": len(closed_sessions),
        "total_billed": round(total_billed, 2),
        "closed_sessions": closed_sessions
    }), 200


# ── Level 3 — T6: Valet Hand-off / Transfer Open Session ───────────
@app.route('/tickets/transfer', methods=['POST'])
@app.route('/api/tickets/transfer', methods=['POST'])
@app.route('/api/parking/transfer', methods=['POST'])
def transfer_ticket():
    data = request.json or {}
    old_plate = (data.get('old_plate') or data.get('from_plate') or '').strip().upper()
    new_plate = (data.get('new_plate') or data.get('to_plate') or '').strip().upper()
    ticket_id = data.get('ticket_id')
    new_v_type = (data.get('new_vehicle_type') or data.get('vehicle_type') or '').strip().lower()

    # Find the active ticket
    ticket = None
    if ticket_id:
        ticket = db.session.get(Ticket, ticket_id)
        if ticket and ticket.status != 'active':
            ticket = None
    elif old_plate:
        old_vehicle = Vehicle.query.filter_by(plate_number=old_plate).first()
        if old_vehicle:
            ticket = Ticket.query.filter_by(vehicle_id=old_vehicle.id, status='active').first()

    if not ticket:
        return jsonify({"error": "No active parking session found for transfer"}), 404

    if not new_plate:
        return jsonify({"error": "New license plate is required for valet transfer"}), 400

    # Ensure new_plate is not already checked in
    new_vehicle = Vehicle.query.filter_by(plate_number=new_plate).first()
    if new_vehicle:
        active_new = Ticket.query.filter_by(vehicle_id=new_vehicle.id, status='active').first()
        if active_new and active_new.id != ticket.id:
            return jsonify({"error": f"Target vehicle {new_plate} is already checked into Spot {active_new.spot.spot_number}"}), 400
    else:
        v_type = new_v_type if new_v_type in ('regular', 'ev') else ticket.vehicle.vehicle_type
        new_vehicle = Vehicle(plate_number=new_plate, vehicle_type=v_type)
        db.session.add(new_vehicle)
        db.session.flush()

    orig_plate = ticket.vehicle.plate_number
    # Valet handoff: transfer vehicle ownership while preserving spot_id and check_in_time
    ticket.vehicle_id = new_vehicle.id
    db.session.commit()

    return jsonify({
        "message": f"Session successfully transferred from {orig_plate} to {new_plate} (Valet Hand-off)",
        "ticket_id": ticket.id,
        "old_plate": orig_plate,
        "new_plate": new_vehicle.plate_number,
        "spot": ticket.spot.spot_number,
        "level": ticket.spot.level,
        "spot_type": ticket.spot.type,
        "check_in_time": ticket.check_in_time.isoformat(),
        "status": "active"
    }), 200


# ══════════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ══════════════════════════════════════════════════════════════════
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "Garage API v2 is running ✅"}), 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)
