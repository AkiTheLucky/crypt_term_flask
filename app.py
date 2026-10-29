import json
import logging
import os
import random
import secrets
import string
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests
from flask import Flask, make_response, render_template, request, session

app = Flask(__name__)

# ------------------------------------------
# SESSION SECRET
# ------------------------------------------
# A randomly generated key at import time means every restart/deploy (and every
# worker, if you run more than one) signs cookies differently. Anyone with a
# board open across a restart would then have their session silently invalidated
# and the puzzle would stop validating. Set SECRET_KEY in the environment and
# this stays stable forever.
_secret_key = os.environ.get("SECRET_KEY", "").strip()
if not _secret_key:
    _secret_key = secrets.token_hex(16)
    logging.getLogger(__name__).warning(
        "SECRET_KEY is not set - falling back to a random key. Every restart "
        "will invalidate open sessions. Set SECRET_KEY in the environment."
    )
app.secret_key = _secret_key

# ==========================================
# 0. DATABASE CONFIGURATION
# ==========================================

D1_API_URL = os.environ.get("D1_API_URL")
D1_API_SECRET = os.environ.get("D1_API_SECRET")

# ==========================================
# 0b. NETWORK / GENERATION LIMITS
# ==========================================
# Every outbound call gets a hard timeout and every retry loop gets a cap, so a
# slow or stuck upstream can fail the request instead of pinning the worker.
DATAMUSE_TIMEOUT = 6          # seconds, per HTTP call
DATAMUSE_WORD_ATTEMPTS = 10   # how many random starting letters to try
MAX_BOARD_ATTEMPTS = 6        # how many full puzzle generations to try
GENERATION_BUDGET = 20.0      # seconds of wall clock for one board, all attempts

logger = logging.getLogger(__name__)


class GenerationError(RuntimeError):
    """Raised when no playable board could be generated within the limits."""


