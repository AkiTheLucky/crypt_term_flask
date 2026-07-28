import json
import os
import random
import secrets
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, make_response, render_template, request, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = secrets.token_hex(16) # Required for Flask session memory

# ==========================================
# 0. DATABASE CONFIGURATION
# ==========================================
# Look for a live database URL from Render. If it's missing, default to local SQLite.
database_url = os.environ.get('DATABASE_URL', 'sqlite:///crypterm.db')

# Fix a known quirk where Render provides 'postgres://' but SQLAlchemy requires 'postgresql://'
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# 0.1. DATABASE MODELS
# ==========================================
class Puzzle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # The date is unique; we only allow one puzzle per day!
    play_date = db.Column(db.Date, unique=True, nullable=False)
    theme_word = db.Column(db.String(20), nullable=False)
    # SQLite doesn't have a native Array type, so we store the matrix as a text string
    matrix_json = db.Column(db.Text, nullable=False)

class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    puzzle_date = db.Column(db.Date, nullable=False)
    nickname = db.Column(db.String(20), nullable=False)
    time_in_seconds = db.Column(db.Integer, nullable=False)

# ==========================================
# 0.2. INITIALIZE TABLES
# ==========================================
# This checks if the database exists, and if not, creates it instantly.
with app.app_context():
    db.create_all()

# ==========================================
# HELPERS
# ==========================================

def longest_common_substring(s1, s2):
    m, n = len(s1), len(s2)
    max_len = 0
    for i in range(m):
        for j in range(n):
            k = 0
            while i + k < m and j + k < n and s1[i + k] == s2[j + k]:
                k += 1
            max_len = max(max_len, k)
    return max_len

def shared_prefix_len(s1, s2):
    count = 0
    for a, b in zip(s1, s2):
        if a == b:
            count += 1
        else:
            break
    return count

def shared_suffix_len(s1, s2):
    return shared_prefix_len(s1[::-1], s2[::-1])

# ==========================================
# 1. CORE GAME GENERATION LOGIC
# ==========================================

def get_theme_word():
    popular_words_list = []
    while not popular_words_list:
        random_letter = random.choice(string.ascii_uppercase)
        random_word_length = random.randint(4, 8) - 1
        number_of_questionmarks = "?" * random_word_length
        response = requests.get(
            f"https://api.datamuse.com/words?sp={random_letter}{number_of_questionmarks}&md=f"
        )
        response_list = response.json()

        for item in response_list:
            if "tags" in item and item["tags"]:
                tag_string = item["tags"][0]
                if tag_string.startswith("f:"):
                    frequency_score = float(tag_string[2:])
                    if 7.0 <= frequency_score <= 9.2 and " " not in item["word"]:
                        w = item["word"].upper()
                        if w.endswith(("LY", "ED", "ING", "TION")):
                            continue
                        popular_words_list.append(item)
        
    theme_dict = random.choice(popular_words_list)
    return theme_dict["word"].upper()


# Kimi renamed this, I changed it back to match your original call
def get_thematic_bucket(theme_word):
    theme_word = theme_word.upper()
    
    queries = [
        (f"https://api.datamuse.com/words?ml={theme_word}&md=fp", 1.0),
        (f"https://api.datamuse.com/words?rel_syn={theme_word}&md=fp", 0.9),
        (f"https://api.datamuse.com/words?rel_trg={theme_word}&md=fp", 0.6),
    ]
    
    antonyms = set()
    try:
        resp = requests.get(f"https://api.datamuse.com/words?rel_ant={theme_word}")
        if resp.status_code == 200:
            antonyms = {item["word"].upper() for item in resp.json()}
    except Exception:
        pass

    raw_words = {}
    for url, weight in queries:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                for item in response.json():
                    word = item["word"].upper()
                    freq = 0.0
                    pos_tags = []
                    
                    if "tags" in item:
                        for tag in item["tags"]:
                            if tag.startswith("f:"):
                                freq = float(tag[2:])
                            elif tag in ("n", "v", "adj", "adv", "u"):
                                pos_tags.append(tag)
                    
                    score = item.get("score", 0) * weight
                    
                    if word not in raw_words or score > raw_words[word]["score"]:
                        raw_words[word] = {
                            "freq": freq,
                            "score": score,
                            "pos": pos_tags
                        }
        except Exception:
            continue

    candidates = []
    for word, meta in raw_words.items():
        if " " in word or "-" in word or not word.isalpha():
            continue
        if theme_word in word or word in theme_word:
            continue
        if not (4 <= len(word) <= 9):
            continue
        if meta["freq"] < 1.5 or meta["freq"] > 9.5:
            continue
        if word in antonyms:
            continue
        if longest_common_substring(theme_word, word) >= 3:
            continue
        if shared_prefix_len(theme_word, word) >= 3:
            continue
        if shared_suffix_len(theme_word, word) >= 3:
            continue
        if word.startswith(theme_word) or word.endswith(theme_word):
            continue
        
        quality = meta["score"] * (meta["freq"] / 10)
        
        candidates.append({
            "word": word,
            "freq": meta["freq"],
            "score": meta["score"],
            "quality": quality,
            "pos": meta["pos"]
        })
    
    return candidates

