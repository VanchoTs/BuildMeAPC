document.addEventListener('DOMContentLoaded', async () => {
    const API_URL = `http://${window.location.hostname}:5075/api/news`;
    const AUTH_API = `http://${window.location.hostname}:5075/api/auth`;
    
    const newsContainer = document.getElementById('news-container');
    const toggleBtn = document.getElementById('toggle-news-btn');
    const newsForm = document.getElementById('create-news-form');
    const cancelBtn = document.getElementById('cancel-news-btn');
    const searchInput = document.getElementById('news-search');
    const searchBtn = document.getElementById('news-search-btn');

    // Single article view elements
    const singleArticleView = document.getElementById('single-article-view');
    const singleArticleContent = document.getElementById('single-article-content');
    const backToNewsBtn = document.getElementById('back-to-news-btn');

    let allArticles = [];

    // Check user role via API
    let currentUser = null;
    try {
        const response = await fetch(`${AUTH_API}/me`, {
            credentials: 'include'
        });
        if (response.ok) {
            currentUser = await response.json();
        }
    } catch (e) {
        console.error('Session verification failed', e);
    }
    
    let isAuthorized = false;
    if (currentUser && (currentUser.role === 'admin' || currentUser.role === 'writer')) {
        isAuthorized = true;
        if (toggleBtn) toggleBtn.style.display = 'block';
    }

    // Search Logic
    if (searchBtn && searchInput) {
        searchBtn.addEventListener('click', () => loadNews(searchInput.value));
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadNews(searchInput.value);
        });
    }

    // Form toggling
    if (toggleBtn && newsForm && cancelBtn) {
        toggleBtn.addEventListener('click', () => {
            newsForm.classList.add('active');
            toggleBtn.style.display = 'none';
        });

        cancelBtn.addEventListener('click', () => {
            newsForm.classList.remove('active');
            newsForm.reset();
            toggleBtn.style.display = 'block';
        });

        // Form submission
        newsForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const titleInput = document.getElementById('news-title');
            const imageInput = document.getElementById('news-image');
            const catchPhraseInput = document.getElementById('news-catch-phrase');
            const contentInput = document.getElementById('news-content');
            
            const newArticle = {
                title: titleInput.value,
                imageUrl: imageInput.value,
                catchPhrase: catchPhraseInput.value,
                content: contentInput.value
            };

            try {
                const response = await fetch(API_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    credentials: 'include',
                    body: JSON.stringify(newArticle)
                });

                if (response.ok) {
                    alert('Article published successfully!');
                    newsForm.reset();
                    newsForm.classList.remove('active');
                    toggleBtn.style.display = 'block';
                    loadNews(); // Refresh the list
                } else {
                    const errText = await response.text();
                    alert(`Failed to publish article: ${errText}`);
                }
            } catch (err) {
                console.error('Error publishing article:', err);
                alert('Could not connect to the server to publish the article.');
            }
        });
    }

    if (backToNewsBtn) {
        backToNewsBtn.addEventListener('click', () => {
            if (singleArticleView && newsContainer) {
                singleArticleView.style.display = 'none';
                newsContainer.style.display = 'grid'; // Restore grid
                if (isAuthorized && toggleBtn && !newsForm.classList.contains('active')) {
                    toggleBtn.style.display = 'block';
                }
            }
        });
    }

    // Load news on page load
    loadNews();

    async function loadNews(search = '') {
        if (!newsContainer) return;
        newsContainer.innerHTML = '<p>Loading news...</p>';
        
        try {
            const url = search ? `${API_URL}?search=${encodeURIComponent(search)}` : API_URL;
            const response = await fetch(url);
            if (response.ok) {
                allArticles = await response.json();
                renderNewsGrid(allArticles);
            } else {
                newsContainer.innerHTML = '<p>Failed to load news.</p>';
            }
        } catch (err) {
            console.error('Error fetching news:', err);
            newsContainer.innerHTML = '<p>Could not connect to the server to load news.</p>';
        }
    }

    function renderNewsGrid(news) {
        if (!newsContainer) return;
        newsContainer.innerHTML = '';

        if (news.length === 0) {
            newsContainer.innerHTML = '<p>No news articles found.</p>';
            return;
        }

        const icons = ['🚀', '💾', '🌡️', '💡', '💻', '⚡'];

        news.forEach((article, index) => {
            const dateStr = new Date(article.createdAt).toLocaleDateString(undefined, {
                year: 'numeric', month: 'long', day: 'numeric'
            });

            const articleEl = document.createElement('article');
            articleEl.className = 'news-card';
            
            let imageContent = '';
            if (article.imageUrl && article.imageUrl.trim() !== '') {
                imageContent = `<div class="news-image" style="background-image: url('${article.imageUrl}'); background-size: cover; background-position: center;"></div>`;
            } else {
                const icon = icons[index % icons.length];
                imageContent = `<div class="news-image" aria-hidden="true">${icon}</div>`;
            }

            let adminActions = '';
            if (isAuthorized) {
                adminActions = `<button class="btn btn-outline delete-news-btn" data-id="${article.id}" style="font-size: 0.8rem; color: var(--danger-color); border-color: var(--danger-color); margin-left: 0.5rem;">Delete</button>`;
            }

            let displayCatchPhrase = article.catchPhrase;
            if (!displayCatchPhrase || displayCatchPhrase.trim() === '') {
                const content = article.content || '';
                const dotIndex = content.indexOf('.');
                if (dotIndex > 0 && dotIndex < 100) {
                    displayCatchPhrase = content.substring(0, dotIndex + 1);
                } else {
                    displayCatchPhrase = content.length > 100 ? content.substring(0, 97) + '...' : content;
                }
            }

            articleEl.innerHTML = `
                ${imageContent}
                <div class="news-content">
                    <div class="news-date">${dateStr} <span data-i18n="by_author">• By </span> <strong style="color: var(--accent-color);">${article.authorName}</strong></div>
                    <h2>${article.title}</h2>
                    <p style="white-space: pre-wrap; font-size: 0.95rem; color: var(--text-primary);">${displayCatchPhrase}</p>
                    <div style="display: flex; align-items: center; margin-top: 1rem;">
                        <button class="btn btn-outline read-more-btn" data-id="${article.id}" style="font-size: 0.8rem;">Read More</button>
                        ${adminActions}
                    </div>
                </div>
            `;
            newsContainer.appendChild(articleEl);
        });

        // Attach Read More listeners
        const readMoreBtns = newsContainer.querySelectorAll('.read-more-btn');
        readMoreBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = parseInt(e.target.getAttribute('data-id') || '0', 10);
                const selectedArticle = allArticles.find(a => a.id === id);
                if (selectedArticle) {
                    showSingleArticle(selectedArticle);
                }
            });
        });

        // Attach Delete listeners
        const deleteBtns = newsContainer.querySelectorAll('.delete-news-btn');
        deleteBtns.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = parseInt(e.target.getAttribute('data-id') || '0', 10);
                if (confirm('Are you sure you want to delete this article?')) {
                    try {
                        const token = localStorage.getItem('authToken');
                        const response = await fetch(`${API_URL}/${id}`, {
                            method: 'DELETE',
                            headers: {
                                'Authorization': `Bearer ${token}`
                            },
                            credentials: 'include'
                        });
                        if (response.ok) {
                            alert('Article deleted successfully.');
                            loadNews();
                        } else {
                            const err = await response.text();
                            alert(`Failed to delete article: ${err}`);
                        }
                    } catch (err) {
                        console.error('Error deleting article:', err);
                        alert('Could not connect to the server to delete the article.');
                    }
                }
            });
        });
    }

    function showSingleArticle(article) {
        if (!singleArticleView || !singleArticleContent || !newsContainer) return;

        const dateStr = new Date(article.createdAt).toLocaleDateString(undefined, {
            year: 'numeric', month: 'long', day: 'numeric'
        });

        let imageHtml = '';
        if (article.imageUrl && article.imageUrl.trim() !== '') {
            imageHtml = `<img src="${article.imageUrl}" alt="${article.title}" style="width: 100%; max-height: 400px; object-fit: cover; border-radius: 8px; margin-bottom: 2rem;">`;
        }

        singleArticleContent.innerHTML = `
            ${imageHtml}
            <h1 style="margin-bottom: 0.5rem; font-size: 2.5rem;">${article.title}</h1>
            <div class="news-date" style="margin-bottom: 2rem;">${dateStr} <span data-i18n="by_author">• By </span> <strong style="color: var(--accent-color);">${article.authorName}</strong></div>
            <p style="white-space: pre-wrap; font-size: 1.1rem; line-height: 1.8;">${article.content}</p>
        `;

        newsContainer.style.display = 'none';
        if (toggleBtn) toggleBtn.style.display = 'none';
        if (newsForm) newsForm.classList.remove('active');
        singleArticleView.style.display = 'block';
    }
});
