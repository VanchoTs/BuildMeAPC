# BuildMeAPC WebScraper

A sophisticated data ingestion module built with **Python 3.13**. It automatically extracts, normalizes, and stores computer component data from retailers like `pic.bg`.

## ✨ Key Features

- **Hybrid Data Extraction**: Combines deterministic regular expression parsing with **LLM-based normalization** using Mistral 7B (GGUF).
- **Intelligent Normalization**: Transforms marketing titles and fragmented specifications into strictly typed database records (Cores, TDP, Socket types, PCIe generations).
- **Playwright Automation**: Uses a headless browser with automated cookie handling and lazy-loading support (infinite scroll) to capture all products.
- **Robust Pipeline**:
  - **URL Collection**: Scans category pages for product links.
  - **Page Parsing**: Extracts raw technical specs using BeautifulSoup4.
  - **AI Refinement**: Sends spec chunks to a local SLM (Small Language Model) to extract specific technical attributes.
  - **JSON Repair**: Custom logic to fix malformed JSON responses from the AI.
- **SQLAlchemy & PostgreSQL**: Manages 8 category tables with automated timestamps and `UPSERT` logic to prevent data duplication.

## 🤖 AI Component

The scraper uses **Mistral 7B Instruct** via `llama-cpp-python`.
- **Context Management**: "Fit-to-context" logic that handles long specification tables by prioritizing key technical terms.
- **Prompt Engineering**: Highly specialized prompts with strict rules (e.g., Core Rule for Intel hybrid CPUs, VRAM resolution logic for GPUs).

## 🛠️ Setup & Usage

1. **Environment**: Use `uv` for fast package management.
   ```bash
   uv sync
   source .venv/bin/activate
   ```
2. **Model Download**:
   Download `mistral-7b-instruct-v0.2.Q4_K_M.gguf` into `WebScraper/models_data/`.
3. **Browser Installation**:
   ```bash
   playwright install chromium
   ```
4. **Running Scrapers**:
   ```bash
   # Scrape CPUs
   python -m scripts.run_cpu_scraper --mode full --headless
   
   # Scrape Motherboards
   python -m scripts.run_motherboard_scraper --mode full --headless
   ```

## 📈 Monitoring

- **Error Logging**: Critical failures and AI parsing errors are recorded in `scraper_errors.log`.
- **Database Tracking**: `created_at` and `updated_at` columns track data freshness.
