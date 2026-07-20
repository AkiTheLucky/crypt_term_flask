import os
import requests
from flask import Flask, jsonify, render_template, request, redirect, session, url_for
import random
import string


app = Flask(__name__)
app.secret_key = "choose_a_long_random_string_for_sessions"

# --- REUSE YOUR LOGIC HERE ---
# Paste your functions here: get_theme_word(), get_thematic_bucket(), 
# arrange_column_words(), and generate_playable_board()

def get_theme_word():

    popular_words_list = []
    while popular_words_list == []:

        random_letter = random.choice(string.ascii_uppercase)
        random_word_length = random.randint(4, 7) - 1
        number_of_questionmarks = "?" * random_word_length
        response = requests.get("https://api.datamuse.com/words?sp=" + random_letter + number_of_questionmarks + "&md=f")
        response_list = response.json()
        
        
        for item in response_list:
            tag_string = item["tags"][0]

            frequency_score = float(tag_string[2:])

            if frequency_score >= 8.8 and " " not in item["word"]: # make sure that this isnt too high, otherwise you just get repeated words for some letters
                popular_words_list.append(item)
        
    theme_dict = random.choice(popular_words_list)
    
    theme_word = theme_dict["word"].upper()
    
    return theme_word



def get_thematic_bucket(theme_word):
    theme_word = theme_word.upper()
    
    # We query multiple Datamuse endpoints to gather a diverse mix of words
    # ml = Means Like, rel_trg = Associative Triggers, rel_syn = Synonyms
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
                    
                    # Robust frequency score parsing (handles potential tag order variations)
                    freq = 0.0
                    if "tags" in item:
                        for tag in item["tags"]:
                            if tag.startswith("f:"):
                                freq = float(tag[2:])
                                break
                    
                    # Store unique words, keeping the one with the highest frequency/score
                    if word not in raw_words or freq > raw_words[word]["freq"]:
                        raw_words[word] = {
                            "freq": freq,
                            "score": item.get("score", 0)
                        }
        except Exception:
            # If a single request fails, carry on to the next
            continue
            
    unfiltered_thematic_bucket_list = []
    
    for word, meta in raw_words.items():
        # 1. Clean up: Skip phrases, hyphenated words, or non-alphabetic strings
        if " " in word or "-" in word or not word.isalpha():
            continue
            
        # 2. Substring & Stem Block: 
        # Prevents "lamppost" for "lamp" (theme_word in word)
        # And prevents "lamp" for "lamppost" (word in theme_word)
        if theme_word in word or word in theme_word:
            continue
            
        # 3. Popularity threshold: filter out highly obscure words.
        # A frequency score (per million words) of > 1.0 or 2.0 ensures 
        # the auxiliary words are recognizable to an average player.
        if meta["freq"] < 1.5:
            continue
            
        # 4. Length limits: keep the vertical columns visually balanced 
        # (e.g., between 4 and 9 letters)
        if not (4 <= len(word) <= 9):
            continue
            
        unfiltered_thematic_bucket_list.append(word)



    return unfiltered_thematic_bucket_list 


#new function for the word matching
def arrange_column_words(theme_word, unfiltered_thematic_bucket_list):
    thematic_bucket_list = []
    #to get from the unfiltered list to the filtered list, i need to get len(theme_word) amount of words that share the right letters
    #do i do this in here or in a seperate function? i guess i do it here
    #maybe in regards to re-usability, i want to have it seperate? considering that i need to re-use the thematic bucket list again in the puzzle logic? im not sure
    
    for column_index, letter in enumerate(theme_word):
        found_match = False

        for word in unfiltered_thematic_bucket_list:
            for letter_index, word_char in enumerate(word):

                if word_char == letter:
                    
                    column_dict = {
                        "word": word,
                        "theme_index": column_index,
                        "word_index": letter_index
                    }

                    thematic_bucket_list.append(column_dict)
                    unfiltered_thematic_bucket_list.remove(word)
                    found_match = True
                    break
            if found_match:
                break
        if not found_match :
            raise ValueError("no fitting word found, try again")
            #implement logic later to re-run the file for another theme word(?)

    return thematic_bucket_list


#time to build the matrix that will get printed on the screen later
def build_cryptex_matrix(theme_word, thematic_bucket_list):
    #1. Find the height of the tallest column / longest aux word
    max_height_matrix = max(len(item["word"]) for item in thematic_bucket_list) + 1 
    
    matrix_width= len(theme_word)

    cryptex_matrix = []

    for i in range(matrix_width):
        column_list = [" "] * max_height_matrix
        cryptex_matrix.append(column_list)
       
    
    #2nd loop to drop in the words
    for column_index in range(matrix_width):
        current_word = thematic_bucket_list[column_index]["word"]

        for char_index, char in enumerate(current_word):
            cryptex_matrix[column_index][char_index] = char
            
        



    return cryptex_matrix



