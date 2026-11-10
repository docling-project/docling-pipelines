# Docpipe UI User Guide

The Docpipe web UI is a visual tool for building, running, and monitoring document processing pipelines.
It is served by the FastAPI backend and is accessible at `/ui` on whichever host you have deployed Docpipe to.

- **Development**: `http://localhost:3000/ui`
- **Wheel / Docker**: `http://localhost:8080/ui`
- **OpenShift / Kubernetes**: `https://<your-route-host>/ui`

---

## Navigation

The application header contains four primary navigation items:

| Item | URL pattern | Purpose |
|------|-------------|---------|
| **Home** | `/ui/home` | Overview dashboard — recent projects, flows, and runs |
| **Projects** | `/ui/projects` | Manage projects and their flows |
| **Canvas** | `/ui/canvas/:flowId` | Visual pipeline editor (opened from a flow) |
| **Runs** | (accessible from a project) | Job run history and status |

---

## Signing in and roles

When authentication is enabled on the backend, the UI asks you to sign in before it shows any page. Administrators configure the login methods, the roles and the group mapping; see the [Authentication and Authorization Guide](AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md).

When authentication is disabled on the backend, the UI skips the sign-in page, treats you as an administrator and does not show the user menu in the header.

### Signing in

Open the UI at `/ui`. If you have no session, the UI redirects you to the **Sign in** page at `/ui/login`. The page shows the methods that the backend offers:

- **Credential form**: enter your username and password and click **Sign in**. Both fields are required. The form is shown only when the backend accepts username and password login.
- **Provider buttons**: one **Sign in with `<provider>`** button for each configured OIDC identity provider. The button leaves the UI, signs you in at the provider and returns you to the UI. When the page offers both methods, they are separated by **or**.
- If the backend has no login method configured, the page shows **No sign-in method is currently configured.** Contact your administrator.
- If you fail too many times in a row, the page shows **Too many failed attempts. Please retry later.** Wait and try again.

The session lives in an HttpOnly cookie that the browser sends automatically. The UI never stores your password or a token in the page, in browser storage or in the address bar.

#### Returning to the page you wanted

If you open a deep link while signed out, for example `/ui/projects/123`, the UI sends you to `/ui/login?return_to=%2Fprojects%2F123`. After a successful sign-in, with either method, you land on that page. Without a `return_to` value you land on **Projects**. The UI and the backend accept only paths inside the application as a return target; anything else is ignored.

### Signing out

When authentication is enabled, the header shows your name (or username if no full name is set). Open that menu and choose **Sign out**. The session ends and the **Sign in** page opens.

### When your session expires

If the backend rejects a request because your session ended (an HTTP 401 response), the UI clears your signed-in state and redirects you to `/ui/login?return_to=<current page>`. Sign in again to return to the page you were on. Unsaved changes on that page are lost, so save the flow before a long break.

### Roles

Your administrator assigns you one of three roles. The highest role you hold applies.

| Role | What you can do |
|------|-----------------|
| **Viewer** | Read only. Browse projects, flows, run history, run metrics, logs and the canvas. You cannot create, edit, delete or run anything. |
| **Editor** | Everything a viewer can do, plus create projects and flows, edit and delete your own projects, flows and runs, and run any flow. |
| **Admin** | Everything. Admins can modify any project, flow or run regardless of who created it. |

Editors work on their own assets. A project, flow or run records who created it. An editor can edit or delete an asset only if they created it. An asset without a recorded owner, such as one created before authentication was enabled or through the CLI, can be changed by any editor. Running a saved flow needs only the editor role, not ownership, so an editor can run a flow that someone else created.

| Action | Viewer | Editor (own asset or no owner) | Editor (asset of another user) | Admin |
|--------|--------|--------------------------------|--------------------------------|-------|
| Browse pages, run history, metrics and logs | Yes | Yes | Yes | Yes |
| Create a project or a flow | No | Yes | Yes | Yes |
| Edit or delete a project or a flow | No | Yes | No | Yes |
| Save changes on the canvas, edit flow details | No | Yes | No | Yes |
| Run a flow, **Run Again** | No | Yes | Yes | Yes |
| Stop a run, cancel a run, delete a run | No | Yes | No | Yes |

