# BuildMeAPC 🖥️

An intelligent system for the selection and optimization of hardware components when building a personal computer. 

This project is a full-stack web application developed as a thesis titled: 
*"Intelligent system for selection and optimization of hardware components when building a personal computer"*

---

## 📖 Project Overview

BuildMeAPC is designed to solve the complexity of selecting compatible computer components. It guides users through an interactive questionnaire to understand their budget, intent (gaming, office, workstation), and aesthetic preferences. The system then uses an intelligent algorithm to generate three optimized configurations:
1. **Best Price/Performance Ratio**
2. **Best Future Upgradeability**
3. **Best Price/Quality Ratio**

The system handles all technical compatibility checks (sockets, chipsets, RAM frequencies, PSU wattage, and physical dimensions) automatically.

---

## ✨ Key Features

- **Intelligent Questionnaire:** Tailored component selection based on user-defined budgets (€) and use cases.
- **Compatibility Engine:** Real-time hardware matching rules implemented in the backend.
- **Comparison Tool:** Side-by-side analysis of technical parameters and prices.
- **My List & PDF Export:** Save configurations to a personal list and export them as professional PDF shopping lists.
- **Automated Web Scraper:** Continuous data ingestion from major retailers to ensure up-to-date pricing and availability.
- **Multi-Theme UI:** Support for Light Mode, Dark Mode (default), and a "Ultra Dark" Neon Red theme.
- **Internationalization (i18n):** Built-in Bulgarian (BG) translation engine with automatic detection.
- **Hardware News Feed:** Role-based publishing for hardware enthusiasts and writers.

---

## 🏗️ Architecture & Tech Stack

The project is architected in three distinct layers:

### 1. WebScraper (Data Layer)
- **Language:** Python 3.13
- **ORM:** SQLAlchemy (PostgreSQL)
- **Functions:** Scrapes hardware data, normalizes messy retailer specifications using advanced parsers, and stores them in the `pc_builder` database.

### 2. Back-End (Logic Layer)
- **Framework:** ASP.NET Core 8.0 Web API
- **Authentication:** Secure Cookie-based JWT with HttpOnly protection.
- **Security:** Password hashing via `BCrypt.Net-Next` and protection against SQL Injection via Entity Framework Core.
- **Role Management:** RBAC system for `user`, `writer`, and `admin` tiers.

### 3. WebPage (Presentation Layer)
- **Tech:** HTML5, Advanced CSS, TypeScript (ES Modules).
- **Features:** Responsive design, dynamic DOM translation (MutationObserver), and PDF generation via `html2pdf.js`.

---

## 📂 Project Structure

```text
BuildMeAPC/
├── WebScraper/      # Python data ingestion and normalization logic
├── Back-End/        # C# .NET 8 RESTful API
├── WebPage/         # TypeScript-driven frontend (Source in ts/, compiled in js/)
├── scripts/         # Database migrations and initialization scripts
├── docker-compose.yml # Full system orchestration
└── *.sql            # Core database schema and data seeds
```

---

## 🚀 Installation & Setup

### Option 1: Quick Start with Docker (Recommended)
The easiest way to run the entire stack is using Docker Compose:

1. **Clone the repository.**
2. **Run Docker Compose:**
   ```bash
   docker compose up -d
   ```
3. **Access the application:**
   - **Frontend:** [http://localhost:5500](http://localhost:5500) (or port 80 depending on config)
   - **API Swagger:** [http://localhost:5075/swagger](http://localhost:5075/swagger)
   - **Database:** localhost:5432

### Option 2: Manual Installation

#### 1. Prerequisites
- **Backend:** .NET 8.0 SDK
- **Database:** PostgreSQL 16+ (Database name: `pc_builder`)
- **Scraper:** Python 3.10+, `uv` (recommended)
- **Frontend:** Any static web server (e.g., Live Server, Nginx, or Python's `http.server`)

#### 2. Database Setup
1. Create a database named `pc_builder`.
2. Run the initialization scripts in order:
   ```bash
   psql -U your_user -d pc_builder -f init_app_tables.sql
   psql -U your_user -d pc_builder -f all_pc_parts.sql
   ```

#### 3. Backend Setup
1. Navigate to the API directory:
   ```bash
   cd Back-End/BuildMeAPC.Api
   ```
2. Configure `appsettings.json` with your PostgreSQL connection string and a secure JWT Token.
3. Start the API:
   ```bash
   dotnet run --urls "http://0.0.0.0:5075"
   ```

#### 4. WebScraper Setup
1. Install dependencies:
   ```bash
   cd WebScraper
   uv sync
   source .venv/bin/activate
   ```
2. Run scrapers to populate/update data:
   ```bash
   PYTHONPATH=. python -m scripts.run_cpu_scraper
   # Options: run_gpu_scraper, run_ram_scraper, run_motherboard_scraper, etc.
   ```

#### 5. Frontend Setup
Serve the `WebPage/` directory. If using Python:
```bash
cd WebPage
python3 -m http.server 5500
```

---

## ⚙️ Configuration

### JWT Authentication
Ensure the `AppSettings:Token` in `appsettings.json` (or `ASPNETCORE_AppSettings__Token` env var) is a secure, random string at least 64 characters long.

### Email (SMTP)
The system uses SMTP for account verification and password resets. Configure your provider in `appsettings.json`:
- `SmtpSettings:Server`
- `SmtpSettings:SenderEmail`
- `SmtpSettings:Password` (Use App Passwords for Gmail)

---

## 👥 User Roles

- **Ordinary User:** Access the configurator, compare builds, save to "My List", and export PDFs.
- **Writer:** All user rights + the ability to publish and manage hardware news articles.
- **Administrator:** Full system control, user management (roles, activation/deactivation), and content moderation.

---

## 🛠️ Ongoing Development

- [x] **Compatibility Engine:** Core logic for socket and power matching.
- [ ] **Advanced AI Recommendation:** Deeper integration of questionnaire inputs with the scorer algorithm.
- [ ] **Real-time Price Alerts:** Notification system for components in "My List".
- [ ] **Extended Internationalization:** Full support for additional languages beyond BG/EN.

