# app.py (Updated with login, student profile, search, and invite to poker)

from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from flask_socketio import SocketIO, emit, join_room
import sqlite3, os, uuid, random
from collections import Counter
from itertools import combinations

app = Flask(__name__)
app.secret_key = 'your-secret-key'
DATABASE = 'users.db'
UPLOAD_FOLDER = 'static/uploads'

# Mail config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'madhuvani709@gmail.com'
app.config['MAIL_PASSWORD'] = 'dyueojfushepyzfa'
mail = Mail(app)
socketio = SocketIO(app, cors_allowed_origins="*")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database Setup
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
        conn.execute('''CREATE TABLE IF NOT EXISTS poker_rooms (
            room_id TEXT PRIMARY KEY,
            invited_email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS game_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT,
            player1 TEXT,
            player2 TEXT,
            community_cards TEXT,
            winner TEXT,
            pot INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
    print("Database initialized.")

init_db()

# Routes for Login/Profile/Search
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password_hash = generate_password_hash(request.form['password'])
        with get_db_connection() as conn:
            try:
                conn.execute('INSERT INTO users (email, password_hash) VALUES (?, ?)', (email, password_hash))
                conn.commit()
            except sqlite3.IntegrityError:
                return "Email already registered."
        session['email'] = email
        return redirect(url_for('complete_profile'))
    return render_template('signup.html')

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

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

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

        profile_pic_filename = session['email'] + '_profile_' + profile_picture.filename if profile_picture else None
        resume_filename = session['email'] + '_resume_' + resume_file.filename if resume_file else None

        if profile_picture:
            profile_picture.save(os.path.join(UPLOAD_FOLDER, profile_pic_filename))
        if resume_file:
            resume_file.save(os.path.join(UPLOAD_FOLDER, resume_filename))

        with get_db_connection() as conn:
            conn.execute('''UPDATE users SET full_name = ?, department = ?, marks = ?,
                             profile_picture = ?, resume_file = ? WHERE email = ?''',
                         (full_name, department, marks, profile_pic_filename, resume_filename, session['email']))
            conn.commit()
        return redirect(url_for('profile'))
    return render_template('profile_form.html')

@app.route('/profile')
def profile():
    if 'email' not in session:
        return redirect(url_for('login'))
    with get_db_connection() as conn:
        user = conn.execute('SELECT * FROM users WHERE email = ?', (session['email'],)).fetchone()
    return render_template('profile.html', user=user)

@app.route('/search')
def search():
    query = request.args.get('q', '')
    results = []
    if query:
        with get_db_connection() as conn:
            results = conn.execute('SELECT * FROM users WHERE LOWER(full_name) LIKE ?',
                                   ('%' + query.lower() + '%',)).fetchall()
    return render_template('search_results.html', results=results, query=query)

@app.route('/invite/<int:user_id>')
def invite(user_id):
    with get_db_connection() as conn:
        sender = conn.execute('SELECT * FROM users WHERE email = ?', (session['email'],)).fetchone()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if user:
            room_id = str(uuid.uuid4())
            conn.execute('INSERT INTO poker_rooms (room_id, invited_email) VALUES (?, ?)', (room_id, user['email']))
            conn.commit()

            try:
                game_link = url_for('poker_room', room_id=room_id, _external=True)
                msg = Message('Poker Game Invite', sender=app.config['MAIL_USERNAME'], recipients=[user['email']])
                msg.body = f"Hi {user['full_name']},\nYou've been invited by {sender['full_name']} to play Poker.\nJoin here: {game_link}"
                mail.send(msg)
                return f"<h3>Email sent successfully to {user['email']}</h3><a href='{game_link}'>Join Game</a>"
            except Exception as e:
                return f"Failed to send email: {str(e)}"
    return redirect(url_for('search'))

# Poker game logic remains same as earlier (WebSocket handlers etc)
# ---- Poker Game WebSocket Logic ----
games = {}
rooms_state = {}

def create_deck():
    suits = ['♠', '♥', '♦', '♣']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    return [f"{r}{s}" for s in suits for r in ranks]

def evaluate_hand(cards):
    ranks = [card[:-1] for card in cards]
    suits = [card[-1] for card in cards]
    RANK_VALUES = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':11,'Q':12,'K':13,'A':14}
    rank_counts = Counter(ranks)
    sorted_ranks = sorted([RANK_VALUES[r] for r in ranks], reverse=True)
    suit_counts = Counter(suits)

    is_flush = max(suit_counts.values()) >= 5
    is_straight = any(all(val in sorted_ranks for val in range(start, start+5)) for start in range(2, 11))

    if is_flush and is_straight: return (9, sorted_ranks)
    if 4 in rank_counts.values(): return (8, sorted_ranks)
    if 3 in rank_counts.values() and 2 in rank_counts.values(): return (7, sorted_ranks)
    if is_flush: return (6, sorted_ranks)
    if is_straight: return (5, sorted_ranks)
    if 3 in rank_counts.values(): return (4, sorted_ranks)
    if list(rank_counts.values()).count(2) >= 2: return (3, sorted_ranks)
    if 2 in rank_counts.values(): return (2, sorted_ranks)
    return (1, sorted_ranks)

@socketio.on('joinRoom')
def handle_join(data):
    room = data.get('room')
    name = data.get('name')
    avatar = data.get('avatar')
    sid = request.sid
    join_room(room)

    if room not in games:
        deck = create_deck()
        random.shuffle(deck)
        games[room] = {
            'players': [],
            'deck': deck,
            'hands': {},
            'community': [],
            'chips': {},
            'bets': {},
            'folded': set(),
            'pot': 0,
            'avatars': {},   # ✅ NEW: Map socket IDs to avatar URLs
            'names': {}      # Optional: track names if needed
        }

    game = games[room]

    if sid not in game['players']:
        game['players'].append(sid)
        game['hands'][sid] = [game['deck'].pop(), game['deck'].pop()]
        game['chips'][sid] = 1000
        game['bets'][sid] = 0
        game['avatars'][sid] = avatar
        game['names'][sid] = name

    if len(game['players']) == 2:
        for pid in game['players']:
            emit('gameUpdate', {
                'yourCards': game['hands'][pid],
                'communityCards': ['?', '?', '?', '?', '?'],
                'avatars': [game['avatars'][game['players'][0]], game['avatars'][game['players'][1]]],
                'playerNames': [game['names'][game['players'][0]], game['names'][game['players'][1]]],
                'message': "Game started! Place your move."
            }, room=pid)

    else:
        emit('gameUpdate', {
            'message': "Waiting for second player to join...",
            'communityCards': ['?', '?', '?', '?', '?']
        }, room=sid)


@socketio.on('playerMove')
def handle_move(data):
    room = data['room']
    action = data['action']
    amount = int(data.get('amount', 0))
    player_id = request.sid

    game = games.get(room)
    if not game or player_id not in game['players']:
        return

    if action == 'fold':
        game['folded'].add(player_id)
        emit('gameUpdate', {'message': f"{player_id[:5]} folds."}, to=room)
    elif action == 'call':
        to_call = max(game['bets'].values()) - game['bets'][player_id]
        game['chips'][player_id] -= to_call
        game['pot'] += to_call
        game['bets'][player_id] += to_call
        emit('gameUpdate', {
            'message': f"{player_id[:5]} calls {to_call}.",
            'chips': game['chips'][player_id]
        }, to=room)
    elif action == 'raise':
        if amount <= 0 or amount > game['chips'][player_id]:
            emit('gameUpdate', {'message': "Invalid raise amount."}, room=player_id)
            return
        game['chips'][player_id] -= amount
        game['pot'] += amount
        game['bets'][player_id] += amount
        emit('gameUpdate', {
            'message': f"{player_id[:5]} raises {amount}.",
            'chips': game['chips'][player_id]
        }, to=room)
    elif action == 'check':
        emit('gameUpdate', {'message': f"{player_id[:5]} checks."}, to=room)

    # Progressive card reveal (Flop → Turn → River)
    if len(game['community']) == 0:
        game['community'] = [game['deck'].pop() for _ in range(3)]
    elif len(game['community']) < 5:
        game['community'].append(game['deck'].pop())

    emit('gameUpdate', {
        'communityCards': game['community'],
        'message': f"Community Cards: {' '.join(game['community'])}"
    }, to=room)

    # If 5 community cards shown or 1 player folded → evaluate
    if len(game['community']) == 5 or len(game['folded']) == 1:
        scores = {}
        for pid in game['players']:
            if pid in game['folded']:
                continue
            cards = game['hands'][pid] + game['community']
            scores[pid] = max(
                [evaluate_hand(list(combo)) for combo in combinations(cards, 5)],
                key=lambda x: x
            )
        winner = max(scores.items(), key=lambda x: x[1])[0]
        game['chips'][winner] += game['pot']

        emit('gameUpdate', {
            'message': f"🏆 {game['names'][winner]} wins {game['pot']} chips!",
            'chips': game['chips'][winner],
            'avatars': [game['avatars'][p] for p in game['players']],
            'playerNames': [game['names'][p] for p in game['players']],
            'winnerId': winner,
            'reset': True
        }, room=room)


        # Reset round
        game['deck'] = create_deck()
        random.shuffle(game['deck'])
        game['hands'] = {p: [game['deck'].pop(), game['deck'].pop()] for p in game['players']}
        game['community'] = []
        game['bets'] = {p: 0 for p in game['players']}
        game['folded'] = set()
        game['pot'] = 0

@socketio.on('leaveRoom')
def handle_leave(data):
    room = data.get('room')
    sid = request.sid

    if room in games and sid in games[room]['players']:
        games[room]['players'].remove(sid)

        # Optional: Notify the other player
        emit('gameUpdate', {
            'message': f"{sid[:5]} has left the game. Game ended.",
            'reset': True
        }, room=room)

        # Clean up the game if no players remain
        if len(games[room]['players']) == 0:
            del games[room]
@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    for room, game in list(games.items()):
        if sid in game['players']:
            game['players'].remove(sid)

            # Notify other player
            emit('gameUpdate', {
                'message': f"{sid[:5]} disconnected. Game ended.",
                'reset': True
            }, room=room)

            # Clean up if room is now empty
            if len(game['players']) == 0:
                del games[room]

@app.route('/poker/room/<room_id>')
def poker_room(room_id):
    return render_template('poker_avatar.html', room_id=room_id)
@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == '__main__':
    socketio.run(app, debug=True)

if __name__ == '__main__':
    init_db()
    try:
        socketio.run(app, debug=True, host='127.0.0.1', port=5000)
    except OSError as e:
        print(f"Error: {e}. Try using a different port.")
