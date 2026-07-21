let matrixData = []; 
let currentColumnIndex = 0; 
let columnIndexes = []; // Tracks which letter index is currently in the solve row
let targetWord = ""; 
let isGameOver = false;

document.getElementById('new-game-btn').addEventListener('click', async () => {
    const response = await fetch('/api/new-game');
    const data = await response.json();
    
    matrixData = data.matrix;
    targetWord = data.theme_word.toUpperCase();
    currentColumnIndex = 0; 
    isGameOver = false;
    
    // Start every column with the first letter (index 0) in the solve row
    columnIndexes = new Array(matrixData.length).fill(0);
    
    // Reset UI
    document.getElementById('hint-btn').style.display = 'inline-block';
    document.getElementById('hint-text').innerText = "";
    
    renderBoard();
});

// The Hint Button Logic
document.getElementById('hint-btn').addEventListener('click', () => {
    // Reveal the first letter of the target word, and the length
    const hintText = `Hint: The word starts with "${targetWord[0]}" and is ${targetWord.length} letters long.`;
    document.getElementById('hint-text').innerText = hintText;
});

function renderBoard() {
    const board = document.getElementById('game-board');
    board.innerHTML = ''; 
    
    matrixData.forEach((column, colIdx) => {
        const colDiv = document.createElement('div');
        colDiv.className = 'column-wheel-wrapper';
        
        if (colIdx === currentColumnIndex && !isGameOver) {
            colDiv.classList.add('active');
        }
        
        // Shift the column visually based on which letter index is targeted
        const offsetPx = -(columnIndexes[colIdx] * 50); 
        
        let columnHTML = `<div class="letter-window">
                            <div class="letter-strip" style="transform: translateY(${offsetPx}px);">`;
        
        column.forEach((letter) => {
            columnHTML += `<div class="letter-cell">${letter}</div>`;
        });
        
        columnHTML += `</div></div>`;
        colDiv.innerHTML = columnHTML;
        board.appendChild(colDiv);
    });

    checkWinCondition();
}

function checkWinCondition() {
    if (isGameOver || !matrixData.length) return;

    // Build the word currently sitting in the solve row
    let currentGuess = "";
    for (let i = 0; i < matrixData.length; i++) {
        currentGuess += matrixData[i][columnIndexes[i]];
    }

    if (currentGuess === targetWord) {
        isGameOver = true;
        document.getElementById('hint-text').innerText = "YOU CRACKED THE CRYPTEX!";
        
        // Trigger the burn animation on all letters in the solve row!
        const letterStrips = document.querySelectorAll('.letter-strip');
        letterStrips.forEach((strip, index) => {
            // Find the specific letter cell sitting in the solve row
            const winningCell = strip.children[columnIndexes[index]];
            winningCell.classList.add('burn-effect');
        });
    }
}

document.addEventListener('keydown', (e) => {
    if (!matrixData.length || isGameOver) return; 

    const currentColumnLength = matrixData[currentColumnIndex].length;

    if (e.key === 'ArrowLeft') {
        currentColumnIndex = (currentColumnIndex - 1 + matrixData.length) % matrixData.length;
        renderBoard();
    } 
    else if (e.key === 'ArrowRight') {
        currentColumnIndex = (currentColumnIndex + 1) % matrixData.length;
        renderBoard();
    } 
    else if (e.key === 'ArrowUp') {
        // Slide column UP (moves target letter down the list)
        if (columnIndexes[currentColumnIndex] < currentColumnLength - 1) {
            columnIndexes[currentColumnIndex] += 1;
            renderBoard();
        }
    } 
    else if (e.key === 'ArrowDown') {
        // Slide column DOWN (moves target letter up the list)
        if (columnIndexes[currentColumnIndex] > 0) {
            columnIndexes[currentColumnIndex] -= 1;
            renderBoard();
        }
    }
});