def arrange_column_words(theme_word, candidates):
    theme_word = theme_word.upper()
    
    letter_candidates = defaultdict(list)
    
    for cand in candidates:
        word = cand["word"]
        seen_positions = set()
        
        for word_index, char in enumerate(word):
            for theme_index, theme_char in enumerate(theme_word):
                if char == theme_char and (theme_index, word_index) not in seen_positions:
                    seen_positions.add((theme_index, word_index))
                    letter_candidates[theme_index].append({
                        **cand,
                        "theme_index": theme_index,
                        "word_index": word_index
                    })
    
    for i in letter_candidates:
        seen = set()
        unique = []
        for c in letter_candidates[i]:
            if c["word"] not in seen:
                seen.add(c["word"])
                unique.append(c)
        letter_candidates[i] = unique
    
    for i in letter_candidates:
        letter_candidates[i].sort(key=lambda x: x["quality"], reverse=True)
        letter_candidates[i] = letter_candidates[i][:20]
    
    def score_combo(combo):
        words = [c["word"] for c in combo]
        avg_quality = sum(c["quality"] for c in combo) / len(combo)
        
        suffixes = [w[-3:] for w in words]
        suffix_diversity = len(set(suffixes)) / len(words)
        
        prefixes = [w[:3] for w in words]
        prefix_diversity = len(set(prefixes)) / len(words)
        
        lengths = [len(w) for w in words]
        length_diversity = len(set(lengths)) / len(words)
        
        pattern_penalty = 0
        for pattern in ["LY", "ED", "ING", "ER", "TION", "NESS"]:
            count = sum(1 for w in words if w.endswith(pattern))
            if count >= 3:
                pattern_penalty += (count - 2) * 1.5 
            elif count == 2:
                pattern_penalty += 0.3
        
        all_pos = []
        for c in combo:
            all_pos.extend(c.get("pos", []))
        pos_diversity = len(set(all_pos)) / max(len(all_pos), 1)
        
        return (
            avg_quality * 2.0 +
            suffix_diversity * 2.5 +      
            prefix_diversity * 0.5 +
            length_diversity * 0.5 -
            pattern_penalty * 3.0 +       
            pos_diversity * 0.3
        )
    
    best_combo = None
    best_score = -float('inf')
    
    for _ in range(5000):
        combo = []
        used_words = set()
        valid = True
        
        for i in range(len(theme_word)):
            available = [c for c in letter_candidates[i] if c["word"] not in used_words]
            if not available:
                valid = False
                break
            choice = random.choice(available)
            combo.append(choice)
            used_words.add(choice["word"])
        
        if valid:
            s = score_combo(combo)
            if s > best_score:
                best_score = s
                best_combo = combo
    
    if best_combo is None:
        raise ValueError("No valid combination found, try again")
    
    # I ADDED THIS: Strip out Kimi's extra metadata so your backend isn't confused
    clean_combo = []
    for item in best_combo:
        clean_combo.append({
            "word": item["word"],
            "theme_index": item["theme_index"],
            "word_index": item["word_index"]
        })

    return clean_combo

def build_cryptex_matrix(theme_word, thematic_bucket_list):
    max_height_matrix = max(len(item["word"]) for item in thematic_bucket_list) + 1 
    matrix_width = len(theme_word)
    cryptex_matrix = []

    for _ in range(matrix_width):
        cryptex_matrix.append([" "] * max_height_matrix)

    for column_index in range(matrix_width):
        current_word = thematic_bucket_list[column_index]["word"]
        for char_index, char in enumerate(current_word):
            cryptex_matrix[column_index][char_index] = char

    return cryptex_matrix


def generate_playable_board():
    while True:
        try:
            theme_word = get_theme_word()
            unfiltered_bucket = get_thematic_bucket(theme_word)
            bucket_list = arrange_column_words(theme_word, unfiltered_bucket)
            matrix = build_cryptex_matrix(theme_word, bucket_list)
            return theme_word, matrix
        except ValueError:
            pass


# ==========================================
# 2. FLASK ROUTES
# ==========================================

@app.route("/")
def index():
    # 1. Get today's date strictly in UTC
    today = datetime.now(timezone.utc).date()
    
    # 2. Ask the database: Do we already have a puzzle for today?
    daily_puzzle = Puzzle.query.filter_by(play_date=today).first()

    if daily_puzzle:
        # 3a. WE HAVE ONE! Load the saved data.
        theme_word = daily_puzzle.theme_word
        
        # We stored the matrix as a JSON string, so we convert it back into a Python list
        matrix = json.loads(daily_puzzle.matrix_json)
        
        # Optional: A little terminal print so you can see what's happening behind the scenes
        print(f"Loaded existing puzzle for {today}: {theme_word}")
        
    else:
        # 3b. BRAND NEW DAY! Generate a fresh puzzle.
        theme_word, matrix = generate_playable_board()
        
        # Package it up and save it to the database
        new_puzzle = Puzzle(
            play_date=today,
            theme_word=theme_word,
            matrix_json=json.dumps(matrix) # Convert list to string for storage
        )
        db.session.add(new_puzzle)
        db.session.commit()
        
        print(f"Generated and saved new puzzle for {today}: {theme_word}")

    # 4. The rest of the setup stays exactly the same
    session['target_word'] = theme_word
    pointer_index = len(matrix[0]) - 1

    return render_template(
        "index.html", 
        columns=matrix, 
        pointer_index=pointer_index,
        theme_word=theme_word,
        play_date=today
    )

