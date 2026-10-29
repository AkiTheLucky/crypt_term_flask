let activeColumnIndex = 0;
let isHintOnCooldown = false;
const COOLDOWN_SECONDS = 5;
let isGameWon = false;
const puzzleDateInput = document.getElementById('current-puzzle-date');
const puzzleDate = puzzleDateInput ? puzzleDateInput.value : 'unknown_date';

// Columns that have been revealed with the hint button, so the shared result
// can show how much of the puzzle was actually worked out.
const hintedColumns = new Set();
let shareText = '';

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

function spinColumn(direction, silent = false) {
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

    // 🚀 Check the word automatically after every player spin.
    // The hint routine passes silent = true so a single hint doesn't fire a
    // request for every intermediate rotation.
    if (!silent) {
        checkWordAutomatically();
    }
}

function initTargetWindows() {
    document.querySelectorAll('.column').forEach((columnEl) => {
        const track = columnEl.querySelector('.column-track');
        const targetCell = track.querySelector('.letter-cell.target-row');
        if (!targetCell) return;

        const windowEl = document.createElement('div');
        windowEl.className = 'target-window';
        
        // Grab the exact dimensions of the target cell
        const rect = targetCell.getBoundingClientRect();
        
        // 1. Make it 10% smaller (multiply by 0.9)
        const newHeight = rect.height * 0.95;
        const newWidth = rect.width * 0.95;
        
        // 2. Set your offsets in pixels (tweak these numbers to get it perfect)
        const offsetRight = 4; 
        const offsetBottom = 4; 

        // 3. Apply the new sizes
        windowEl.style.height = `${newHeight}px`;
        windowEl.style.width = `${newWidth}px`; 
        
        // 4. Apply the offsets
        windowEl.style.top = `${targetCell.offsetTop + offsetBottom}px`;
        windowEl.style.left = `${targetCell.offsetLeft + offsetRight}px`;

        columnEl.insertBefore(windowEl, track);
    });
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

    hintedColumns.add(activeColumnIndex);

    // 3. Spin until the target letter lands in the target row.
    //    Silent spins: the column rotates several times, but we only ask the
    //    server once, after the letter has actually arrived.
    let targetCell = activeColumn.querySelector('.letter-cell.target-row');
    let safetyCounter = 0; // Prevents infinite loops just in case

    while (targetCell.textContent.trim() !== targetLetter && safetyCounter < 15) {
        spinColumn('up', true);
        targetCell = activeColumn.querySelector('.letter-cell.target-row');
        safetyCounter++;
    }

    checkWordAutomatically();

    // 4. Start the cooldown timer
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
    if (isGameWon) return; // Already solved (e.g. a duplicated validate response)

    // 1. Calculate the final time
    const elapsedMillis = Date.now() - startTime;
    const totalSeconds = Math.floor(elapsedMillis / 1000);
    const formattedTime = formatTime(totalSeconds);

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

    // 3. Move the reveal (theme word + column words) from /validate into the modal
    const revealSource = document.getElementById('win-reveal');
    const revealTarget = document.getElementById('modal-reveal');
    if (revealSource && revealTarget) {
        revealTarget.innerHTML = revealSource.innerHTML;
    }

    const themeEl = document.querySelector('#modal-reveal .reveal-theme');
    const solvedWord = themeEl ? themeEl.textContent.trim() : '';

    // 4. Lock the game
    isGameWon = true;

    // 👇 WRITE TO MEMORY: Save the win permanently in the browser!
    localStorage.setItem(winStorageKey, 'true');

    const streak = updateStreak(puzzleDate);
    const streakLine = document.getElementById('streak-line');
    const streakCount = document.getElementById('streak-count');
    if (streakLine && streakCount) {
        streakCount.textContent = streak;
        streakLine.hidden = streak < 2;
    }

    shareText = buildShareText(solvedWord, formattedTime, streak);

    // 5. Disable the hint button
    const hintBtn = document.getElementById('hint-btn');
    if (hintBtn) hintBtn.disabled = true;

    // 6. Fire the triple confetti burst (skipped when motion is reduced)
    const wantsMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches === false;

    if (wantsMotion && typeof confetti !== 'undefined') {
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
    // 7. Open the Score Modal (Wait 3.5 seconds so they can see the confetti first!)
    setTimeout(() => {
        const modal = document.getElementById('score-modal');
        if (modal) modal.setAttribute('open', 'true');
    }, 3500);
}

function formatTime(totalSeconds) {
    const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
    const seconds = String(totalSeconds % 60).padStart(2, '0');
    return `${minutes}:${seconds}`;
}

// Streak bookkeeping, kept entirely in the browser (no login needed).
function updateStreak(todayStr) {
    const STREAK_KEY = 'crypTerm_streak';
    let state = { last: null, count: 0 };

    try {
        const raw = localStorage.getItem(STREAK_KEY);
        if (raw) state = JSON.parse(raw) || state;
    } catch (err) {
        state = { last: null, count: 0 };
    }

    if (state.last === todayStr) return state.count || 1;

    const previousDay = new Date(`${todayStr}T00:00:00Z`);
    previousDay.setUTCDate(previousDay.getUTCDate() - 1);
    const yesterdayStr = previousDay.toISOString().slice(0, 10);

    const count = state.last === yesterdayStr ? (state.count || 0) + 1 : 1;
    localStorage.setItem(STREAK_KEY, JSON.stringify({ last: todayStr, count }));
    return count;
}

function buildShareText(solvedWord, formattedTime, streak) {
    const columnCount = document.querySelectorAll('.column').length;
    let grid = '';
    for (let i = 0; i < columnCount; i++) {
        grid += hintedColumns.has(i) ? '🟨' : '🟩';
    }

    const lines = [`crypTerm ${puzzleDate}`, grid];

    if (solvedWord) {
        lines.push(`Solved ${solvedWord} in ${formattedTime}`);
    } else {
        lines.push(`Solved in ${formattedTime}`);
    }

    if (streak > 1) lines.push(`🔥 ${streak} day streak`);
    lines.push(window.location.origin);

    return lines.join('\n');
}

async function shareResult() {
    const feedback = document.getElementById('share-feedback');
    if (!shareText) return;

    let copied = false;

    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(shareText);
            copied = true;
        } catch (err) {
            // Permission denied or no transient activation - fall through.
            copied = false;
        }
    }

    if (!copied) {
        try {
            copied = copyWithFallback(shareText);
        } catch (err) {
            copied = false;
        }
    }

    if (feedback) {
        feedback.textContent = copied
            ? 'Copied to clipboard'
            : 'Copy failed - select the text manually';
    }
}

