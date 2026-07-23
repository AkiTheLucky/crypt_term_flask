from flask import Flask, render_template, request, Response 


SECRET_WORD = "ONCE"

app = Flask(__name__)

@app.route("/")
def index():
    # Mock puzzle data for testing Phase 1
    # Each inner list represents a vertical column of letters
    mock_columns = [
        ["S", "O", "M", "E", "T", "I", "M", "E", " "],
        ["W", "H", "E", "N", " ", " ", " ", " ", " "],
        ["B", "E", "C", "A", "U", "S", "E", " ", " "],
        ["F", "O", "R", "M", "E", "R", "L", "Y", " "]
    ]
    
    # Target row index (e.g., index 1 is where the pointers '> <' lock)
    pointer_index = len(mock_columns[0])-1

    return render_template("index.html", columns=mock_columns, pointer_index=pointer_index)


@app.route("/validate", methods=["POST"])
def validate():
    # Grab the current word sent from the frontend
    user_word = request.form.get("word", "").upper()
    
    if user_word == SECRET_WORD:
        # Return victory HTML snippet to be swapped into #game-status
        return """
        <div class="win-banner">
            <h2>ACCESS GRANTED</h2>
            <p>Vault cracked!</p>
        </div>
        """
    
    # If incorrect, return 204 (No Content) so HTMX does nothing
    return Response(status=204)


if __name__ == "__main__":
    app.run(debug=True)