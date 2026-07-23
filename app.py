import random
import requests
import string
from flask import Flask, render_template, request, session
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16) # Required for Flask session memory

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
    theme_word, matrix = generate_playable_board()
    
    # Store secret target word in player's browser session (secure, anti-cheat)
    session['target_word'] = theme_word
    
    # Target row index (e.g. middle row or last row)
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

    # If user wins, return the win badge!
    return '<article style="background: var(--pico-ins-color); text-align: center; margin: 0.5rem 0; padding: 0.5rem;">🎉 <strong>SYSTEM UNLOCKED!</strong> You cracked the crypTerm.</article>'

if __name__ == "__main__":
    app.run(debug=True)