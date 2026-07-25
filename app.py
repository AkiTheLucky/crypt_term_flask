import random
import os
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta
import json
import requests
import string
from flask import Flask, render_template, request, session, make_response
import secrets

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

# ==========================================
# 0.2. INITIALIZE TABLES
# ==========================================
# This checks if the database exists, and if not, creates it instantly.
with app.app_context():
    db.create_all()


# ==========================================
# 1. CORE GAME GENERATION LOGIC
# ==========================================

def get_theme_word():
    popular_words_list = []
    while not popular_words_list:
        random_letter = random.choice(string.ascii_uppercase)
        random_word_length = random.randint(4, 7) - 1
        number_of_questionmarks = "?" * random_word_length
        response = requests.get(f"https://api.datamuse.com/words?sp={random_letter}{number_of_questionmarks}&md=f")
        response_list = response.json()

        for item in response_list:
            if "tags" in item and item["tags"]:
                tag_string = item["tags"][0]
                if tag_string.startswith("f:"):
                    frequency_score = float(tag_string[2:])
                    if frequency_score >= 8.8 and " " not in item["word"]:
                        popular_words_list.append(item)
        
    theme_dict = random.choice(popular_words_list)
    return theme_dict["word"].upper()


def get_thematic_bucket(theme_word):
    theme_word = theme_word.upper()
    queries = [
        f"https://api.datamuse.com/words?ml={theme_word}&md=f",
        f"https://api.datamuse.com/words?rel_trg={theme_word}&md=f",
        f"https://api.datamuse.com/words?rel_syn={theme_word}&md=f"
    ]
    
    raw_words = {}
    for url in queries:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                for item in response.json():
                    word = item["word"].upper()
                    freq = 0.0
                    if "tags" in item:
                        for tag in item["tags"]:
                            if tag.startswith("f:"):
                                freq = float(tag[2:])
                                break
                    if word not in raw_words or freq > raw_words[word]["freq"]:
                        raw_words[word] = {"freq": freq, "score": item.get("score", 0)}
        except Exception:
            continue
            
    unfiltered_thematic_bucket_list = []
    for word, meta in raw_words.items():
        if " " in word or "-" in word or not word.isalpha():
            continue
        if theme_word in word or word in theme_word:
            continue
        if meta["freq"] < 1.5:
            continue
        if not (4 <= len(word) <= 9):
            continue
        unfiltered_thematic_bucket_list.append(word)

    return unfiltered_thematic_bucket_list 


def arrange_column_words(theme_word, unfiltered_thematic_bucket_list):
    thematic_bucket_list = []
    bucket_copy = unfiltered_thematic_bucket_list.copy()

    for column_index, letter in enumerate(theme_word):
        found_match = False
        for word in bucket_copy:
            for letter_index, word_char in enumerate(word):
                if word_char == letter:
                    column_dict = {
                        "word": word,
                        "theme_index": column_index,
                        "word_index": letter_index
                    }
                    thematic_bucket_list.append(column_dict)
                    bucket_copy.remove(word)
                    found_match = True
                    break
            if found_match:
                break
        if not found_match:
            raise ValueError("No fitting word found, try again")

    return thematic_bucket_list


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
        theme_word=theme_word
    )


@app.route("/validate", methods=["POST"])
def validate():
    user_guess = request.form.get("word", "").upper().strip()
    target_word = session.get("target_word", "").upper().strip()

    # If user hasn't matched yet, return empty or subtle status
    if not user_guess or user_guess != target_word:
        return "" 

    # Create the HTML badge
    html_badge = '<article style="background: var(--pico-ins-color); text-align: center; margin: 0.5rem 0; padding: 0.5rem;">🎉 <strong>SYSTEM UNLOCKED!</strong> You cracked the crypTerm.</article>'
    
    # Wrap it in a response object so we can add headers
    response = make_response(html_badge)
    
    # 🪄 The HTMX Magic: This triggers a JS event named 'puzzleSolved'
    response.headers["HX-Trigger"] = "puzzleSolved"


    # If user wins, return the win badge!
    return '<article style="background: var(--pico-ins-color); text-align: center; margin: 0.5rem 0; padding: 0.5rem;">🎉 <strong>SYSTEM UNLOCKED!</strong> You cracked the crypTerm.</article>'

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
        theme_word=theme_word
    )

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
    #backfill_historic_puzzles(10)
    # run app
    app.run(debug=True)