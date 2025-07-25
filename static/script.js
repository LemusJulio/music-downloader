document.addEventListener('DOMContentLoaded', () => {
    const urlInput = document.getElementById('url-input');
    const fetchInfoBtn = document.getElementById('fetch-info-btn');
    const infoContainer = document.getElementById('info-container');
    const infoTitle = document.getElementById('info-title');
    const songList = document.getElementById('song-list');
    const qualitySelect = document.getElementById('quality-select');
    const formatSelect = document.getElementById('format-select');
    const downloadBtn = document.getElementById('download-btn');
    const progressContainer = document.getElementById('progress-container');
    const progressBarInner = document.getElementById('progress-bar-inner');
    const progressText = document.getElementById('progress-text');
    const completedList = document.getElementById('completed-list');
    const clearHistoryBtn = document.getElementById('clear-history-btn');
    const cancelBtn = document.getElementById('cancel-btn');
    const cancelSelectionBtn = document.getElementById('cancel-selection-btn');
    const loadingIndicator = document.getElementById('loading-indicator');

    let currentUrl = '';
    let isPlaylist = false;

    urlInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            fetchInfoBtn.click();
        }
    });

    fetchInfoBtn.addEventListener('click', async () => {
        currentUrl = urlInput.value;
        if (!currentUrl) {
            alert('Please enter a URL.');
            return;
        }

        try {
            loadingIndicator.classList.remove('hidden');
            infoContainer.classList.add('hidden');

            const response = await fetch('/download_info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: currentUrl }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to fetch info.');
            }

            const data = await response.json();
            displayInfo(data);
        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            loadingIndicator.classList.add('hidden');
        }
    });

    function displayInfo(data) {
        infoTitle.textContent = data.title;
        songList.innerHTML = '';
        isPlaylist = data.type === 'playlist';

        if (isPlaylist) {
            cancelSelectionBtn.classList.remove('hidden');
            data.songs.forEach((song, index) => {
                const songItem = document.createElement('div');
                songItem.className = 'song-item';
                songItem.innerHTML = `
                    <input type="checkbox" data-index="${index}" checked>
                    <img src="${song.thumbnail}" alt="thumbnail">
                    <div class="song-details">
                        <span class="song-title">${song.title}</span>
                        <span class="song-artist">${song.artist}</span>
                    </div>
                `;
                songList.appendChild(songItem);
            });
        } else {
            const song = data.songs[0];
            const songItem = document.createElement('div');
            songItem.className = 'song-item';
            songItem.innerHTML = `
                <input type="checkbox" data-index="0" checked style="display:none;">
                <img src="${song.thumbnail}" alt="thumbnail">
                <div class="song-details">
                    <span class="song-title">${song.title}</span>
                    <span class="song-artist">${song.artist}</span>
                </div>
            `;
            songList.appendChild(songItem);
        }

        infoContainer.classList.remove('hidden');
    }

    downloadBtn.addEventListener('click', async () => {
        const selectedSongs = Array.from(songList.querySelectorAll('input[type="checkbox"]:checked'))
            .map(cb => parseInt(cb.dataset.index));

        if (selectedSongs.length === 0) {
            alert('Please select at least one song to download.');
            return;
        }

        const quality = qualitySelect.value;
        const format = formatSelect.value;

        try {
            const response = await fetch('/start_download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: currentUrl,
                    selected_songs: selectedSongs,
                    quality: quality,
                    format: format,
                }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to start download.');
            }

            progressContainer.classList.remove('hidden');
            if (isPlaylist) {
                cancelBtn.classList.remove('hidden');
            }
            listenForProgress();
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });

    function listenForProgress() {
        const eventSource = new EventSource('/progress');

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            progressBarInner.style.width = `${data.progress}%`;
            progressText.textContent = `${data.progress}%`;

            if (data.new_completed_songs) {
                data.new_completed_songs.forEach(song => {
                    const li = document.createElement('li');
                    li.innerHTML = `<img src="${song.thumbnail}" alt="thumbnail"> ${song.title}`;
                    completedList.appendChild(li);
                });
                clearHistoryBtn.classList.remove('hidden');
            }

            if (data.status === 'finished' || data.status === 'error') {
                setTimeout(() => {
                    progressContainer.classList.add('hidden');
                    cancelBtn.classList.add('hidden');
                }, 2000);
                eventSource.close();
                if (data.error) {
                    alert(`Download finished with error: ${data.error}`);
                }
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
        };
    }

    clearHistoryBtn.addEventListener('click', async () => {
        try {
            const response = await fetch('/clear_history', {
                method: 'POST',
            });
            if (response.ok) {
                completedList.innerHTML = '';
                clearHistoryBtn.classList.add('hidden');
            } else {
                alert('Failed to clear history.');
            }
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });

    cancelBtn.addEventListener('click', async () => {
        try {
            const response = await fetch('/cancel_download', {
                method: 'POST',
            });
            if (!response.ok) {
                alert('Failed to send cancel request.');
            }
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });

    cancelSelectionBtn.addEventListener('click', () => {
        infoContainer.classList.add('hidden');
        songList.innerHTML = '';
        infoTitle.textContent = '';
        urlInput.value = '';
        cancelSelectionBtn.classList.add('hidden');
    });
});