@app.route("/validate", methods=["POST"])
def validate():
    user_guess = request.form.get("word", "").upper().strip()
    target_word = session.get("target_word", "").upper().strip()

    if not user_guess or user_guess != target_word:
        return "" 

    # We return the badge AND a script block. 
    # HTMX is smart enough to execute the script instantly upon swap!
    return '''
    <article style="background: var(--pico-ins-color); text-align: center; margin: 0.5rem 0; padding: 0.5rem;">
        <strong>UNLOCKED!</strong> You cracked the crypTerm.
    </article>
    <script>
        if (typeof triggerWin === 'function') {
            triggerWin();
        }
    </script>
    '''


@app.route("/archive")
def archive():
    # Fetch all puzzles, sorted by newest date first
    # We use .all() to get a list of Puzzle objects
    historic_puzzles = Puzzle.query.order_by(Puzzle.play_date.desc()).all()
    
    return render_template("archive.html", puzzles=historic_puzzles)

@app.route("/play/<puzzle_date>")
def play_historic(puzzle_date):
    # 1. Convert the URL string (e.g., '2026-07-14') back into a Python Date object
    try:
        target_date = datetime.strptime(puzzle_date, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid date format", 400

    # 2. Look up that specific date in the database
    historic_puzzle = Puzzle.query.filter_by(play_date=target_date).first()
    
    if not historic_puzzle:
        return "Puzzle not found for this date.", 404

    # 3. Unpack the puzzle data
    theme_word = historic_puzzle.theme_word
    matrix = json.loads(historic_puzzle.matrix_json)
    
    # 4. VERY IMPORTANT: Set the session target word so the HTMX check & Hint button work!
    session['target_word'] = theme_word
    pointer_index = len(matrix[0]) - 1

    # 5. Serve the exact same index.html we use for the daily game!
    return render_template(
        "index.html", 
        columns=matrix, 
        pointer_index=pointer_index,
        theme_word=theme_word,
        play_date=target_date
    )

@app.route("/submit_score", methods=["POST"])
def submit_score():
    nickname = request.form.get("nickname", "Anonymous").strip()
    time_in_seconds = request.form.get("time_in_seconds", type=int)
    
    # Safety fallback so the database never crashes with a 'None' error again
    if time_in_seconds is None:
        time_in_seconds = 999
        
    date_str = request.form.get("puzzle_date")
    try:
        play_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        play_date = datetime.now(timezone.utc).date()

    new_score = Score(
        puzzle_date=play_date,
        nickname=nickname[:15], 
        time_in_seconds=time_in_seconds
    )
    db.session.add(new_score)
    db.session.commit()
    
    # Tell HTMX to force a redirect to the leaderboard page!
    response = make_response("")
    response.headers["HX-Redirect"] = f"/leaderboard/{play_date}"
    return response
    
@app.route("/leaderboard/<puzzle_date>")
def leaderboard(puzzle_date):
    try:
        target_date = datetime.strptime(puzzle_date, '%Y-%m-%d').date()
    except ValueError:
        target_date = datetime.now(timezone.utc).date()

    # Query the database: Get top 10 fastest scores for this specific date
    top_scores = Score.query.filter_by(puzzle_date=target_date)\
                            .order_by(Score.time_in_seconds.asc())\
                            .limit(10).all()
    
    return render_template("leaderboard.html", scores=top_scores, play_date=target_date)

# ==========================================
# 0.3. backfill puzzles for archive
# ==========================================
# backfill old puzzle for archive page
def backfill_historic_puzzles(days_to_backfill=10):
    with app.app_context():
        # Get today's date strictly in UTC
        today = datetime.now(timezone.utc).date()
        
        for i in range(1, days_to_backfill + 1):
            # Calculate the date for 'i' days ago
            past_date = today - timedelta(days=i)
            
            # Check if we already generated this day
            existing_puzzle = Puzzle.query.filter_by(play_date=past_date).first()
            
            if not existing_puzzle:
                # We removed the broad try/except block. 
                # If this fails, it will now properly tell us exactly why!
                theme_word, matrix = generate_playable_board()
                
                new_puzzle = Puzzle(
                    play_date=past_date,
                    theme_word=theme_word,
                    matrix_json=json.dumps(matrix)
                )
                db.session.add(new_puzzle)
                print(f"Backfilled puzzle for {past_date}: {theme_word}")
        
        # Save all the newly generated puzzles at once
        db.session.commit()
        print("Backfill complete!")




if __name__ == "__main__":
# 1. Force the backfill to run right before the server starts!
    #print("Starting backfill process...")
    backfill_historic_puzzles(10)
    # run app
    app.run(debug=True)