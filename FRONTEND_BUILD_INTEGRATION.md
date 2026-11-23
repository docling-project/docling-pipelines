# Frontend Build Integration

This document explains how the React frontend is integrated into the Python wheel package.

## Overview

The docpipe project includes a React frontend that is automatically built and bundled into the Python wheel during the package build process. When the wheel is installed, the frontend assets are included and served by the FastAPI backend.

## Architecture

### Build Process

1. **Frontend Build Script** (`scripts/build_frontend.py`)
   - Executed during wheel creation via hatch build hook
   - Checks for npm availability and exits with an error if it is missing
   - Installs frontend dependencies (`npm ci`)
   - Builds production frontend (`npm run build`)
   - Bundles the BFF server (`npm run build:bff`)
   - Copies built assets to `src/docpipe/api/static/`

2. **Hatch Build Hook** (`hatch_build.py`)
   - Custom hatch plugin that runs before wheel creation
   - Invokes the frontend build script
   - Fails the build with `Frontend build failed` if the frontend build script fails (for example, when npm is unavailable)
   - Runs for every wheel build, including editable installs (`uv sync`, `uv pip install -e .`)

3. **Static File Serving** (`src/docpipe/api/main.py`)
   - FastAPI mounts static files from `src/docpipe/api/static/`
   - Serves React app at `/ui` and `/ui/*` routes
   - Falls back to `index.html` for client-side routing

### Directory Structure

```
docling-pipelines/
├── frontend/                    # React application source
│   ├── src/
│   ├── package.json
│   └── vite.config.ts          # Base path: /ui/
├── scripts/
│   └── build_frontend.py       # Frontend build script
├── hatch_build.py              # Hatch build hook
├── pyproject.toml              # Build configuration
└── src/docpipe/api/
    ├── main.py                 # FastAPI with static file serving
    └── static/                 # Built frontend assets (generated)
        ├── index.html
        └── assets/
```

## Building the Package

### Prerequisites

- Python 3.12+
- Node.js 22.15.1+ and npm (for frontend build)
- uv package manager

### Build Commands

```bash
# Build wheel with frontend
uv build

# The build process will:
# 1. Run hatch_build.py hook
# 2. Execute scripts/build_frontend.py
# 3. Build React app with Vite
# 4. Copy assets to src/docpipe/api/static/
# 5. Create wheel with bundled frontend
```

### Build Without Node.js

Node.js and npm are required. If npm is not on `PATH`, the build fails:

```bash
uv sync
# Error: npm not found. Cannot build frontend for wheel.
# RuntimeError: Frontend build failed
```

Install Node.js 22.15.1 (for example with `nvm install` in the `frontend/` directory, which reads `frontend/.nvmrc`) and run the command again from the same shell. The build is skipped only when the `frontend/` directory or `frontend/package.json` is absent.

## Running the Application

### Development Mode

**Backend:**
```bash
# Start FastAPI server
uvicorn docpipe.api.main:app --reload --host 0.0.0.0 --port 8080
```

**Frontend (separate terminal):**
```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:3000
```

### Production Mode

After installing the wheel:

```bash
# Install the wheel
pip install dist/docling_pipelines-*.whl

# Start the server
uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080

# Access the UI at:
# http://localhost:8080/ui
```

## Frontend Configuration

### Vite Configuration (`frontend/vite.config.ts`)

```typescript
export default defineConfig({
  plugins: [react()],
  base: '/ui/',  // Important: matches FastAPI route
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
})
```

### React Router Configuration

The React app uses client-side routing with routes:
- `/ui` → Redirects to `/ui/home`
- `/ui/home` → Home page
- `/ui/canvas` → Canvas page

FastAPI serves `index.html` for all `/ui/*` routes to support client-side routing.

## API Endpoints

### Backend API
- `/api/v1/*` - REST API endpoints
- `/api/v1/docs` - Swagger UI
- `/health` - Health check

### Frontend
- `/ui` - React application root
- `/ui/*` - React application routes (client-side routing)
- `/static/*` - Static assets (JS, CSS, images)

## Troubleshooting

### Frontend Not Available

If you see "Frontend not found" when accessing `/ui`:

1. Check if static directory exists:
   ```bash
   ls -la src/docpipe/api/static/
   ```

2. Rebuild the frontend manually:
   ```bash
   python scripts/build_frontend.py
   ```

3. Verify npm is installed:
   ```bash
   npm --version
   ```

### Build Failures

If the wheel build fails:

1. Check build logs for errors
2. Ensure Node.js 22.15.1+ is installed
3. Try building frontend separately:
   ```bash
   cd frontend
   npm install
   npm run build
   ```

### CORS Issues

If frontend can't connect to backend API:

1. Check CORS configuration in `src/docpipe/api/main.py`
2. Ensure `CORS_ORIGINS` environment variable includes frontend URL
3. For development, default is `http://localhost:3000`

## CI/CD Considerations

### Jenkins/GitHub Actions

Ensure build environment has:
- Node.js 22.15.1+
- npm
- Python 3.12+
- uv

Example GitHub Actions:
```yaml
- name: Setup Node.js
  uses: actions/setup-node@v4
  with:
    node-version: '22.15.1'

- name: Build wheel
  run: uv build
```

### Docker Builds

Multi-stage Dockerfile example:
```dockerfile
# Stage 1: Build frontend
FROM node:22.15.1 as frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Build Python package
FROM python:3.12
WORKDIR /app
COPY --from=frontend-builder /app/frontend/dist /app/src/docpipe/api/static
COPY . .
RUN pip install uv && uv build
```

## Security Considerations

1. **Static File Serving**: Only serves files from `static/` directory
2. **Content Security Policy**: Configured in `SecurityHeadersMiddleware`
3. **CORS**: Restricted to configured origins
4. **Authentication**: API endpoints protected by JWT/LDAP

## Future Enhancements

- [ ] Add frontend build caching
- [ ] Support multiple frontend themes
- [ ] Add frontend unit tests to build process
- [ ] Implement frontend version checking
- [ ] Add source maps for production debugging