function copyWithFallback(text) {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(area);
    return copied;
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
// touch controls (drag-to-scroll, infinite wraparound reveal)
function initDragControls() {
    document.querySelectorAll('.column').forEach((columnEl, colIndex) => {
        const track = columnEl.querySelector('.column-track');
        const firstCell = track.querySelector('.letter-cell');
        const cellHeight = firstCell.getBoundingClientRect().height;

        let dragStartY = 0;
        let dragging = false;

        columnEl.addEventListener('touchstart', (e) => {
            if (isGameWon) return;
            dragging = true;
            dragStartY = e.touches[0].screenY;

            if (colIndex !== activeColumnIndex) {
                document.querySelectorAll('.column')[activeColumnIndex].classList.remove('active');
                activeColumnIndex = colIndex;
                columnEl.classList.add('active');
            }
        }, { passive: true });

        columnEl.addEventListener('touchmove', (e) => {
            if (!dragging) return;
            e.preventDefault();

            let delta = e.touches[0].screenY - dragStartY;
            
            // CLAMP REMOVED: Allow the track to translate as far as the user drags
            track.style.transform = `translateY(${delta}px)`;
        }, { passive: false });

        columnEl.addEventListener('touchend', (e) => {
            if (!dragging) return;
            dragging = false;

            const delta = e.changedTouches[0].screenY - dragStartY;
            const steps = Math.round(delta / cellHeight); // Can now be any number!

            track.style.transform = 'translateY(0px)'; // snap back instantly

            // Run the spin algorithm X times based on how many steps were dragged
            if (steps > 0) {
                for (let i = 0; i < steps; i++) {
                    spinColumn('down');
                }
            } else if (steps < 0) {
                for (let i = 0; i < Math.abs(steps); i++) {
                    spinColumn('up');
                }
            }
        });
    });
}

window.addEventListener('DOMContentLoaded', initDragControls);
window.addEventListener('DOMContentLoaded', initTargetWindows);