#screenshot helper function for winning screen
def create_perfect_board_snapshot(cryptex_matrix, term, box_start_x, box_start_y):
    snapshot_lines = []
    
    cols = len(cryptex_matrix)
    rows = len(cryptex_matrix[0])
    box_width = (cols * 4) + 12
    
    # ==========================================
    # 1. TOP Y PADDING (Empty lines before the box)
    # ==========================================
    for _ in range(box_start_y):
        snapshot_lines.append(" " * term.width)
        
    # ==========================================
    # 2. X PADDING HELPER 
    # ==========================================
    def pad_x(line_content):
        # Add the left offset
        left_pad = " " * box_start_x
        # Calculate exactly how many spaces are needed to reach the right wall
        right_pad_len = term.width - box_start_x - len(line_content)
        right_pad = " " * max(0, right_pad_len)
        return left_pad + line_content + right_pad

    # ==========================================
    # 3. BUILD THE BOX (using the pad_x helper)
    # ==========================================
    top_edge = "+" + ("─" * (box_width - 1)) + "+"
    snapshot_lines.append(pad_x(top_edge))
    
    empty_row = "|" + (" " * (box_width - 1)) + "|"
    snapshot_lines.append(pad_x(empty_row))
    
    for r in range(rows):
        is_solve_row = (r == rows - 1) 
        left_char = ">" if is_solve_row else "|"
        row_str = left_char + "   "
        
        for c in range(cols):
            row_str += cryptex_matrix[c][r] + "   "
            
        padding_needed = (box_width + 1) - len(row_str) - 1
        right_char = "<" if is_solve_row else "|"
        row_str += (" " * padding_needed) + right_char
        
        snapshot_lines.append(pad_x(row_str))

    snapshot_lines.append(pad_x(empty_row))
    snapshot_lines.append(pad_x(empty_row))
    bottom_edge = "+" + ("─" * (box_width - 1)) + "+"
    snapshot_lines.append(pad_x(bottom_edge))

    # ==========================================
    # 4. BOTTOM Y PADDING (Empty lines after the box)
    # ==========================================
    current_lines = len(snapshot_lines)
    for _ in range(term.height - current_lines):
        snapshot_lines.append(" " * term.width)

    return "\n".join(snapshot_lines)

#remote control?


