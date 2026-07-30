# crypTerm

A mobile-friendly, terminal-styled daily word puzzle game built with Flask, HTMX, and Pico.css.

![crypTerm Screenshot](./static/tutorial_image.png)

## How to Play

- Each vertical column contains letters. They all relate to the code word in some way.
- Swipe or use the D-Pad controls to shift columns up and down.
- Align the hidden horizontal target word inside the active center row.
- Use the **Hint** button if you get stuck!

## Tech Stack

- **Backend:** Python / Flask , Datamuse API
- **Frontend:** HTMX, Pico.css, Vanilla JavaScript
- **Animations:** Canvas Confetti

## how it works
- the datamuse API gets called to provide a random word from the english dictionary that is between 4-8 letters long.
- i take the response and get more datamuse API calls that use the selected word to find auxilary words
- once i have a longlist, i start a check where i try to make one letter of the theme_word_bucket fit with each letter of the theme word. 
- if that fails, call the datamuse API again and try a new word
- rank words by popularity and fit (dont take random words that have barely any correlation, or common knowledge) to make the puzzle fun.
- if all goes well, split the word into a list of list with each item being a single letter.
- JS and CSS and HTMX to make the game playable in the browser
- every time the user spins a column, there is a request being sent:
    - "does this word match the hidden word?"
    - if yes, start confetti animation
    - if no, do nothing
- keep sending responses until the player solves it.

- if the player presses the hint button, call the column rotation function until the letter at this position matches the correct one
- put hint on cooldown

- store everything in a postgreSQL for persistance (like leaderboard and daily puzzle) 


##  Running Locally

1. Clone the repository:
2. git clone [https://github.com/AkiTheLucky/crypt_term_flask.git](https://github.com/AkiTheLucky/crypt_term_flask.git)
3. cd crypt_term_flask
4. python3 app.py
5. open in browser