# BuildMeAPC Back-End API

The core of the BuildMeAPC ecosystem, built with **ASP.NET Core 8.0** and **C#**. This REST API handles configuration generation, user authentication, and administrative management.

## 🚀 Key Features

- **Intelligent Recommendation Engine**: A greedy nested search algorithm that finds the best compatible PC parts within a given budget and tier (Price-Performance, Upgradeability, Quality).
- **Secure Authentication**: Implementation of JWT-based authentication using **HttpOnly cookies** for XSS protection and **BCrypt** for password hashing.
- **Role-Based Access Control (RBAC)**: Supports three user roles: `user`, `writer`, and `admin`.
- **Email Verification & Password Reset**: Automated email flows using SMTP for account verification and security.
- **Spam Protection**: A "gibberish detector" for configuration reports to prevent automated spam.
- **Entity Framework Core & PostgreSQL**: Robust data access layer with JSONB support for flexible technical specifications.

## 🏗️ Architecture

The project follows a modular service-oriented architecture:

- **Controllers**: Handle HTTP requests and define REST endpoints.
- **Services**: Contain the core business logic (e.g., `BuildService`, `BudgetAllocator`).
- **Models/DTOs**: Define the data structure for domain entities and API transfers.
- **Data (AppDbContext)**: Manages the connection to the PostgreSQL database.

## 🧠 Core Algorithms

### 1. BudgetAllocator
Distributes the total budget across 8 component categories based on the user's primary usage (Gaming, Workstation, General) and the selected build tier.

### 2. CandidatePicker
Queries the database for component "candidates" within a price band around the allocated amount, scoring them based on performance metrics.

### 3. BuildService (Greedy Search)
The main orchestrator that executes a 3-pass search:
- **Pass A (Strict)**: Honors the exact requested RAM capacity.
- **Pass B (Adaptive)**: Automatically adjusts RAM capacity if a build cannot be found at the requested level.
- **Pass C (Last Resort)**: Loosens constraints to ensure a recommendation is returned.

### 4. CompatibilityFilter
A collection of static rules that enforce hardware compatibility (Socket match, RAM type, PSU wattage overhead, Case physical dimensions).

## 🛠️ Setup & Running

1. **Prerequisites**: .NET 8.0 SDK, PostgreSQL 15+.
2. **Configuration**: Update `appsettings.json` with your database connection string and SMTP settings.
3. **Database Initialization**:
   ```bash
   dotnet run --urls "http://0.0.0.0:5075"
   ```
   *Note: `db.Database.EnsureCreated()` runs on startup to initialize application tables.*
4. **Swagger UI**: Accessible at `http://localhost:5075/swagger` in development mode.