### Disabled buttons and tooltips

The UI disables an action you are not allowed to perform instead of hiding it. Hover over or focus the disabled button to see a tooltip that explains why: either your role is too low (you need the editor role) or the asset belongs to another user (only the owner or an administrator can change it). The Home page create-project and sample project actions, the create, edit and delete actions on **Projects**, **Project detail** and **Flow detail**, the cancel and delete actions on job runs, the edit-details button in **About flow**, the editing controls and **Save** on the canvas, and **Stop** and **Run Again** on a run all follow this pattern. Reading stays available everywhere: you can still open any flow, inspect nodes, view run history, metrics and logs.

If you ask the backend to do something your role does not allow, for example because your role changed during the session, the backend answers with HTTP 403 and the UI shows a **Permission Denied** notification with the text **You do not have permission to perform this action**. The UI gating is a convenience; the backend enforces every permission.

If a button you expect to use is disabled and you believe that is wrong, ask an administrator to check your role mapping.

---

## Pages

### Home

The Home page provides an at-a-glance overview with three summary cards:

- **Projects card** — lists your most recently modified projects.
- **Flows card** — lists your most recently modified flows across all projects.
- **Runs card** — lists recent job runs and their status.

Click any item in a card to navigate directly to it.

---

### Projects

The Projects page lists all projects. A **project** is a logical container for one or more pipelines (flows).

**Creating a project**

Click **Create project** in the top-right corner of the page. Enter a name and an optional description. The project appears in the list immediately after creation.

**Opening a project**

Click on any project card to open its detail view, which shows the flows that belong to it.

**Editing or deleting a project**

Use the overflow menu (⋮) on the project card to rename, edit the description, or delete the project.

---

### Project detail — Flows

Inside a project you see the list of flows. A **flow** is a directed pipeline of operators: it defines which operators run, in what order, and with what configuration.

**Creating a flow**

Click **Create flow**. Enter a name and optional description. The flow is saved to the project.

**Opening a flow in the canvas**

Click on any flow card to open the visual canvas editor for that flow.

**Editing or deleting a flow**

Use the overflow menu (⋮) on the flow card.

---

### Canvas

The Canvas is the visual pipeline editor. It opens when you click a flow.

#### Operator palette

The left panel lists all available operators grouped by category (Ingest, Extract, Functional, Quality, VectorDB, Storage). Drag an operator from the palette onto the canvas to add it to your pipeline.

#### Building a pipeline

1. **Add operators**: drag them from the palette onto the canvas.
2. **Connect operators**: drag from the output port of one operator to the input port of the next. Pipelines must have exactly one root operator (an ingest node with no incoming connections).
3. **Configure an operator**: double-click a node (or right-click → **Edit**) to open the properties panel on the right. Fill in the operator's parameters and click **Save**.
4. **Delete a node or link**: select it and press Delete, or use the right-click context menu.

#### Running a pipeline

Click **Run** in the canvas toolbar. The pipeline is submitted to the backend as a job. A notification appears when the run starts. Click **View run** (or navigate to the Runs page) to follow progress.

#### Flow run history

Click the **Flow run history** button in the toolbar to see all past runs for this flow with their status and duration.

#### About flow

Click **About flow** in the toolbar to view and edit the flow name and description without leaving the canvas.

---

### Runs

The Runs page (accessible from within a project) lists all job runs for that project. Each row shows:

- **Flow name**
- **Status** — `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`
- **Start time** and **duration**

Click any row to open the **Run details** page, which shows per-operator status, document counts, and error messages.

---

## Concepts

| Term | Meaning |
|------|---------|
| **Project** | A logical container for one or more flows |
| **Flow** | A directed acyclic graph (DAG) of operators that defines a pipeline |
| **Operator** | A single processing step (ingest, extract, chunk, embed, store, etc.) |
| **Node** | An operator instance placed on the canvas |
| **Link** | A connection between two nodes that defines data flow |
| **Job run** | A single execution of a flow |

---

## Typical workflow

