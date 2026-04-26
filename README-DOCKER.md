# BuildMeAPC Docker Deployment

This setup uses **Docker Compose** to run the complete project in isolated containers.

## Prerequisites
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

## Services
1. **db**: PostgreSQL 16 Database.
2. **api**: .NET 8 Web API.
3. **frontend**: Nginx serving the static HTML/JS/CSS files.
4. **scraper**: Python 3.13 scraper with Playwright support.

## Running the Project
1. Open a terminal in the project root.
2. Run the following command:
   ```bash
   docker compose up -d
   ```
3. The application will be available at:
   - **Frontend**: http://localhost
   - **API Swagger**: http://localhost:5075/swagger

## Upgrading After Code Changes
To easily upgrade the project after making changes to the source code:

### 1. Rebuild and restart everything
```bash
docker compose up --build -d
```

### 2. Rebuild a specific service (faster)
If you only changed the **API**:
```bash
docker compose build api && docker compose up -d api
```

If you only changed the **Scraper**:
```bash
docker compose build scraper && docker compose up -d scraper
```

If you only changed **Frontend** (HTML/JS/CSS):
- Since `WebPage/` is mounted as a volume in `docker-compose.yml`, you usually just need to **refresh your browser**. Changes are reflected instantly without a rebuild!

## Troubleshooting
- **Database Connection**: The API and Scraper connect to the `db` service using the hostname `db`.
- **Logs**: View logs with `docker compose logs -f [service_name]`.
- **Port Conflicts**: Ensure ports 80, 5432, and 5075 are not in use on your host.