def datamuse(url):
    """GET a Datamuse URL with a timeout. Raises on non-200 responses."""
    response = requests.get(url, timeout=DATAMUSE_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _check_deadline(deadline):
    if deadline is not None and time.monotonic() > deadline:
        raise GenerationError(
            f"Gave up after {GENERATION_BUDGET:.0f}s of upstream slowness"
        )


def d1_query(sql, params=None):
    """Send a SQL query to our Cloudflare D1 Worker."""
    if not D1_API_URL or not D1_API_SECRET:
        raise RuntimeError(
            "D1_API_URL and D1_API_SECRET must be set in the environment."
        )

    if params is None:
        params = []

    response = requests.post(
        D1_API_URL,
        json={
            "sql": sql,
            "params": params
        },
        headers={
            "Authorization": f"Bearer {D1_API_SECRET}"
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        raise RuntimeError(data.get("error", "D1 query failed"))

    return data["result"]


def d1_rows(sql, params=None):
    """Run a SELECT query and return its rows."""
    result = d1_query(sql, params)
    return result.get("results", [])


def d1_execute(sql, params=None):
    """Run an INSERT/UPDATE/DELETE query."""
    return d1_query(sql, params)


_puzzle_index_lock = threading.Lock()
_puzzle_index_ready = False


def ensure_puzzle_index():
    """Best-effort UNIQUE index on puzzle.play_date.

    Without it, two visitors arriving at the same moment on a fresh day can both
    generate and insert a puzzle, leaving duplicate rows for one date. This runs
    once per process; if it fails (old duplicates already in the table, worker
    restricts DDL, ...) the app keeps working and reads stay consistent because
    every query orders by id and takes the first row.
    """
    global _puzzle_index_ready
    if _puzzle_index_ready:
        return

    with _puzzle_index_lock:
        if _puzzle_index_ready:
            return
        try:
            d1_execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_puzzle_play_date "
                "ON puzzle(play_date)"
            )
        except Exception as exc:  # pragma: no cover - depends on D1 state
            logger.warning("Could not create unique index on puzzle.play_date: %s", exc)
        finally:
            # Do not retry on every request, even if it failed.
            _puzzle_index_ready = True

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

def get_theme_word(deadline=None):
    """Pick a random, reasonably common dictionary word to build a puzzle around.

    Bounded to DATAMUSE_WORD_ATTEMPTS calls (and to the shared deadline) so a
    Datamuse miss can never spin forever on a request thread.
    """
    for _ in range(DATAMUSE_WORD_ATTEMPTS):
        _check_deadline(deadline)
        random_letter = random.choice(string.ascii_uppercase)
        random_word_length = random.randint(4, 8) - 1
        number_of_questionmarks = "?" * random_word_length

        try:
            response_list = datamuse(
                f"https://api.datamuse.com/words"
                f"?sp={random_letter}{number_of_questionmarks}&md=f"
            )
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Datamuse lookup failed: %s", exc)
            continue

        popular_words_list = []
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

        if popular_words_list:
            theme_dict = random.choice(popular_words_list)
            return theme_dict["word"].upper()

    raise GenerationError(
        f"No theme word found in {DATAMUSE_WORD_ATTEMPTS} attempts"
    )



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
        resp = requests.get(
            f"https://api.datamuse.com/words?rel_ant={theme_word}",
            timeout=DATAMUSE_TIMEOUT,
        )
        if resp.status_code == 200:
            antonyms = {item["word"].upper() for item in resp.json()}
    except (requests.RequestException, ValueError):
        pass

    raw_words = {}
    for url, weight in queries:
        try:
            response = datamuse(url)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Datamuse query failed (%s): %s", url, exc)
            continue

        for item in response:
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
    """Generate a board, retrying within a bounded number of attempts and time."""
    last_error = None
    deadline = time.monotonic() + GENERATION_BUDGET

    for _ in range(MAX_BOARD_ATTEMPTS):
        try:
            _check_deadline(deadline)
            theme_word = get_theme_word(deadline)
            unfiltered_bucket = get_thematic_bucket(theme_word)
            bucket_list = arrange_column_words(theme_word, unfiltered_bucket)
            matrix = build_cryptex_matrix(theme_word, bucket_list)
            return theme_word, matrix
        except (ValueError, GenerationError) as exc:
            last_error = exc
            logger.info("Board attempt failed, retrying: %s", exc)

    raise GenerationError(
        f"Could not generate a board in {MAX_BOARD_ATTEMPTS} attempts: {last_error}"
    )


def build_reveal(matrix, theme_word):
    """Describe each column word and where the theme letter sits inside it.

    Used on the win screen so the player sees *why* the columns belong together:
    the highlighted letters, read left to right, spell the theme word.
    """
    reveal = []
    for column, target_char in zip(matrix, theme_word.upper()):
        word = "".join(ch for ch in column if ch.strip())
        index = word.find(target_char)
        if index == -1:
            html = word
        else:
            html = f"{word[:index]}<mark>{word[index]}</mark>{word[index + 1:]}"
        reveal.append({"word": word, "index": index, "html": html})
    return reveal



@app.context_processor
def inject_asset_version():
    """Cache-busting token based on the mtime of the static assets.

    Every template shares one value, so a CSS/JS edit reaches the game page and
    the archive/leaderboard at the same time instead of drifting apart.
    """
    return {"asset_version": asset_version()}


@app.after_request
def revalidate_html(response):
    """Make browsers revalidate pages instead of heuristically caching them.

    Without this, a deploy can leave visitors on an old page that still points
    at an old ?v= asset, which is exactly the staleness the shared version
    token is meant to prevent. Responses are still validatable (304s), so this
    costs almost nothing.
    """
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


ASSET_CACHE = {"value": "1"}


def asset_version():
    if ASSET_CACHE["value"] != "1":
        return ASSET_CACHE["value"]

    static_dir = os.path.join(app.root_path, "static")
    newest = 0.0
    for root, _dirs, files in os.walk(static_dir):
        for name in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            except OSError:
                continue
    ASSET_CACHE["value"] = str(int(newest))
    return ASSET_CACHE["value"]


def load_puzzle_for_date(play_date):
    """Return (theme_word, matrix) for a date, generating it if missing.

    Uses INSERT OR IGNORE plus a canonical read so two visitors hitting a fresh
    day at the same moment converge on the same puzzle instead of creating
    duplicates that the archive then lists twice.
    """
    date_str = play_date.isoformat()

    rows = d1_rows(
        """
        SELECT theme_word, matrix_json
        FROM puzzle
        WHERE play_date = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        [date_str]
    )

    if rows:
        return rows[0]["theme_word"], json.loads(rows[0]["matrix_json"])

    ensure_puzzle_index()

    theme_word, matrix = generate_playable_board()

    try:
        d1_execute(
            """
            INSERT OR IGNORE INTO puzzle (play_date, theme_word, matrix_json)
            VALUES (?, ?, ?)
            """,
            [date_str, theme_word, json.dumps(matrix)]
        )
    except Exception:
        # Someone else may have inserted first; re-read below either way.
        logger.warning("Insert for %s failed, re-reading", date_str, exc_info=True)

    # Always serve whatever row actually won the race.
    rows = d1_rows(
        """
        SELECT theme_word, matrix_json
        FROM puzzle
        WHERE play_date = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        [date_str]
    )

    if not rows:
        raise RuntimeError(f"Puzzle for {date_str} could not be stored")

    return rows[0]["theme_word"], json.loads(rows[0]["matrix_json"])


def serve_board(theme_word, matrix, play_date):
    session["target_word"] = theme_word
    session["reveal"] = build_reveal(matrix, theme_word)

    return render_template(
        "index.html",
        columns=matrix,
        pointer_index=len(matrix[0]) - 1,
        theme_word=theme_word,
        play_date=play_date
    )


# ==========================================
# 2. new cloudflare ROUTES
# ==========================================

@app.route("/")
def index():
    # Get today's date strictly in UTC
    today = datetime.now(timezone.utc).date()

    theme_word, matrix = load_puzzle_for_date(today)

    return serve_board(theme_word, matrix, today)


@app.route("/validate", methods=["POST"])
def validate():
    user_guess = request.form.get("word", "").upper().strip()
    target_word = session.get("target_word", "").upper().strip()

    if not user_guess or user_guess != target_word:
        return ""

    # The reveal (theme word + column words) is only ever sent after a correct
    # guess, so the answer is not sitting in the page before the player wins.
    return render_template(
        "partials/win_reveal.html",
        theme_word=target_word,
        reveal=session.get("reveal", [])
    )


@app.route("/archive")
def archive():
    # One row per date: if a race ever produced duplicates, the first insert wins.
    historic_puzzles = d1_rows(
        """
        SELECT play_date
        FROM puzzle
        WHERE id IN (SELECT MIN(id) FROM puzzle GROUP BY play_date)
        ORDER BY play_date DESC
        """
    )

    for puzzle in historic_puzzles:
        puzzle["play_date"] = datetime.strptime(
            puzzle["play_date"],
            "%Y-%m-%d"
        ).date()

    return render_template("archive.html", puzzles=historic_puzzles)


@app.route("/play/<puzzle_date>")
def play_historic(puzzle_date):
    # Convert the URL string into a Python date
    try:
        target_date = datetime.strptime(
            puzzle_date,
            "%Y-%m-%d"
        ).date()
    except ValueError:
        return "Invalid date format", 400

    # Do NOT allow future puzzles to be played
    today = datetime.now(timezone.utc).date()

    if target_date > today:
        return "That puzzle isn't available yet.", 404

    # Look up the puzzle in D1
    rows = d1_rows(
        """
        SELECT theme_word, matrix_json
        FROM puzzle
        WHERE play_date = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        [target_date.isoformat()]
    )

    if not rows:
        return "Puzzle not found for this date.", 404

    theme_word = rows[0]["theme_word"]
    matrix = json.loads(rows[0]["matrix_json"])

    # Serve the exact same game page
    return serve_board(theme_word, matrix, target_date)


@app.route("/submit_score", methods=["POST"])
def submit_score():
    nickname = request.form.get("nickname", "Anonymous").strip()

    time_in_seconds = request.form.get(
        "time_in_seconds",
        type=int
    )

    # Safety fallback
    if time_in_seconds is None:
        time_in_seconds = 999

    date_str = request.form.get("puzzle_date")

    try:
        play_date = datetime.strptime(
            date_str,
            "%Y-%m-%d"
        ).date()
    except (ValueError, TypeError):
        play_date = datetime.now(timezone.utc).date()

    d1_execute(
        """
        INSERT INTO score (
            puzzle_date,
            nickname,
            time_in_seconds
        )
        VALUES (?, ?, ?)
        """,
        [
            play_date.isoformat(),
            nickname[:15],
            time_in_seconds
        ]
    )

    # Tell HTMX to force a redirect to the leaderboard
    response = make_response("")
    response.headers["HX-Redirect"] = f"/leaderboard/{play_date}"

    return response

@app.route("/leaderboard/<puzzle_date>")
def leaderboard(puzzle_date):
    try:
        target_date = datetime.strptime(
            puzzle_date,
            "%Y-%m-%d"
        ).date()
    except ValueError:
        target_date = datetime.now(timezone.utc).date()

    # Get top 10 fastest scores from D1
    top_scores = d1_rows(
        """
        SELECT nickname, time_in_seconds
        FROM score
        WHERE puzzle_date = ?
        ORDER BY time_in_seconds ASC
        LIMIT 10
        """,
        [target_date.isoformat()]
    )

    return render_template(
        "leaderboard.html",
        scores=top_scores,
        play_date=target_date
    )

@app.errorhandler(GenerationError)
def handle_generation_error(exc):
    logger.error("Puzzle generation failed: %s", exc)
    return render_template("error.html"), 503


if __name__ == "__main__":
    app.run(debug=True)