#draw matrix to screen logic here:
def draw_cryptex_board(cryptex_matrix, term, active_column_index):
    #print clear screen to the terminal
    print(term.clear)


    #draw a box around my game
    
    box_width = (len(cryptex_matrix) * 4) + 12
    box_height = (len(cryptex_matrix[0])) + 4
    box_start_x = (term.width - box_width) // 2 - 20
    box_start_y = (term.height - box_height) // 2


    for current_x in range(box_start_x, box_start_x + box_width):
        print(term.move_xy(current_x, box_start_y) + term.blue("─")) #top edge

        print(term.move_xy(current_x, box_start_y + box_height) + term.blue("─")) # bottom edge
        print(term.move_xy(current_x, box_start_y + box_height - 2 ) + term.yellow("-"))

    
    for current_y in range(box_start_y, box_start_y + box_height):
        print(term.move_xy(box_start_x, current_y) + term.blue("|")) #left edge

        print(term.move_xy(box_start_x + box_width, current_y) + term.blue("|")) #right edge
    #corners
    print(term.move_xy(box_start_x,box_start_y)+ term.blue("+"))
    print(term.move_xy(box_start_x + box_width ,box_start_y)+ term.blue("+"))
    print(term.move_xy(box_start_x,box_start_y + box_height)+ term.blue("+"))
    print(term.move_xy(box_start_x + box_width ,box_start_y + box_height)+ term.blue("+"))


    solve_row_index = len(cryptex_matrix[0]) - 1
    solve_y_pos = box_start_y + 2 + solve_row_index
    
    # Overwrite the border at that exact height with red pointers!
    print(term.move_xy(box_start_x, solve_y_pos) + term.red(">"))
    print(term.move_xy(box_start_x + box_width, solve_y_pos) + term.red("<"))

    #print titel and controls in ascii art next to box
    # ==========================================
    # RIGHT UI SIDE PANEL (Title & Controls)
    # ==========================================
    
    # 1. Define your ASCII art using a "raw" string (r"") 
    # This stops Python from getting confused by the backslashes!
    title_art = r"""
      ___               _____               _           _ 
     / __|_ _ _  _ _ __|_   _|__ _ _ _ __ _(_)_ _  __ _| |
    | (__| '_| || | '_ \ | |/ -_) '_| '  \ | | ' \/ _` | |
     \___|_|  \_, | .__/ |_|\___|_| |_|_|_||_|_||_\__,_|_|
              |__/|_|                                     
    """

    # Define your controls as a simple list
    controls_text = [
        "CONTROLS:",
        "─────────",
        "[ ← ] [ → ] : Select Column",
        "[ ↑ ] [ ↓ ] : Rotate Letters",
        "[   Q   ]   : Quit Game",
        "[   E   ]   : Hint for active row"
    ]

    # 2. Calculate where the side panel goes
    # Start 6 spaces to the right of the right border
    side_panel_x = box_start_x + box_width + 6 
    
    # Start the Y coordinate at the exact same height as the top of the box
    ui_current_y = box_start_y 


    # ==========================================
    # LEFT UI PANEL (How to Play)
    # ==========================================
    
    # 1. Define your instructions
    instructions_text = [
        "HOW TO PLAY:",
        "────────────",
        "1. Read each word from ",
        "   top to bottom.",
        "",
        "2. Spin the columns using",
        "   the arrow keys.",
        "",
        "3. Align the hidden theme",
        "   word between the red",
        "   > pointers <.",
        "",
        "4. Crack the crypTerminal to",
        "   escape!"
    ]

    # 2. Calculate the Left X Coordinate
    # Start 35 spaces to the LEFT of the box's left edge
    left_panel_x = box_start_x - 35 
    
    # Push the text down a couple of rows so it aligns nicely 
    # with the middle of the game board
    left_ui_y = box_start_y + 2 

    # 3. Print the lines!
    for line in instructions_text:
        # Let's make the instructions magenta/purple to contrast the right panel!
        print(term.move_xy(left_panel_x, left_ui_y) + term.magenta(line))
        left_ui_y += 1
    # 3. Loop through the ASCII art and print it line by line
    # .strip("\n") removes the blank lines at the very top/bottom of the raw string
    # .split("\n") turns the multiline string into a list of individual lines
    for line in title_art.strip("\n").split("\n"):
        print(term.move_xy(side_panel_x, ui_current_y) + term.cyan(line))
        ui_current_y += 1

    # Add a couple of blank lines of spacing between the title and the controls
    ui_current_y += 2

    # 4. Loop through the controls and print them
    for line in controls_text:
        print(term.move_xy(side_panel_x, ui_current_y) + term.white(line))
        ui_current_y += 1



    #draw the letters
    #set the x pos for the rows (how far to the right)
    starting_x_pos = (term.width - box_width) // 2 + 4 - 20 #the minus 20 is to move everything to the left for the titel to fit on the right
                                                            # dont forget to also change the other variable that is dependant on term.width!

    for column_index, column_data in enumerate(cryptex_matrix):
        #reset the Y position for each new column so they all start at the top
        current_y_pos = box_start_y + 2
        
        # Check if the column we are about to draw is the active one!
        is_active = (column_index == active_column_index)

        # loop through each char in column x
        for char_index, char in enumerate(column_data):
            
            is_active = (column_index == active_column_index)
            is_solve_row = (char_index == solve_row_index)

            if is_active and is_solve_row:
                # Active AND Solve Row (Maybe green background, yellow text?)
                print(term.move_xy(starting_x_pos, current_y_pos) + term.reverse(term.yellow(char)))
                
            elif is_active:
                #use blessed to print active column in reverse
                print(term.move_xy(starting_x_pos, current_y_pos) + term.reverse(term.green(char)))

            elif is_solve_row:
                # Just the solve row
                print(term.move_xy(starting_x_pos, current_y_pos) + term.yellow_bold(char))

            else:
                #use blessed to teleport cursor to the desired location
                print(term.move_xy(starting_x_pos, current_y_pos) + term.green(char))

            #move one row down:
            current_y_pos += 1

        #outside the inner loop, move the cursor over to the next column. lets see how much to the right
        starting_x_pos += 4 



#Manager function:
def generate_playable_board():
    # This loop will run forever until it hits "return"
    while True:
        # 1. "try" tells Python to attempt this code
        try:
            theme_word = get_theme_word()
            unfiltered_bucket = get_thematic_bucket(theme_word)
            
            # If this function fails, it raises your ValueError!
            # The code will instantly stop and jump to the "except" block
            bucket_list = arrange_column_words(theme_word, unfiltered_bucket)
            
            # If we make it to this line, it means NO error happened!
            matrix = build_cryptex_matrix(theme_word, bucket_list)
            
            # Return the valid data (this breaks the while loop)
            return theme_word, matrix

        # 2. If a ValueError is raised, Python jumps here
        except ValueError:
            # We don't need to crash the program. We just tell the loop 
            # to "continue" back to the top and try again with a new word!
            pass 

# -----------------------------

@app.route("/")
def index():
    # Serve your index.html template from the /templates folder
    user = session.get("user")  # We will use this for LinkedIn login later!
    return render_template("index.html", user=user)

@app.route("/api/new-game", methods=["GET"])
def get_new_puzzle():
    """Provides the JS frontend with a freshly generated puzzle matrix."""
    try:
        # Utilizing your existing robust matrix-generation logic!
        theme_word, cryptex_matrix = generate_playable_board()
        return jsonify({
            "theme_word": theme_word,
            "matrix": cryptex_matrix
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Run the server locally on port 5000
    app.run(debug=True)