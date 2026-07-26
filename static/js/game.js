let activeColumnIndex = 0;
let isHintOnCooldown = false;
const COOLDOWN_SECONDS = 5;
let isGameWon = false;
const puzzleDateInput = document.getElementById('current-puzzle-date');
const puzzleDate = puzzleDateInput ? puzzleDateInput.value : 'unknown_date';

// We create a unique key for today (e.g., "crypTerm_won_2026-07-25")
const winStorageKey = `crypTerm_won_${puzzleDate}`;

// 2. CHECK MEMORY ON LOAD: Did they already win this puzzle?
if (localStorage.getItem(winStorageKey) === 'true') {
    isGameWon = true; // Instantly lock the game!
    
    // Wait for the HTML to load, then update the UI
    window.addEventListener('DOMContentLoaded', () => {
        const hintBtn = document.getElementById('hint-btn');
        if (hintBtn) hintBtn.disabled = true;
        
        const timerDisplay = document.getElementById('timer-display');
        if (timerDisplay) {
            timerDisplay.textContent = "SOLVED";
            timerDisplay.style.color = "var(--pico-ins-color)"; // Make it green!
        }
    });
}

function selectColumn(direction) {
    if (isGameWon) return; // 🛑 Stop if won
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
    if (isGameWon) return; // 🛑 Stop if won
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
    if (isGameWon || isHintOnCooldown) return; // 🛑 Stop if won or on cooldown
    

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



function triggerWin() {
    console.log("Victory triggered!"); // Helps us debug in the browser console
    
    // 1. Calculate the final time
    const elapsedMillis = Date.now() - startTime;
    const totalSeconds = Math.floor(elapsedMillis / 1000);

    const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
    const seconds = String(totalSeconds % 60).padStart(2, '0');
    const formattedTime = `${minutes}:${seconds}`;

    // 2. Inject that time into our HTML Modal safely
    const hiddenTimeInput = document.getElementById('hidden-time');
    const modalTimeDisplay = document.getElementById('modal-time-display');

    if (hiddenTimeInput && modalTimeDisplay) {
        // Force the value as a string so HTMX reads it properly
        hiddenTimeInput.value = totalSeconds.toString();
        modalTimeDisplay.textContent = formattedTime;
    } else {
        console.error("Missing modal elements in HTML!");
    }


    // 1. Lock the game
    isGameWon = true;
    
    // 👇 WRITE TO MEMORY: Save the win permanently in the browser!
    localStorage.setItem(winStorageKey, 'true');

    // 2. Disable the hint button
    const hintBtn = document.getElementById('hint-btn');
    if (hintBtn) hintBtn.disabled = true;

    // 3. Fire the triple confetti burst!
    if (typeof confetti !== 'undefined') {
        const fireConfetti = () => {

            const randomX = Math.random() * 0.6 + 0.2; 
            const randomY = Math.random() * 0.4 + 0.3;


            confetti({
                particleCount: 150,
                spread: 80,
                origin: { x: randomX, y: randomY },
                colors: ['#00fa9a', '#ffffff', '#ff007f']
            });
        };

        fireConfetti(); // 1st shot (Immediate)
        setTimeout(fireConfetti, 300); // 2nd shot (0.3s delay)
        setTimeout(fireConfetti, 600); // 3rd shot (0.6s delay)

    } 
    // 4. Open the Score Modal (Wait 1.5 seconds so they can see the confetti first!)
    setTimeout(() => {
        const modal = document.getElementById('score-modal');
        if (modal) modal.setAttribute('open', 'true');
    }, 3500);
}

// Timer State
const startTime = Date.now();
let timerInterval;

function startTimer() {
    const timerDisplay = document.getElementById('timer-display');
    if (!timerDisplay) return;

    timerInterval = setInterval(() => {
        // If they win, stop the clock!
        if (isGameWon) {
            clearInterval(timerInterval);
            return;
        }
        
        // Calculate elapsed time
        const elapsedMillis = Date.now() - startTime;
        const totalSeconds = Math.floor(elapsedMillis / 1000);
        
        // Format into MM:SS (e.g., 03:05)
        const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
        const seconds = String(totalSeconds % 60).padStart(2, '0');
        
        timerDisplay.textContent = `${minutes}:${seconds}`;
    }, 1000); // Ticks every 1000ms (1 second)
}

// Start the timer the exact moment the Javascript loads
startTimer();


// touch controls

let touchStartY = 0;
let touchEndY = 0;
// touch controls
const SWIPE_THRESHOLD = 30; // minimum px movement to count as a swipe

document.querySelectorAll('.column').forEach((columnEl, index) => {
    let touchStartY = 0;

    columnEl.addEventListener('touchstart', (e) => {
        touchStartY = e.changedTouches[0].screenY;
    }, { passive: true });

    columnEl.addEventListener('touchmove', (e) => {
        // Stop the page from scrolling/bouncing while swiping a column
        e.preventDefault();
    }, { passive: false });

    columnEl.addEventListener('touchend', (e) => {
        if (isGameWon) return;

        const touchEndY = e.changedTouches[0].screenY;
        const deltaY = touchEndY - touchStartY;

        if (Math.abs(deltaY) < SWIPE_THRESHOLD) return; // ignore small taps/jitter

        // Make sure the swiped column becomes the active one
        if (index !== activeColumnIndex) {
            document.querySelectorAll('.column')[activeColumnIndex].classList.remove('active');
            activeColumnIndex = index;
            columnEl.classList.add('active');
        }

        if (deltaY < 0) {
            spinColumn('up');   // swiped up
        } else {
            spinColumn('down'); // swiped down
        }
    });
});