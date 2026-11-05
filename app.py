from functools import wraps
from datetime import datetime, timedelta
import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from csp_solver import build_problem, solve_and_compare

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "timetable.db")
app = Flask(__name__)
app.secret_key = os.environ.get("TIMETABLE_SECRET_KEY", "change-this-secret-key-before-deployment")

DEFAULT_SETTINGS = {
    "institution": "DIT University (Demo)",
    "total_students": "1200",
    "course_type": "Tech",
    "semester_type": "Odd",
    "specialisation": "DIML",
    "academic_year": "3rd Year",
    "working_days": "5",
    "periods_per_day": "7",
    "period_minutes": "50",
    "day_start": "09:00",
    "break_after_period": "3",
    "break_minutes": "40",
    "break_label": "Lunch Break",
    "section_size": "60",
}

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS faculty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            max_periods INTEGER NOT NULL DEFAULT 20,
            available_days TEXT NOT NULL DEFAULT '1,2,3,4,5'
        );
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            room_type TEXT NOT NULL DEFAULT 'Classroom',
            capacity INTEGER NOT NULL DEFAULT 60,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Core',
            lectures_per_week INTEGER NOT NULL DEFAULT 3,
            practicals_per_week INTEGER NOT NULL DEFAULT 0,
            practical_duration INTEGER NOT NULL DEFAULT 2,
            requires_lab INTEGER NOT NULL DEFAULT 0,
            faculty_id INTEGER,
            FOREIGN KEY(faculty_id) REFERENCES faculty(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            section TEXT NOT NULL,
            students INTEGER NOT NULL DEFAULT 60,
            year_label TEXT NOT NULL DEFAULT '3rd Year',
            specialisation TEXT NOT NULL DEFAULT 'DIML'
        );
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            faculty_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            period_index INTEGER NOT NULL,
            duration INTEGER NOT NULL DEFAULT 1,
            session_type TEXT NOT NULL DEFAULT 'Lecture',
            FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
            FOREIGN KEY(faculty_id) REFERENCES faculty(id),
            FOREIGN KEY(room_id) REFERENCES rooms(id)
        );
        """)
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        if not con.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            con.execute("INSERT INTO users(username,password_hash) VALUES(?,?)",
                        ("admin", generate_password_hash("Admin@123")))
        # Add a tiny, clearly labelled demo seed only when there is no academic data.
        if not con.execute("SELECT id FROM faculty LIMIT 1").fetchone():
            con.executemany("INSERT INTO faculty(code,name,max_periods,available_days) VALUES(?,?,?,?)", [
                ("F1","Faculty 1",20,"1,2,3,4,5"), ("F2","Faculty 2",20,"1,2,3,4,5"),
                ("F3","Faculty 3",20,"1,2,3,4,5"), ("F4","Faculty 4",20,"1,2,3,4,5"),
                ("F5","Faculty 5",20,"1,2,3,4,5")])
        if not con.execute("SELECT id FROM courses LIMIT 1").fetchone():
            faculty = {r["code"]:r["id"] for r in con.execute("SELECT id,code FROM faculty")}
            seed = [
                ("AI","Artificial Intelligence","Core",3,1,2,1,"F1"),
                ("ML","Machine Learning","Core",3,1,2,1,"F1"),
                ("CN","Computer Networks","Core",3,1,2,1,"F2"),
                ("JAVA","Java Programming","Core",2,1,2,1,"F3"),
                ("R","R Programming","Open Elective",2,1,2,1,"F4"),
                ("EMS","EMS (edit full name)","Common",2,0,2,0,"F5"),
                ("APT","Aptitude","Common",2,0,2,0,"F5"),
                ("HP","HP (edit full name)","Common",2,0,2,0,"F5")]
            con.executemany("""INSERT INTO courses(code,name,category,lectures_per_week,practicals_per_week,
                               practical_duration,requires_lab,faculty_id) VALUES(?,?,?,?,?,?,?,?)""",
                            [(a,b,c,d,e,f,g,faculty[h]) for a,b,c,d,e,f,g,h in seed])
        if not con.execute("SELECT id FROM rooms LIMIT 1").fetchone():
            con.executemany("INSERT INTO rooms(code,name,room_type,capacity) VALUES(?,?,?,?)", [
                ("R101","Classroom 101","Classroom",60), ("R102","Classroom 102","Classroom",60),
                ("R103","Classroom 103","Classroom",60), ("LAB1","Computer Lab 1","Lab",30),
                ("LAB2","Computer Lab 2","Lab",30)])
        if not con.execute("SELECT id FROM classes LIMIT 1").fetchone():
            con.executemany("INSERT INTO classes(code,section,students,year_label,specialisation) VALUES(?,?,?,?,?)", [
                ("DIML-Y3-A","A",60,"3rd Year","DIML"),("DIML-Y3-B","B",60,"3rd Year","DIML")])

init_db()

def get_settings():
    with connect() as con:
        values = {r["key"]:r["value"] for r in con.execute("SELECT key,value FROM settings")}
    return {**DEFAULT_SETTINGS, **values}

def logged_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        with connect() as con:
            user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@logged_in
def dashboard():
    with connect() as con:
        faculty = con.execute("SELECT * FROM faculty ORDER BY code").fetchall()
        rooms = con.execute("SELECT * FROM rooms ORDER BY code").fetchall()
        courses = con.execute("""SELECT c.*,f.code AS faculty_code FROM courses c
                              LEFT JOIN faculty f ON c.faculty_id=f.id ORDER BY c.code""").fetchall()
        classes = con.execute("SELECT * FROM classes ORDER BY code").fetchall()
        timetable_count = con.execute("SELECT COUNT(*) n FROM timetable").fetchone()["n"]
    return render_template("dashboard.html", settings=get_settings(), faculty=faculty, rooms=rooms,
                           courses=courses, classes=classes, timetable_count=timetable_count,
                           days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"])

@app.route("/settings", methods=["POST"])
@logged_in
def save_settings():
    keys = list(DEFAULT_SETTINGS.keys())
    data = {k:request.form.get(k, DEFAULT_SETTINGS[k]).strip() for k in keys}
    try:
        if int(data["total_students"]) < 1 or int(data["working_days"]) not in (5,6) or int(data["periods_per_day"]) < 1:
            raise ValueError
        if int(data["period_minutes"]) < 1 or int(data["break_minutes"]) < 0 or int(data["section_size"]) < 1:
            raise ValueError
        datetime.strptime(data["day_start"], "%H:%M")
        if not 0 <= int(data["break_after_period"]) <= int(data["periods_per_day"]):
            raise ValueError
    except ValueError:
        flash("Check the numeric settings and start time. Working days must be 5 or 6.", "error")
        return redirect(url_for("dashboard") + "#settings")
    with connect() as con:
        con.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        list(data.items()))
    flash("Academic setup and timetable rules saved.", "success")
    return redirect(url_for("dashboard") + "#settings")

@app.route("/faculty/add", methods=["POST"])
@logged_in
def add_faculty():
    try:
        with connect() as con:
            con.execute("INSERT INTO faculty(code,name,email,max_periods,available_days) VALUES(?,?,?,?,?)", (
                request.form["code"].strip().upper(), request.form["name"].strip(),
                request.form.get("email","").strip(), int(request.form.get("max_periods",20)),
                ",".join(request.form.getlist("available_days")) or "1,2,3,4,5"))
        flash("Faculty added.", "success")
    except (sqlite3.IntegrityError, ValueError):
        flash("Could not add faculty. Check that the ID is unique and workload is valid.", "error")
    return redirect(url_for("dashboard") + "#faculty")

@app.route("/faculty/delete/<int:item_id>", methods=["POST"])
@logged_in
def delete_faculty(item_id):
    with connect() as con:
        con.execute("DELETE FROM faculty WHERE id=?", (item_id,))
    flash("Faculty deleted. Any assigned courses need a new faculty assignment.", "success")
    return redirect(url_for("dashboard") + "#faculty")

@app.route("/courses/add", methods=["POST"])
@logged_in
def add_course():
    try:
        with connect() as con:
            con.execute("""INSERT INTO courses(code,name,category,lectures_per_week,practicals_per_week,
                         practical_duration,requires_lab,faculty_id) VALUES(?,?,?,?,?,?,?,?)""", (
                request.form["code"].strip().upper(), request.form["name"].strip(),
                request.form["category"], int(request.form.get("lectures_per_week",0)),
                int(request.form.get("practicals_per_week",0)), int(request.form.get("practical_duration",2)),
                1 if request.form.get("requires_lab") else 0,
                int(request.form["faculty_id"]) if request.form.get("faculty_id") else None))
        flash("Course added.", "success")
    except (sqlite3.IntegrityError, ValueError, KeyError):
        flash("Could not add course. Check the unique course code and numeric values.", "error")
    return redirect(url_for("dashboard") + "#courses")

@app.route("/courses/delete/<int:item_id>", methods=["POST"])
@logged_in
def delete_course(item_id):
    with connect() as con:
        con.execute("DELETE FROM courses WHERE id=?", (item_id,))
    flash("Course deleted.", "success")
    return redirect(url_for("dashboard") + "#courses")

@app.route("/rooms/add", methods=["POST"])
@logged_in
def add_room():
    try:
        with connect() as con:
            con.execute("INSERT INTO rooms(code,name,room_type,capacity) VALUES(?,?,?,?)", (
                request.form["code"].strip().upper(), request.form["name"].strip(),
                request.form["room_type"], int(request.form.get("capacity",60))))
        flash("Room added.", "success")
    except (sqlite3.IntegrityError, ValueError, KeyError):
        flash("Could not add room. Check the unique room ID and capacity.", "error")
    return redirect(url_for("dashboard") + "#rooms")

@app.route("/rooms/delete/<int:item_id>", methods=["POST"])
@logged_in
def delete_room(item_id):
    with connect() as con:
        con.execute("DELETE FROM rooms WHERE id=?", (item_id,))
    flash("Room deleted.", "success")
    return redirect(url_for("dashboard") + "#rooms")

@app.route("/classes/add", methods=["POST"])
@logged_in
def add_class():
    try:
        with connect() as con:
            con.execute("INSERT INTO classes(code,section,students,year_label,specialisation) VALUES(?,?,?,?,?)", (
                request.form["code"].strip().upper(), request.form["section"].strip().upper(),
                int(request.form.get("students",60)), request.form.get("year_label","3rd Year"),
                request.form.get("specialisation","DIML").strip().upper()))
        flash("Class/section added.", "success")
    except (sqlite3.IntegrityError, ValueError, KeyError):
        flash("Could not add class. Class ID must be unique and student count valid.", "error")
    return redirect(url_for("dashboard") + "#classes")

@app.route("/classes/delete/<int:item_id>", methods=["POST"])
@logged_in
def delete_class(item_id):
    with connect() as con:
        con.execute("DELETE FROM classes WHERE id=?", (item_id,))
    flash("Class/section deleted.", "success")
    return redirect(url_for("dashboard") + "#classes")

def time_slots(settings):
    start = datetime.strptime(settings["day_start"], "%H:%M")
    period = int(settings["period_minutes"])
    break_after = int(settings["break_after_period"])
    break_minutes = int(settings["break_minutes"])
    slots = []
    current = start
    count = int(settings["periods_per_day"])
    for p in range(1, count+1):
        end = current + timedelta(minutes=period)
        slots.append({"period":p,"start":current.strftime("%H:%M"),"end":end.strftime("%H:%M")})
        current = end
        if p == break_after and break_minutes:
            current += timedelta(minutes=break_minutes)
    return slots

def generate_schedule():
    """Build the timetable as a Constraint Satisfaction Problem (see csp_solver.py):
    backtracking search + MRV variable ordering + forward checking + constraint propagation,
    followed by soft-constraint optimisation. Returns a list of messages for the admin."""
    settings = get_settings()
    weekdays = int(settings["working_days"])
    periods = int(settings["periods_per_day"])
    break_after = int(settings["break_after_period"])
    with connect() as con:
        classes = [dict(r) for r in con.execute("SELECT * FROM classes ORDER BY code")]
        courses = [dict(r) for r in con.execute("SELECT * FROM courses ORDER BY code")]
        faculty = [dict(r) for r in con.execute("SELECT * FROM faculty")]
        rooms = [dict(r) for r in con.execute("SELECT * FROM rooms WHERE active=1 ORDER BY capacity")]
        con.execute("DELETE FROM timetable")
        con.commit()
    if not classes or not courses or not rooms or not faculty:
        return ["Add at least one class, course, faculty member and room before generating."]

    problem = build_problem(classes, courses, faculty, rooms, weekdays, periods, break_after)
    errors = list(problem.errors)            # sessions that can never fit + workload warnings
    scheduled, best, rows = [], None, []
    if problem.vars:
        best, rows = solve_and_compare(problem)
        assignment = best["result"]["assignment"]
        for i, (day, start, room_id) in sorted(assignment.items()):
            v = problem.vars[i]
            scheduled.append((v.cls, v.course, v.fid, room_id, day, start, v.dur, v.kind))
        left = [v.label for v in problem.vars if v.idx not in assignment]
        for label in left[:30]:
            errors.append(f"Could not schedule {label}: no conflict-free (day, time, room) left after "
                          f"search. Add rooms/labs/faculty days or reduce sessions.")
        if len(left) > 30:
            errors.append(f"...and {len(left) - 30} more unscheduled session(s).")
    if scheduled:
        with connect() as con:
            con.executemany("""INSERT INTO timetable(class_id,course_id,faculty_id,room_id,day_index,period_index,duration,session_type)
                               VALUES(?,?,?,?,?,?,?,?)""", scheduled)

    report = []
    if best:
        sp = best["soft"]
        report.append(f'Solver report - chosen: {best["strategy"]}. Hard-constraint violations: '
                      f'{best["hard_violations"]}. Soft penalty: {sp["total"]} (empty periods {sp["empty_periods"]}, '
                      f'consecutive difficult subjects {sp["consecutive_difficult"]}, same course twice a day '
                      f'{sp["same_course_same_day"]}, faculty overload {sp["faculty_overload"]}).')
        per_strategy = {}
        for r in rows:
            key = (r["hard_violations"], r["total"] - r["placed"], r["soft"]["total"])
            if r["strategy"] not in per_strategy or key < per_strategy[r["strategy"]][0]:
                per_strategy[r["strategy"]] = (key, r)
        for name, (_, r) in per_strategy.items():
            report.append(f'Solver report - {name}: placed {r["placed"]}/{r["total"]}, hard violations '
                          f'{r["hard_violations"]}, soft penalty {r["soft"]["total"]}, nodes {r["nodes"]}, '
                          f'backtracks {r["backtracks"]}, {r["seconds"]}s{" (stopped at limit)" if r["timed_out"] else ""}.')

    if not scheduled and not errors:
        errors.append("No timetable entries could be generated.")
    if scheduled and not errors:
        head = [f"Successfully scheduled {len(scheduled)} sessions across {len(classes)} class(es) using "
                f"backtracking + MRV + forward checking + constraint propagation. No faculty, room, or class clashes were created."]
    elif scheduled:
        head = [f"Partial timetable: scheduled {len(scheduled)} sessions, but {len(errors)} issue(s) remain. Review the messages below."]
    else:
        head = []
    return head + report + errors

@app.route("/generate", methods=["POST"])
@logged_in
def generate():
    messages = generate_schedule()
    for msg in messages:
        flash(msg, "success" if msg.startswith(("Successfully", "Solver report")) else "error")
    return redirect(url_for("timetable"))

@app.route("/timetable")
@logged_in
def timetable():
    settings = get_settings()
    days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"][:int(settings["working_days"])]
    slots = time_slots(settings)
    class_id = request.args.get("class_id", type=int)
    with connect() as con:
        classes = con.execute("SELECT * FROM classes ORDER BY code").fetchall()
        entries = con.execute("""SELECT t.*,cl.code AS class_code,cl.section,c.code AS course_code,c.name AS course_name,
                              f.code AS faculty_code,r.code AS room_code
                              FROM timetable t JOIN classes cl ON t.class_id=cl.id
                              JOIN courses c ON t.course_id=c.id JOIN faculty f ON t.faculty_id=f.id
                              JOIN rooms r ON t.room_id=r.id ORDER BY t.day_index,t.period_index""").fetchall()
    if class_id is None and classes:
        class_id = classes[0]["id"]
    selected = next((c for c in classes if c["id"] == class_id), None)
    chosen = [e for e in entries if e["class_id"] == class_id]
    grid = {}
    for e in chosen:
        for p in range(e["period_index"], e["period_index"]+e["duration"]):
            grid[(e["day_index"],p)] = e
    return render_template("timetable.html", settings=settings, classes=classes, selected=selected,
                           days=days, slots=slots, grid=grid, entries=chosen,
                           break_after=int(settings["break_after_period"]), break_label=settings["break_label"])

@app.route("/change-password", methods=["GET","POST"])
@logged_in
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password","")
        new = request.form.get("new_password","")
        with connect() as con:
            user = con.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if not check_password_hash(user["password_hash"], old):
                flash("Current password is incorrect.", "error")
            elif len(new) < 10:
                flash("New password must be at least 10 characters.", "error")
            else:
                con.execute("UPDATE users SET password_hash=? WHERE id=?",
                            (generate_password_hash(new), session["user_id"]))
                flash("Password changed.", "success")
                return redirect(url_for("dashboard"))
    return render_template("change_password.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