```
1. Create a project
2. Create a flow inside the project
3. Open the flow in the canvas
4. Drag an Ingest operator onto the canvas and configure the file path or source
5. Add downstream operators (Extract, Chunker, Embeddings, VectorDB)
6. Connect them in order
7. Click Run
8. Monitor progress on the Runs page
```

---

## Troubleshooting

Symptoms can have different causes depending on how you started the UI. Find your deployment mode below.

---

### Local dev (`npm run dev`)

**Blank page or nothing loads at `http://localhost:3000/ui`**

- Check that both processes started: the terminal running `npm run dev` should show output from both `BFF` and `VITE` prefixes.
- Check that `frontend/.env` exists. If not, run `cp .env.example .env` from the `frontend/` directory and restart.
- Check that `BACKEND_API_URL` in `frontend/.env` points to where FastAPI is actually running (default: `http://localhost:8080`).

**Canvas shows no operators in the palette**

The browser cannot reach the backend API through the BFF. Open the browser developer console (F12) and check for errors on the Network tab.

- `net::ERR_CONNECTION_REFUSED` on `/api/*` — the BFF is not running. Check the `BFF` prefix output in the terminal; if it exited, re-run `npm run dev`.
- `404` from the BFF — the FastAPI backend is not running. Start it: `uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080`.
- CORS errors — the FastAPI backend is running on a different port than `BACKEND_API_URL` in `frontend/.env`.

**BFF exits immediately with `BACKEND_API_URL is not set`**

`frontend/.env` is missing or empty. Run `cp .env.example .env` from the `frontend/` directory.

---

### Wheel install (`uvicorn docpipe.api.main:app`)

**UI not accessible at `http://localhost:8080/ui`**

The frontend assets were not bundled into the wheel. Rebuild them manually and restart:
```bash
cd frontend && npm install && npm run build
python scripts/build_frontend.py
uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080
```

**Canvas shows no operators — backend logs show "BFF not started: node not found"**

`node` is not in `PATH`. Install Node.js (any version ≥ 18) and ensure it is on the system `PATH`, then restart the server.

**Canvas shows no operators — backend logs show "BFF not started: bff/server.cjs not found"**

The BFF bundle was not included in the wheel. Run `python scripts/build_frontend.py` from the project root to rebuild the assets and bundle, then restart.

---

### Docker Compose

**A service is not healthy**

```bash
docker compose -f docker/all-in-one-deployment/docker-compose.yml ps
docker compose -f docker/all-in-one-deployment/docker-compose.yml logs bff
docker compose -f docker/all-in-one-deployment/docker-compose.yml logs docpipe
```

**Canvas shows no operators after the stack is healthy**

The `docpipe` container depends on `bff` being healthy before it starts. If the BFF container restarted after `docpipe` came up, FastAPI may have lost its BFF URL. Restart the `docpipe` container:
```bash
docker compose -f docker/all-in-one-deployment/docker-compose.yml restart docpipe
```

---

### OpenShift / Kubernetes

**UI route returns 502 or connection refused**

Check that the BFF pod is running and healthy, and that `BFF_URL` is set correctly on the backend deployment:
```bash
oc get pods -l app=docpipe-bff
oc logs deployment/docpipe-bff
oc get env deployment/docpipe-backend | grep BFF_URL
```

---

### All modes

**A run stays in PENDING forever**

The backend started the job but an operator cannot reach an external service. Check the FastAPI logs for connection errors to Ollama, OpenSearch, or other configured services.

**Page loads but all API calls return 401 Unauthorized**

Your session is missing or expired. The UI normally redirects you to the sign-in page (see [When your session expires](#when-your-session-expires)). If you are stuck in a redirect loop between `/ui/login` and a page, the browser is not sending the session cookie (`docpipe_access_token` by default). Check that you open the UI on the same origin that served the sign-in, that cookies are not blocked, and that a custom ingress routes `/auth` to the REST API. See the [Authentication and Authorization Guide](AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md) for the session and cookie settings.

**Sign-in with a provider fails or returns to the sign-in page**

The provider must redirect to the callback address of your deployment, for example `http://localhost:3000/auth/oauth2/callback` for the Vite development server. See "Redirect URI per topology" in the [Authentication and Authorization Guide](AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md).
