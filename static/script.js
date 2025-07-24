document.addEventListener('DOMContentLoaded', () => {
    const urlInput = document.getElementById('url-input');
    const fetchInfoBtn = document.getElementById('fetch-info-btn');
    const downloadBtn = document.getElementById('download-btn');
    const infoContainer = document.getElementById('info-container');
    const infoTitle = document.getElementById('info-title');
    const songList = document.getElementById('song-list');
    const qualitySelect = document.getElementById('quality-select');
    const progressContainer = document.getElementById('progress-container');
    const progressBarInner = document.getElementById('progress-bar-inner');
    const completedList = document.getElementById('completed-list');
    const clearHistoryBtn = document.getElementById('clear-history-btn');

    let currentUrl = '';
    let songs = [];

    // Combined button for fetching and downloading single videos
    fetchInfoBtn.addEventListener('click', async () => {
        currentUrl = urlInput.value;
        if (!currentUrl) {
            alert('Please enter a URL.');
            return;
        }

        try {
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
            songs = data.songs;

            if (data.type === 'playlist') {
                displayInfo(data);
            } else {
                // If it's a single video, download it directly
                startDownload([0]);
            }
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });

    function displayInfo(data) {
        infoTitle.textContent = data.title;
        songList.innerHTML = '';

        songs.forEach((song, index) => {
            const songItem = document.createElement('div');
            songItem.className = 'group relative p-6 bg-black border border-gray-800 rounded-xl hover:border-transparent hover:bg-gradient-to-r hover:from-purple-500/10 hover:to-pink-500/10 transition-all duration-300';
            songItem.innerHTML = `
                <div class="absolute inset-0 rounded-xl border-2 border-transparent bg-gradient-to-r from-purple-500 to-pink-500 p-[1px] opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                    <div class="bg-black rounded-xl h-full w-full"></div>
                </div>
                <div class="relative flex items-center gap-6">
                    <input type="checkbox" data-index="${index}" class="form-checkbox h-5 w-5 text-green-500 bg-gray-800 border-gray-700 rounded focus:ring-green-500" checked>
                    <img src="${song.thumbnail}" alt="${song.title} thumbnail" class="w-16 h-16 rounded-xl object-cover border-2 border-gray-700 group-hover:border-purple-500 transition-colors duration-300">
                    <div class="flex-1 min-w-0">
                        <h3 class="text-white font-medium text-lg mb-2 truncate group-hover:text-transparent group-hover:bg-gradient-to-r group-hover:from-cyan-400 group-hover:to-purple-500 group-hover:bg-clip-text transition-all duration-300">${song.title}</h3>
                        <div class="flex items-center gap-6 text-gray-400">
                            <span class="flex items-center gap-2">
                                <div class="w-2 h-2 rounded-full bg-blue-500"></div>
                                ${song.artist}
                            </span>
                        </div>
                    </div>
                </div>
            `;
            songList.appendChild(songItem);
        });

        infoContainer.classList.remove('hidden');
    }

    downloadBtn.addEventListener('click', () => {
        const selectedSongsIndices = Array.from(songList.querySelectorAll('input[type="checkbox"]:checked'))
            .map(cb => parseInt(cb.dataset.index));

        if (selectedSongsIndices.length === 0) {
            alert('Please select at least one song to download.');
            return;
        }
        startDownload(selectedSongsIndices);
    });

    async function startDownload(indices) {
        const quality = qualitySelect.value;

        try {
            const response = await fetch('/start_download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: currentUrl,
                    selected_songs: indices,
                    quality: quality,
                    format: 'mp3',
                }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to start download.');
            }

            progressContainer.classList.remove('hidden');
            listenForProgress();
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    function listenForProgress() {
        const eventSource = new EventSource('/progress');

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            progressBarInner.style.width = `${data.progress}%`;

            if (data.new_completed_songs) {
                data.new_completed_songs.forEach(song => {
                    const li = document.createElement('div');
                    li.className = 'group relative p-6 bg-black border border-gray-800 rounded-xl';
                    li.innerHTML = `
                        <div class="relative flex items-center gap-6">
                            <img src="${song.thumbnail}" alt="${song.title} thumbnail" class="w-16 h-16 rounded-xl object-cover border-2 border-gray-700">
                            <div class="flex-1 min-w-0">
                                <h3 class="text-white font-medium text-lg mb-2 truncate">${song.title}</h3>
                                <div class="flex items-center gap-6 text-gray-400">
                                    <span class="flex items-center gap-2">
                                        <div class="w-2 h-2 rounded-full bg-green-500"></div>
                                        Completed
                                    </span>
                                </div>
                            </div>
                        </div>
                    `;
                    completedList.prepend(li);
                });
            }

            if (data.status === 'finished' || data.status === 'error') {
                eventSource.close();
                progressContainer.classList.add('hidden');
                if (data.error) {
                    alert(`Download finished with error: ${data.error}`);
                }
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
        };
    }

    clearHistoryBtn.addEventListener('click', () => {
        completedList.innerHTML = '';
    });
});
