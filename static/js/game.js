let activeColumnIndex = 0;

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
        // Shift letters up: first item moves to the end
        letters.push(letters.shift());
    } else if (direction === 'down') {
        // Shift letters down: last item moves to the beginning
        letters.unshift(letters.pop());
    }

    // Re-render letters back into the DOM cells
    cells.forEach((cell, index) => {
        cell.textContent = letters[index] || " ";
    });
    
}

function checkUnlock() {
    // Collect the letters currently sitting in the target row
    const targetCells = document.querySelectorAll('.letter-cell.target-row');
    let alignedWord = "";
    targetCells.forEach(cell => alignedWord += cell.textContent.trim());

    alert("Current Aligned Word: " + alignedWord);
}

// Listen for physical keyboard inputs
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
            checkUnlock();
            break;
    }
});