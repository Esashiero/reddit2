# 🤖 Reddit AI Curator

**Reddit AI Curator** is an advanced, AI-powered information retrieval system designed to find high-quality, relevant Reddit discussions. It combines professional Boolean search logic with Large Language Model (LLM) analysis to sift through thousands of posts and deliver the most impactful results.

---

## 🚀 Key Features

### 🏆 Multi-Query Tournament
Doesn't just run one search. It generates multiple query variations (Broad, Specific, Narrative, Jargon) and runs a "tournament" on a sample size to see which one performs best before committing to a full search.

### 🌊 Smart Search Cascade
If it doesn't find enough high-quality posts, it automatically triggers a tiered fallback system:
1.  **Sort Variation**: Retries with `relevance`, `top`, `hot`, and `comments` sorts.
2.  **Variant Fallback**: Uses the runner-up queries from the tournament.
3.  **Expansion**: Increases fetch limits to 500 posts per sub and expands the time filter.
4.  **Adaptive Scoring**: Intelligently relaxes the quality threshold (from 80 to 70/60) if the quota is still unmet.

### 📚 Continual Learning System
-   **Tag Extraction**: Automatically extracts semantic tags from high-scoring results to learn the "vocabulary" of successful matches.
-   **Favorites**: Save your favorite posts to train the AI. It will use your favorites to prioritize themes and keywords in future searches.
-   **Auto-Blacklist**: Automatically blacklists posts scoring >85 to ensure every new search provides fresh content.

---

## 🛠️ Setup & Installation

1.  **Python 3.12+**
2.  **Install Dependencies**:
    ```bash
    pip install praw mistralai google-generativeai flask python-dotenv
    ```
3.  **Configure Environment**:
    Create a `.env` file with your credentials:
    ```env
    REDDIT_CLIENT_ID=your_id
    REDDIT_CLIENT_SECRET=your_secret
    REDDIT_USER_AGENT=your_agent
    MISTRAL_API_KEY=your_key  # or GOOGLE_API_KEY
    ```

---

## 🖥️ Usage

### CLI Commands

**1. AI-Powered Curation (Best Results)**
Generates queries, runs a tournament, and performs the search cascade automatically.
```bash
python app.py curate --description "First person stories of car accidents in heavy rain" --target_posts 10
```

**2. Direct Boolean Search**
```bash
python app.py search --keywords "car accident AND (rain OR storm)" --criteria "High detail stories only"
```

**3. Discover Subreddits**
Finds subreddits that are most likely to contain the content you are looking for.
```bash
python app.py discover --keywords "adventure travel and hiking"
```

**Optional Flags:**
- `--exhaustive`: Try all sorts and variants for maximum recall.
- `--no-fallback`: Disable the automatic cascade.
- `--json`: Output raw data only.

### 🌐 Web Interface
Launch the interactive dashboard to run searches, view live results, manage subreddits, and browse your favorites.
```bash
python app.py
# Open http://localhost:5000 in your browser
```

---

## 📂 Project Structure

- `app.py`: Main application entry point (CLI & Web).
- `tag_learning.py`: The "brain" that manages favorites and tag-based refinement.
- `report_generator.py`: Generates the beautiful, standalone HTML reports.
- `config/`: Centralized folder for all JSON data (favorites, learning DB, queries, blacklist).
- `static/` & `templates/`: Responsive frontend assets.
- `results/`: Output folder for JSON and HTML findings.

---

**License:** MIT
