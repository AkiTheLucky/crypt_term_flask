let activeColumnIndex = 0;
let isHintOnCooldown = false;
const COOLDOWN_SECONDS = 5;


function selectColumn(direction) {
    const columns = document.querySelectorAll('.column');
    columns[activeColumnIndex].classList.remove('active');

    if (direction === 'left') {
        activeColumnIndex = (activeColumnIndex - 1 + columns.length) % columns.length;
    } else if (direction === 'right') {
        activeColumnIndex = (activeColumnIndex + 1) % columns.length;
    }

    columns[activeColumnIndex].classList.add('active');
}

function spinColumn(direction) {
    const activeColumn = document.querySelectorAll('.column')[activeColumnIndex];
    const cells = Array.from(activeColumn.querySelectorAll('.letter-cell'));
    
    // Extract current letters in this column
    const letters = cells.map(cell => cell.textContent.trim());

    if (direction === 'up') {
        letters.push(letters.shift());
    } else if (direction === 'down') {
        letters.unshift(letters.pop());
    }

    // Re-render letters back into the DOM cells
    cells.forEach((cell, index) => {
        cell.textContent = letters[index] || " ";
    });

    // 🚀 Check the word automatically after every spin!
    checkWordAutomatically();
}

function checkWordAutomatically() {
    // Collect the letters currently sitting in the target row
    const targetCells = document.querySelectorAll('.letter-cell.target-row');
    let currentWord = "";
    targetCells.forEach(cell => currentWord += cell.textContent.trim());

    // Fire a silent background check to Flask via HTMX
    if (typeof htmx !== 'undefined') {
        htmx.ajax('POST', '/validate', {
            values: { word: currentWord },
            target: '#game-status',
            swap: 'innerHTML'
        });
    }
}


function revealHint() {
    // 1. Guard check: do nothing if on cooldown
    if (isHintOnCooldown) return;

    // 2. Get the target letter for the currently active column
    const activeColumn = document.querySelectorAll('.column')[activeColumnIndex];
    const targetLetter = activeColumn.dataset.targetLetter;

    if (!targetLetter) return;

    // 3. Spin until the target letter lands in the target row
    let targetCell = activeColumn.querySelector('.letter-cell.target-row');
    let safetyCounter = 0; // Prevents infinite loops just in case

    while (targetCell.textContent.trim() !== targetLetter && safetyCounter < 15) {
        spinColumn('up'); // Re-uses your existing spin algorithm!
        targetCell = activeColumn.querySelector('.letter-cell.target-row');
        safetyCounter++;
    }

    // 4. Start the 3-second countdown timer
    startHintCooldown();
}

function startHintCooldown() {
    isHintOnCooldown = true;
    const hintBtn = document.getElementById('hint-btn');
    let timeRemaining = COOLDOWN_SECONDS;

    if (hintBtn) {
        hintBtn.disabled = true;
        hintBtn.textContent = `Cooldown (${timeRemaining}s)...`;

        const timer = setInterval(() => {
            timeRemaining--;
            if (timeRemaining > 0) {
                hintBtn.textContent = `Cooldown (${timeRemaining}s)...`;
            } else {
                clearInterval(timer);
                hintBtn.disabled = false;
                hintBtn.textContent = "Hint";
                isHintOnCooldown = false;
            }
        }, 1000);
    }
}

// 5. Update keyboard controls to support 'E' / 'e' for hints
document.addEventListener('keydown', (event) => {
    switch (event.key) {
        case 'ArrowLeft':
            selectColumn('left');
            break;
        case 'ArrowRight':
            selectColumn('right');
            break;
        case 'ArrowUp':
            spinColumn('up');
            break;
        case 'ArrowDown':
            spinColumn('down');
            break;
        case 'Enter':
            checkWordAutomatically();
            break;
        case 'e':
        case 'E':
            revealHint();
            break;
    }
});