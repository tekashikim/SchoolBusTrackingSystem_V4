from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash  # type: ignore[reportMissingImports]
import sqlite3, os, re, uuid
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash  # type: ignore[reportMissingImports]
try:
    from werkzeug.utils import secure_filename  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - compatibility fallback
    from werkzeug import secure_filename  # type: ignore[reportMissingImports]

app = Flask(__name__)
app.secret_key = os.environ.get('SCHOOL_BUS_SECRET_KEY', 'change-this-demo-secret-key-before-deployment')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, 'database.db')
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
os.makedirs(UPLOAD_DIR, exist_ok=True)

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, fullname TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, photo_filename TEXT, account_status TEXT NOT NULL DEFAULT 'Active')""")
    # Safe schema migration for databases created by earlier versions.
    user_columns = {row['name'] for row in c.execute('PRAGMA table_info(users)').fetchall()}
    if 'photo_filename' not in user_columns:
        c.execute('ALTER TABLE users ADD COLUMN photo_filename TEXT')
    if 'account_status' not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN account_status TEXT NOT NULL DEFAULT 'Active'")
    c.execute("""CREATE TABLE IF NOT EXISTS buses(id INTEGER PRIMARY KEY AUTOINCREMENT, bus_number TEXT UNIQUE NOT NULL, driver_id INTEGER, route TEXT NOT NULL, status TEXT DEFAULT 'Available', latitude REAL DEFAULT -1.286389, longitude REAL DEFAULT 36.817223, photo_filename TEXT)""")
    bus_columns = {row['name'] for row in c.execute('PRAGMA table_info(buses)').fetchall()}
    if 'photo_filename' not in bus_columns:
        c.execute('ALTER TABLE buses ADD COLUMN photo_filename TEXT')
    c.execute("""CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY AUTOINCREMENT, admission_no TEXT UNIQUE NOT NULL, fullname TEXT NOT NULL, route TEXT NOT NULL, parent_id INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, bus_id INTEGER, status TEXT, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER NOT NULL, student_id INTEGER, message TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_read INTEGER NOT NULL DEFAULT 0)""")
    # Demo accounts are inserted only when missing. Existing plaintext demo passwords are upgraded on successful login.
    demos = [('School Admin','admin@school.com','admin123','Admin'),('John Driver','driver@school.com','driver123','Driver'),('Mary Parent','parent@school.com','parent123','Parent')]
    for name,email,password,role in demos:
        c.execute('INSERT OR IGNORE INTO users(fullname,email,password,role) VALUES(?,?,?,?)',(name,email,generate_password_hash(password),role))
    driver = c.execute("SELECT id FROM users WHERE email='driver@school.com'").fetchone()
    parent = c.execute("SELECT id FROM users WHERE email='parent@school.com'").fetchone()
    if driver:
        c.execute('INSERT OR IGNORE INTO buses(bus_number,driver_id,route,status) VALUES(?,?,?,?)',('SCHOOL-01',driver['id'],'School Route','On Route'))
    if parent:
        c.execute('INSERT OR IGNORE INTO students(admission_no,fullname,route,parent_id) VALUES(?,?,?,?)',('STU001','Alex Kamau','School Route',parent['id']))
    c.commit(); c.close()

def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if not session.get('user_id'): return redirect(url_for('login'))
        return f(*a,**k)
    return w

def role_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a,**k):
            if not session.get('user_id'): return redirect(url_for('login'))
            if session.get('role') not in roles: return render_template('error.html', message='You do not have permission to access this page.'),403
            if session.get('role') != 'Admin':
                c = db(); account = c.execute('SELECT account_status FROM users WHERE id=?', (session['user_id'],)).fetchone(); c.close()
                if not account or account['account_status'] != 'Active':
                    session.clear()
                    flash('Your account is inactive. Please contact the school administrator.', 'error')
                    return redirect(url_for('login'))
            return f(*a,**k)
        return w
    return deco

@app.route('/')
def home(): return render_template('home.html')

@app.route('/login', methods=['GET','POST'])
def login():
    error=None
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        c=db(); u=c.execute('SELECT * FROM users WHERE lower(email)=?',(email,)).fetchone()
        valid=False
        if u:
            stored=u['password']
            try: valid=check_password_hash(stored,password)
            except (ValueError, TypeError): valid=False
            # One-time migration for databases created by the earlier version.
            if not valid and stored == password:
                valid=True
                c.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(password),u['id']))
                c.commit()
        c.close()
        if valid and u['role'] != 'Admin' and u['account_status'] == 'Inactive':
            error='Your account is inactive. Please contact the school administrator.'
        elif valid:
            session.clear(); session.update(user_id=u['id'],fullname=u['fullname'],role=u['role'])
            return redirect(url_for('role_home'))
        else:
            error='The email address or password is incorrect.'
    return render_template('login.html',error=error)

@app.route('/signup', methods=['GET','POST'])
def signup():
    error=None
    if request.method=='POST':
        fullname=' '.join(request.form.get('fullname','').split())
        email=request.form.get('email','').strip().lower()
        password=request.form.get('password',''); confirm=request.form.get('confirm_password','')
        role=request.form.get('role','Parent').strip().title()
        allowed_roles={'Parent','Driver','Teacher'}
        if role not in allowed_roles: error='Choose Parent, Driver, or Teacher.'
        elif len(fullname)<2: error='Enter your full name.'
        elif not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): error='Enter a valid email address.'
        elif len(password)<8: error='Use a password with at least 8 characters.'
        elif password != confirm: error='The passwords do not match.'
        else:
            c=db()
            try:
                c.execute('INSERT INTO users(fullname,email,password,role) VALUES(?,?,?,?)',(fullname,email,generate_password_hash(password),role))
                c.commit()
                u=c.execute('SELECT id,fullname,role FROM users WHERE email=?',(email,)).fetchone()
                session.clear(); session.update(user_id=u['id'],fullname=u['fullname'],role=u['role'])
                c.close(); return redirect(url_for('role_home'))
            except sqlite3.IntegrityError:
                error='An account with that email already exists.'
            finally:
                try: c.close()
                except Exception: pass
    return render_template('signup.html',error=error)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session['user_id']
    error = None
    c = db()
    user = c.execute('SELECT id, fullname, email, role, password, photo_filename FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        c.close(); session.clear(); return redirect(url_for('login'))

    if request.method == 'POST':
        fullname = ' '.join(request.form.get('fullname', '').split())
        email = request.form.get('email', '').strip().lower()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        uploaded = request.files.get('photo')
        new_photo_name = None

        if len(fullname) < 2:
            error = 'Enter your full name.'
        elif not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            error = 'Enter a valid email address.'
        elif c.execute('SELECT 1 FROM users WHERE lower(email)=? AND id<>?', (email, user_id)).fetchone():
            error = 'That email address is already in use.'
        elif new_password and len(new_password) < 8:
            error = 'Your new password must have at least 8 characters.'
        elif new_password and new_password != confirm_password:
            error = 'The new passwords do not match.'
        elif new_password and not check_password_hash(user['password'], current_password):
            error = 'Enter your current password to change it.'

        if not error and uploaded and uploaded.filename:
            filename = secure_filename(uploaded.filename)
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                error = 'Use a JPG, JPEG, PNG, or WEBP profile photo.'
            else:
                uploaded.stream.seek(0, os.SEEK_END); size = uploaded.stream.tell(); uploaded.stream.seek(0)
                header = uploaded.stream.read(12); uploaded.stream.seek(0)
                valid_image = ((ext in ('jpg', 'jpeg') and header.startswith(b'\xff\xd8\xff')) or
                               (ext == 'png' and header.startswith(b'\x89PNG\r\n\x1a\n')) or
                               (ext == 'webp' and len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == b'WEBP'))
                if size > MAX_UPLOAD_BYTES:
                    error = 'The profile photo must be 5 MB or smaller.'
                elif not valid_image:
                    error = 'The selected file is not a valid image.'
                else:
                    new_photo_name = f"user_{user_id}_{uuid.uuid4().hex}.{ext}"
                    uploaded.save(os.path.join(UPLOAD_DIR, new_photo_name))

        if not error:
            old_photo = user['photo_filename']
            if new_password:
                c.execute('UPDATE users SET fullname=?, email=?, password=?, photo_filename=COALESCE(?, photo_filename) WHERE id=?',
                          (fullname, email, generate_password_hash(new_password), new_photo_name, user_id))
            else:
                c.execute('UPDATE users SET fullname=?, email=?, photo_filename=COALESCE(?, photo_filename) WHERE id=?',
                          (fullname, email, new_photo_name, user_id))
            c.commit()
            session['fullname'] = fullname
            if new_photo_name and old_photo:
                old_path = os.path.join(UPLOAD_DIR, os.path.basename(old_photo))
                if os.path.isfile(old_path):
                    try: os.remove(old_path)
                    except OSError: pass
            c.close()
            flash('Your profile has been updated.', 'success')
            return redirect(url_for('profile'))

    c.close()
    return render_template('profile.html', user=user, error=error)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/my-workspace')
@login_required
def role_home():
    role=session.get('role')
    if role == 'Driver': return redirect(url_for('driver'))
    if role == 'Teacher': return redirect(url_for('teacher_workspace'))
    if role == 'Parent': return redirect(url_for('parent_workspace'))
    return redirect(url_for('dashboard'))

@app.route('/parent')
@role_required('Parent')
def parent_workspace():
    c=db()
    children=c.execute('SELECT * FROM students WHERE parent_id=? ORDER BY fullname',(session['user_id'],)).fetchall()
    attendance_rows=c.execute('SELECT a.*,s.fullname,b.bus_number FROM attendance a JOIN students s ON s.id=a.student_id LEFT JOIN buses b ON b.id=a.bus_id WHERE s.parent_id=? ORDER BY a.recorded_at DESC LIMIT 10',(session['user_id'],)).fetchall()
    unread=c.execute('SELECT COUNT(*) FROM notifications WHERE parent_id=? AND is_read=0',(session['user_id'],)).fetchone()[0]
    c.close()
    return render_template('parent.html',children=children,attendance_rows=attendance_rows,unread=unread)

@app.route('/teacher')
@role_required('Teacher')
def teacher_workspace():
    c=db()
    students=c.execute('SELECT * FROM students ORDER BY fullname').fetchall()
    records=c.execute('SELECT a.*,s.fullname student_name,b.bus_number FROM attendance a JOIN students s ON a.student_id=s.id JOIN buses b ON a.bus_id=b.id ORDER BY a.id DESC LIMIT 20').fetchall()
    c.close()
    return render_template('teacher.html', students=students, records=records)

@app.route('/dashboard')
@role_required('Admin')
def dashboard():
    c=db(); stats=[c.execute('SELECT COUNT(*) FROM buses').fetchone()[0],c.execute('SELECT COUNT(*) FROM students').fetchone()[0],c.execute("SELECT COUNT(*) FROM users WHERE role='Driver'").fetchone()[0],c.execute("SELECT COUNT(*) FROM buses WHERE status='On Route'").fetchone()[0]]
    featured_bus=c.execute('SELECT b.*,u.fullname driver FROM buses b LEFT JOIN users u ON b.driver_id=u.id ORDER BY b.id LIMIT 1').fetchone()
    recent_buses=c.execute('SELECT b.*,u.fullname driver,u.photo_filename driver_photo FROM buses b LEFT JOIN users u ON b.driver_id=u.id ORDER BY b.id DESC LIMIT 4').fetchall(); c.close()
    return render_template('dashboard.html',stats=stats,featured_bus=featured_bus,recent_buses=recent_buses)

@app.route('/map')
@role_required('Admin','Parent','Teacher')
def map_page():
    c=db()
    if session['role']=='Parent':
        buses=c.execute('SELECT DISTINCT b.*,u.fullname driver FROM buses b LEFT JOIN users u ON b.driver_id=u.id JOIN students s ON s.route=b.route WHERE s.parent_id=?',(session['user_id'],)).fetchall()
    else: buses=c.execute('SELECT b.*,u.fullname driver FROM buses b LEFT JOIN users u ON b.driver_id=u.id').fetchall()
    c.close(); return render_template('map.html',buses=buses)

@app.route('/api/buses')
@role_required('Admin','Parent','Teacher')
def api_buses():
    c=db()
    if session['role']=='Parent': rows=c.execute('SELECT DISTINCT b.*,u.fullname driver FROM buses b LEFT JOIN users u ON b.driver_id=u.id JOIN students s ON s.route=b.route WHERE s.parent_id=?',(session['user_id'],)).fetchall()
    else: rows=c.execute('SELECT b.*,u.fullname driver FROM buses b LEFT JOIN users u ON b.driver_id=u.id').fetchall()
    c.close(); return jsonify([dict(x) for x in rows])

@app.route('/drivers')
@role_required('Admin','Parent','Teacher')
def drivers_directory():
    c=db()
    if session['role']=='Parent': rows=c.execute("SELECT DISTINCT u.id,u.fullname,u.email,u.photo_filename,u.account_status,b.bus_number,b.route,b.status AS bus_status FROM users u JOIN buses b ON b.driver_id=u.id JOIN students s ON s.route=b.route WHERE u.role='Driver' AND s.parent_id=? ORDER BY u.fullname",(session['user_id'],)).fetchall()
    else: rows=c.execute("SELECT u.id,u.fullname,u.email,u.photo_filename,u.account_status,b.bus_number,b.route,b.status AS bus_status FROM users u LEFT JOIN buses b ON b.driver_id=u.id WHERE u.role='Driver' ORDER BY u.fullname").fetchall()
    c.close(); return render_template('drivers.html', drivers=rows)

@app.route('/add_driver', methods=['POST'])
@role_required('Admin')
def add_driver():
    fullname = ' '.join(request.form.get('fullname', '').split())
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')
    if len(fullname) < 2:
        flash("Enter the driver's full name.", 'error')
    elif not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        flash('Enter a valid email address.', 'error')
    elif len(password) < 8:
        flash('The temporary password must have at least 8 characters.', 'error')
    elif password != confirm:
        flash('The passwords do not match.', 'error')
    else:
        c = db()
        try:
            c.execute('INSERT INTO users(fullname,email,password,role) VALUES(?,?,?,?)',
                      (fullname, email, generate_password_hash(password), 'Driver'))
            c.commit()
            flash(f'Driver account created for {fullname}. You can now assign the driver to a bus.', 'success')
        except sqlite3.IntegrityError:
            flash('An account with that email already exists.', 'error')
        finally:
            c.close()
    return redirect(url_for('drivers_directory'))

@app.route('/driver/account-status/<int:driver_id>', methods=['POST'])
@role_required('Admin')
def update_driver_account_status(driver_id):
    new_status = request.form.get('account_status', '')
    if new_status not in ('Active', 'Inactive'):
        flash('Choose Active or Inactive.', 'error')
        return redirect(url_for('drivers_directory'))
    c = db()
    driver_row = c.execute("SELECT id FROM users WHERE id=? AND role='Driver'", (driver_id,)).fetchone()
    if not driver_row:
        c.close(); flash('Driver account not found.', 'error')
        return redirect(url_for('drivers_directory'))
    c.execute('UPDATE users SET account_status=? WHERE id=?', (new_status, driver_id))
    c.commit(); c.close()
    flash(f'Driver account status changed to {new_status}.', 'success')
    return redirect(url_for('drivers_directory'))

@app.route('/teachers')
@role_required('Admin')
def teacher_management():
    c = db()
    teachers = c.execute("SELECT id,fullname,email,account_status FROM users WHERE role='Teacher' ORDER BY fullname").fetchall()
    c.close()
    return render_template('teachers.html', teachers=teachers)

@app.route('/teachers/add', methods=['POST'])
@role_required('Admin')
def add_teacher():
    fullname = ' '.join(request.form.get('fullname', '').split())
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    if len(fullname) < 2 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(password) < 8:
        flash('Enter a valid name and email, and a password of at least 8 characters.', 'error')
    else:
        c = db()
        try:
            c.execute("INSERT INTO users(fullname,email,password,role) VALUES(?,?,?,'Teacher')", (fullname,email,generate_password_hash(password)))
            c.commit(); flash('Teacher account created.', 'success')
        except sqlite3.IntegrityError:
            flash('An account with that email already exists.', 'error')
        finally: c.close()
    return redirect(url_for('teacher_management'))

@app.route('/teachers/<int:teacher_id>/status', methods=['POST'])
@role_required('Admin')
def update_teacher_status(teacher_id):
    status = request.form.get('account_status', '')
    if status not in ('Active','Inactive'):
        flash('Choose Active or Inactive.', 'error')
    else:
        c=db(); cur=c.execute("UPDATE users SET account_status=? WHERE id=? AND role='Teacher'", (status,teacher_id)); c.commit(); c.close()
        flash('Teacher status updated.' if cur.rowcount else 'Teacher not found.', 'success' if cur.rowcount else 'error')
    return redirect(url_for('teacher_management'))

@app.route('/notifications')
@role_required('Parent')
def parent_notifications():
    c=db(); rows=c.execute('SELECT * FROM notifications WHERE parent_id=? ORDER BY id DESC LIMIT 100', (session['user_id'],)).fetchall(); c.execute('UPDATE notifications SET is_read=1 WHERE parent_id=?', (session['user_id'],)); c.commit(); c.close()
    return render_template('notifications.html', notifications=rows)

@app.route('/driver/photo/<int:driver_id>', methods=['POST'])
@role_required('Admin')
def upload_driver_photo(driver_id):
    uploaded = request.files.get('photo')
    if not uploaded or not uploaded.filename:
        flash('Choose a driver photo first.', 'error'); return redirect(url_for('buses'))
    filename = secure_filename(uploaded.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        flash('Use a JPG, JPEG, PNG, or WEBP image.', 'error'); return redirect(url_for('buses'))
    uploaded.stream.seek(0, os.SEEK_END); size = uploaded.stream.tell(); uploaded.stream.seek(0)
    if size > MAX_UPLOAD_BYTES:
        flash('The photo must be 5 MB or smaller.', 'error'); return redirect(url_for('buses'))
    header = uploaded.stream.read(12); uploaded.stream.seek(0)
    valid_image = ((ext in ('jpg', 'jpeg') and header.startswith(b'\xff\xd8\xff')) or
                   (ext == 'png' and header.startswith(b'\x89PNG\r\n\x1a\n')) or
                   (ext == 'webp' and len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == b'WEBP'))
    if not valid_image:
        flash('The selected file does not appear to be a valid image of that type.', 'error'); return redirect(url_for('buses'))
    c=db(); driver_row=c.execute("SELECT id,photo_filename FROM users WHERE id=? AND role='Driver'", (driver_id,)).fetchone()
    if not driver_row:
        c.close(); return 'Driver not found.',404
    new_name = f"driver_{driver_id}_{uuid.uuid4().hex}.{ext}"
    uploaded.save(os.path.join(UPLOAD_DIR, new_name))
    old_name = driver_row['photo_filename']
    c.execute('UPDATE users SET photo_filename=? WHERE id=?', (new_name, driver_id)); c.commit(); c.close()
    if old_name:
        old_path=os.path.join(UPLOAD_DIR, os.path.basename(old_name))
        if os.path.isfile(old_path):
            try: os.remove(old_path)
            except OSError: pass
    flash('Driver photo updated.', 'success'); return redirect(url_for('buses'))

@app.route('/driver')
@role_required('Driver')
def driver():
    c=db(); bus=c.execute('SELECT * FROM buses WHERE driver_id=?',(session['user_id'],)).fetchone(); c.close(); return render_template('driver.html',bus=bus)

@app.route('/driver/location',methods=['POST'])
@role_required('Driver')
def location():
    data=request.get_json(silent=True) or {}
    try:
        lat=float(data['latitude']); lon=float(data['longitude'])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError()
    except (KeyError,TypeError,ValueError): return jsonify(success=False,message='Invalid location coordinates.'),400
    c=db(); c.execute("UPDATE buses SET latitude=?,longitude=?,status='On Route' WHERE driver_id=?",(lat,lon,session['user_id'])); c.commit(); c.close(); return jsonify(success=True,message='Bus location updated.')

@app.route('/driver/status',methods=['POST'])
@role_required('Driver')
def status():
    new_status=request.form.get('status','')
    if new_status not in ('Available','On Route','Arrived at School','Completed','Delayed'): return 'Invalid bus status.',400
    c=db(); buses=c.execute('SELECT id,route,status FROM buses WHERE driver_id=?',(session['user_id'],)).fetchall()
    c.execute('UPDATE buses SET status=? WHERE driver_id=?',(new_status,session['user_id']))
    if new_status == 'Arrived at School' and any(bus['status'] != 'Arrived at School' for bus in buses):
        for bus in buses:
            linked=c.execute('SELECT id,fullname,parent_id FROM students WHERE parent_id IS NOT NULL AND route=?',(bus['route'],)).fetchall()
            for student in linked:
                c.execute('INSERT INTO notifications(parent_id,student_id,message) VALUES(?,?,?)',(student['parent_id'],student['id'],f"The school bus for {student['fullname']} has arrived at school."))
    c.commit(); c.close(); flash('Bus status updated. Parents linked to students on this route are notified when the bus arrives.', 'success'); return redirect(url_for('driver'))

@app.route('/buses')
@role_required('Admin')
def buses():
    c=db(); rows=c.execute('SELECT b.*,u.fullname driver,u.photo_filename driver_photo FROM buses b LEFT JOIN users u ON b.driver_id=u.id').fetchall(); drivers=c.execute("SELECT id,fullname,photo_filename,account_status FROM users WHERE role='Driver' ORDER BY fullname").fetchall(); c.close(); return render_template('buses.html',buses=rows,drivers=drivers)

@app.route('/bus/photo/<int:bus_id>', methods=['POST'])
@role_required('Admin')
def upload_bus_photo(bus_id):
    uploaded = request.files.get('photo')
    if not uploaded or not uploaded.filename:
        flash('Choose a bus photo first.', 'error'); return redirect(url_for('buses'))
    filename = secure_filename(uploaded.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        flash('Use a JPG, JPEG, PNG, or WEBP image.', 'error'); return redirect(url_for('buses'))
    uploaded.stream.seek(0, os.SEEK_END); size = uploaded.stream.tell(); uploaded.stream.seek(0)
    header = uploaded.stream.read(12); uploaded.stream.seek(0)
    valid_image = ((ext in ('jpg', 'jpeg') and header.startswith(b'\xff\xd8\xff')) or
                   (ext == 'png' and header.startswith(b'\x89PNG\r\n\x1a\n')) or
                   (ext == 'webp' and len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == b'WEBP'))
    if size > MAX_UPLOAD_BYTES or not valid_image:
        flash('Choose a valid JPG, JPEG, PNG, or WEBP image under 5 MB.', 'error'); return redirect(url_for('buses'))
    c=db(); bus=c.execute('SELECT id,photo_filename FROM buses WHERE id=?', (bus_id,)).fetchone()
    if not bus:
        c.close(); return 'Bus not found.',404
    new_name = f'bus_{bus_id}_{uuid.uuid4().hex}.{ext}'
    uploaded.save(os.path.join(UPLOAD_DIR, new_name))
    old_name=bus['photo_filename']; c.execute('UPDATE buses SET photo_filename=? WHERE id=?',(new_name,bus_id)); c.commit(); c.close()
    if old_name:
        old_path=os.path.join(UPLOAD_DIR, os.path.basename(old_name))
        if os.path.isfile(old_path):
            try: os.remove(old_path)
            except OSError: pass
    flash('Bus photo updated successfully.', 'success'); return redirect(url_for('buses'))

@app.route('/add_bus',methods=['POST'])
@role_required('Admin')
def add_bus():
    bus_number=request.form.get('bus_number','').strip().upper(); route=request.form.get('route','').strip()
    if not bus_number or not route: return 'Bus number and route are required.',400
    c=db(); driver_raw=request.form.get('driver_id','').strip(); driver_id=None
    if driver_raw:
        try: driver_id=int(driver_raw)
        except ValueError: c.close(); return 'Choose a valid driver.',400
        driver=c.execute("SELECT id,account_status FROM users WHERE id=? AND role='Driver'",(driver_id,)).fetchone()
        if not driver or driver['account_status']!='Active': c.close(); flash('Choose an active driver.', 'error'); return redirect(url_for('buses'))
        assigned=c.execute('SELECT bus_number FROM buses WHERE driver_id=?',(driver_id,)).fetchone()
        if assigned: c.close(); flash(f'This driver is already assigned to {assigned["bus_number"]}. Choose another driver or edit that bus first.', 'error'); return redirect(url_for('buses'))
    try: c.execute('INSERT INTO buses(bus_number,driver_id,route) VALUES(?,?,?)',(bus_number,driver_id,route)); c.commit()
    except sqlite3.IntegrityError: flash('That bus number already exists.', 'error')
    finally: c.close()
    return redirect(url_for('buses'))

@app.route('/bus/<int:bus_id>/update', methods=['POST'])
@role_required('Admin')
def update_bus(bus_id):
    bus_number = request.form.get('bus_number', '').strip().upper()
    route = request.form.get('route', '').strip()
    driver_raw = request.form.get('driver_id', '').strip()
    if not bus_number or not route:
        flash('Bus registration and route are required.', 'error')
        return redirect(url_for('buses'))
    driver_id = None
    if driver_raw:
        try: driver_id = int(driver_raw)
        except ValueError:
            flash('Choose a valid driver.', 'error'); return redirect(url_for('buses'))
        c = db(); driver = c.execute("SELECT id,account_status FROM users WHERE id=? AND role='Driver'", (driver_id,)).fetchone()
        if not driver or driver['account_status'] != 'Active':
            c.close(); flash('You can assign only an active driver.', 'error'); return redirect(url_for('buses'))
        already_assigned = c.execute('SELECT id,bus_number FROM buses WHERE driver_id=? AND id<>?', (driver_id, bus_id)).fetchone()
        if already_assigned:
            c.close(); flash(f'This driver is already assigned to bus {already_assigned["bus_number"]}. Remove that assignment first.', 'error'); return redirect(url_for('buses'))
    else:
        c = db()
    try:
        cur = c.execute('UPDATE buses SET bus_number=?,route=?,driver_id=? WHERE id=?', (bus_number, route, driver_id, bus_id))
        if cur.rowcount == 0:
            c.close(); flash('Bus not found.', 'error'); return redirect(url_for('buses'))
        c.commit(); flash('Bus details and driver assignment updated.', 'success')
    except sqlite3.IntegrityError:
        flash('That bus registration is already in use.', 'error')
    finally:
        c.close()
    return redirect(url_for('buses'))

@app.route('/students')
@role_required('Admin','Parent','Teacher')
def students():
    c=db()
    rows=c.execute('SELECT * FROM students WHERE parent_id=?',(session['user_id'],)).fetchall() if session['role']=='Parent' else c.execute('SELECT s.*,u.fullname parent_name FROM students s LEFT JOIN users u ON u.id=s.parent_id ORDER BY s.fullname').fetchall()
    parents=c.execute("SELECT id,fullname,email FROM users WHERE role='Parent' AND account_status='Active' ORDER BY fullname").fetchall() if session['role']=='Admin' else []
    c.close(); return render_template('students.html',students=rows,parents=parents)

@app.route('/add_student',methods=['POST'])
@role_required('Admin')
def add_student():
    admission=request.form.get('admission_no','').strip(); fullname=request.form.get('fullname','').strip(); route=request.form.get('route','').strip()
    parent_raw=request.form.get('parent_id','').strip()
    parent_id=None
    if parent_raw:
        try: parent_id=int(parent_raw)
        except ValueError: return 'Choose a valid parent account.',400
    if not all((admission,fullname,route)): return 'All student fields are required.',400
    c=db()
    if parent_id and not c.execute("SELECT 1 FROM users WHERE id=? AND role='Parent' AND account_status='Active'",(parent_id,)).fetchone():
        c.close(); return 'Choose an active parent account.',400
    try: c.execute('INSERT INTO students(admission_no,fullname,route,parent_id) VALUES(?,?,?,?)',(admission,fullname,route,parent_id)); c.commit()
    except sqlite3.IntegrityError: return 'That admission number already exists.',400
    finally: c.close()
    flash('Student record saved and parent linked if selected.', 'success'); return redirect(url_for('students'))

@app.route('/attendance')
@role_required('Admin','Driver','Teacher','Parent')
def attendance():
    c=db()
    month=request.args.get('month','')
    where=[]; params=[]
    if session['role']=='Parent':
        where.append('s.parent_id=?'); params.append(session['user_id'])
    elif session['role']=='Driver':
        where.append('b.driver_id=?'); params.append(session['user_id'])
    if month and re.fullmatch(r'\d{4}-\d{2}', month):
        where.append("substr(a.recorded_at,1,7)=?"); params.append(month)
    clause=(' WHERE '+' AND '.join(where)) if where else ''
    records=c.execute('SELECT a.*,s.fullname,b.bus_number,s.parent_id FROM attendance a JOIN students s ON a.student_id=s.id LEFT JOIN buses b ON a.bus_id=b.id'+clause+' ORDER BY a.recorded_at DESC',params).fetchall()
    if session['role']=='Parent':
        ss=c.execute('SELECT * FROM students WHERE parent_id=? ORDER BY fullname',(session['user_id'],)).fetchall()
    elif session['role']=='Driver':
        ss=c.execute('SELECT s.* FROM students s JOIN buses b ON b.route=s.route WHERE b.driver_id=? ORDER BY s.fullname',(session['user_id'],)).fetchall()
    else:
        ss=c.execute('SELECT * FROM students ORDER BY fullname').fetchall()
    bs=c.execute('SELECT * FROM buses WHERE driver_id=? ORDER BY bus_number',(session['user_id'],)).fetchall() if session['role']=='Driver' else (c.execute('SELECT * FROM buses ORDER BY bus_number').fetchall() if session['role']=='Admin' else [])
    c.close(); return render_template('attendance.html',records=records,students=ss,buses=bs,month=month)

@app.route('/attendance/add',methods=['POST'])
@role_required('Admin','Driver','Teacher')
def add_attendance():
    if request.form.get('status') not in ('Boarded','Absent','Dropped off'): return 'Invalid attendance status.',400
    try: student_id=int(request.form['student_id']); bus_id=int(request.form['bus_id'])
    except (KeyError,ValueError): return 'Choose a valid student and bus.',400
    c=db()
    student=c.execute('SELECT id,route FROM students WHERE id=?',(student_id,)).fetchone()
    bus=c.execute('SELECT id,route,driver_id FROM buses WHERE id=?',(bus_id,)).fetchone()
    if not student or not bus:
        c.close(); return 'Student or bus not found.',404
    if session['role']=='Driver' and (bus['driver_id'] != session['user_id'] or student['route'] != bus['route']):
        c.close(); return 'You can record attendance only for students on your assigned route.',403
    c.execute('INSERT INTO attendance(student_id,bus_id,status) VALUES(?,?,?)',(student_id,bus_id,request.form['status'])); c.commit(); c.close(); flash('Attendance recorded.', 'success'); return redirect(url_for('attendance'))

@app.route('/reports')
@role_required('Admin')
def reports():
    c=db(); stats=[c.execute('SELECT COUNT(*) FROM buses').fetchone()[0],c.execute("SELECT COUNT(*) FROM users WHERE role='Driver' AND account_status='Active'").fetchone()[0],c.execute('SELECT COUNT(*) FROM students').fetchone()[0],c.execute('SELECT COUNT(*) FROM attendance').fetchone()[0]]; c.close(); return render_template('reports.html',stats=stats)

@app.route('/error')
def error_page(): return render_template('error.html',message='The requested page could not be found.'),404

@app.errorhandler(404)
def not_found(_): return render_template('error.html',message='The page you requested could not be found.'),404

if __name__=='__main__':
    init_db()
    app.run(debug=False)
