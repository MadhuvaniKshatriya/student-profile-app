from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key'
DATABASE = 'users.db'
UPLOAD_FOLDER = 'static/uploads'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            department TEXT,
            marks TEXT,
            profile_picture TEXT,
            resume_file TEXT
        )''')
    print("Database initialized.")

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        password_hash = generate_password_hash(password)
        with get_db_connection() as conn:
            try:
                conn.execute('INSERT INTO users (email, password_hash) VALUES (?, ?)', (email, password_hash))
                conn.commit()
            except sqlite3.IntegrityError:
                return "Email already registered."
        session['email'] = email
        return redirect(url_for('complete_profile'))
    return render_template('signup.html')

@app.route('/complete_profile', methods=['GET', 'POST'])
def complete_profile():
    if 'email' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        full_name = request.form['full_name']
        department = request.form['department']
        marks = request.form['marks']
        profile_picture = request.files.get('profile_picture')
        resume_file = request.files.get('resume_file')

        picture_filename = None
        resume_filename = None

        if profile_picture and profile_picture.filename:
            picture_filename = session['email'] + '_profile_' + profile_picture.filename
            profile_picture.save(os.path.join(UPLOAD_FOLDER, picture_filename))

        if resume_file and resume_file.filename:
            resume_filename = session['email'] + '_resume_' + resume_file.filename
            resume_file.save(os.path.join(UPLOAD_FOLDER, resume_filename))

        with get_db_connection() as conn:
            conn.execute('''UPDATE users SET full_name = ?, department = ?, marks = ?, 
                             profile_picture = ?, resume_file = ? WHERE email = ?''',
                         (full_name, department, marks, picture_filename, resume_filename, session['email']))
            conn.commit()
        return redirect(url_for('profile'))
    return render_template('profile_form.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        with get_db_connection() as conn:
            user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session['email'] = user['email']
                return redirect(url_for('profile'))
            return "Invalid credentials."
    return render_template('login.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'email' not in session:
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        user = conn.execute('SELECT * FROM users WHERE email = ?', (session['email'],)).fetchone()

        if request.method == 'POST':
            full_name = request.form['full_name']
            department = request.form['department']
            marks = request.form['marks']

            # Handle new file uploads
            profile_picture = request.files.get('profile_picture')
            resume_file = request.files.get('resume_file')

            picture_filename = user['profile_picture']
            resume_filename = user['resume_file']

            if profile_picture and profile_picture.filename:
                picture_filename = session['email'] + '_profile_' + profile_picture.filename
                profile_picture.save(os.path.join(UPLOAD_FOLDER, picture_filename))

            if resume_file and resume_file.filename:
                resume_filename = session['email'] + '_resume_' + resume_file.filename
                resume_file.save(os.path.join(UPLOAD_FOLDER, resume_filename))

            conn.execute('''
                UPDATE users SET full_name = ?, department = ?, marks = ?, 
                profile_picture = ?, resume_file = ? WHERE email = ?
            ''', (full_name, department, marks, picture_filename, resume_filename, session['email']))
            conn.commit()
            return redirect(url_for('profile'))

    return render_template('profile.html', user=user)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    results = []
    if query:
        with get_db_connection() as conn:
            results = conn.execute('''SELECT * FROM users WHERE LOWER(full_name) LIKE ?''',
                                   ('%' + query.lower() + '%',)).fetchall()
    return render_template('search_results.html', results=results, query=query)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    try:
        app.run(debug=True, use_reloader=True, host='127.0.0.1', port=5000)
    except OSError as e:
        print(f"Error: {e}. Try using a different port.")
