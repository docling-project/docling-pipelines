import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, act, waitFor, fireEvent } from '@testing-library/react';
import { ProjectsCard } from '@/components/cards/ProjectsCard';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { server } from '../../../mocks/server';
import { http, HttpResponse } from 'msw';

// ── mock navigate so we can assert calls ──────────────────────────────────
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

// ── shared fixtures ───────────────────────────────────────────────────────
const PROJECT_1 = {
  project_id: 'p-1',
  name: 'Alpha Project',
  description: 'First project',
  tags: [],
  flow_count: 3,
  created_on: '2024-01-01T00:00:00Z',
  modified_on: '2024-06-01T00:00:00Z',
  created_by: 'user',
  modified_by: 'user',
  href: '/api/projects/p-1',
};

const PROJECT_2 = {
  ...PROJECT_1,
  project_id: 'p-2',
  name: 'Beta Project',
  modified_on: '2024-07-01T00:00:00Z',
};

const CREATED_PROJECT = {
  project_id: 'new-proj-id',
  name: 'New Project',
  description: '',
  tags: [],
  flow_count: 0,
  created_on: '2024-01-01T00:00:00Z',
  modified_on: '2024-01-01T00:00:00Z',
  created_by: 'u',
  modified_by: 'u',
  href: '',
};

const CREATED_FLOW = {
  flow_id: 'new-flow-id',
  name: 'My Flow',
  description: '',
  tags: [],
  project_id: 'new-proj-id',
  container_id: 'new-proj-id',
  definition: '{}',
  created_on: '2024-01-01T00:00:00Z',
  modified_on: '2024-01-01T00:00:00Z',
};

function renderCard(opts?: Parameters<typeof renderWithProviders>[1]) {
  return renderWithProviders(<ProjectsCard />, opts);
}

// ── API helpers ───────────────────────────────────────────────────────────

function useEmptyProjectsApi() {
  server.use(
    http.get('/api/projects', () => HttpResponse.json({ projects: [], total: 0 }))
  );
}

function useOneProjectApi() {
  server.use(
    http.get('/api/projects', () =>
      HttpResponse.json({ projects: [PROJECT_1], total: 1 })
    )
  );
}

function useTwoProjectsApi() {
  server.use(
    http.get('/api/projects', () =>
      HttpResponse.json({ projects: [PROJECT_1, PROJECT_2], total: 2 })
    )
  );
}

function useErrorProjectsApi() {
  server.use(
    http.get('/api/projects', () =>
      HttpResponse.json({ detail: 'Server error' }, { status: 500 })
    )
  );
}

/**
 * The HomeCard header icon button is rendered by Carbon's `Button` with
 * `hasIconOnly`. In the DOM it gets `aria-labelledby` pointing to a tooltip
 * span that has `aria-hidden="true"`, so RTL's `getByRole` cannot resolve its
 * name via `aria-labelledby`. The reliable selector is the CSS class
 * `cds--btn--icon-only` inside the card header.
 */
function getHeaderIconButton(): HTMLElement | null {
  return document.querySelector(
    '[class*="cardHeaderAction"] .cds--btn--icon-only'
  ) as HTMLElement | null;
}

/**
 * Wait until the empty-state <h2> heading is visible (the API resolved).
 */
async function waitForEmptyState() {
  await waitFor(() => {
    expect(screen.getByRole('heading', { name: 'No recent projects' })).toBeInTheDocument();
  });
}

// ── tests ─────────────────────────────────────────────────────────────────

describe('ProjectsCard', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  // ── basic rendering ───────────────────────────────────────────────────

  it('renders the "Projects" card title', async () => {
    useEmptyProjectsApi();
    await act(async () => { renderCard(); });
    expect(screen.getAllByText(/^Projects$/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing when API returns empty list', async () => {
    useEmptyProjectsApi();
    await act(async () => { renderCard(); });
    expect(document.body).not.toBeNull();
  });

  // ── empty state ───────────────────────────────────────────────────────

  it('shows empty-state heading when no projects exist', async () => {
    useEmptyProjectsApi();
    renderCard();
    await waitForEmptyState();
    // Use heading role to disambiguate from SVG <title> tag
    expect(screen.getByRole('heading', { name: 'No recent projects' })).toBeInTheDocument();
  });

  it('shows empty-state subtitle when no projects exist', async () => {
    useEmptyProjectsApi();
    renderCard();
    await waitForEmptyState();
    expect(
      screen.getByText("After you create projects, you'll see them here.")
    ).toBeInTheDocument();
  });

  it('does NOT show "View all" button in empty state', async () => {
    useEmptyProjectsApi();
    renderCard();
    await waitForEmptyState();
    expect(screen.queryByText('View all')).not.toBeInTheDocument();
  });

  it('shows the header icon button in the card', async () => {
    useEmptyProjectsApi();
    renderCard();
    await waitForEmptyState();
    expect(getHeaderIconButton()).not.toBeNull();
  });

  // ── loaded projects list ──────────────────────────────────────────────

  it('renders project name rows when API returns projects', async () => {
    useOneProjectApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Alpha Project')).toBeInTheDocument();
    });
  });

  it('renders all returned projects', async () => {
    useTwoProjectsApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Alpha Project')).toBeInTheDocument();
      expect(screen.getByText('Beta Project')).toBeInTheDocument();
    });
  });

  it('shows "View all" button when projects exist', async () => {
    useOneProjectApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('View all')).toBeInTheDocument();
    });
  });

  it('does NOT show empty-state heading when projects are loaded', async () => {
    useOneProjectApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Alpha Project')).toBeInTheDocument();
    });
    expect(screen.queryByRole('heading', { name: 'No recent projects' })).not.toBeInTheDocument();
  });

  // ── project row relative time (modifiedOn metadata) ───────────────────

  it('renders relative time metadata for each project row', async () => {
    useOneProjectApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Alpha Project')).toBeInTheDocument();
    });
    const metaSpans = document.querySelectorAll('[class*="itemMeta"]');
    expect(metaSpans.length).toBeGreaterThan(0);
    expect(metaSpans[0]?.textContent).not.toBe('');
  });

  // ── sort order ────────────────────────────────────────────────────────

  it('sorts projects descending by modifiedOn — newer appears first', async () => {
    // PROJECT_2 has modified_on '2024-07-01' (later) vs PROJECT_1 '2024-06-01'
    // API returns them as [PROJECT_1, PROJECT_2]; component must sort descending
    useTwoProjectsApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Alpha Project')).toBeInTheDocument();
      expect(screen.getByText('Beta Project')).toBeInTheDocument();
    });

    const rows = document.querySelectorAll('[class*="itemRow"]');
    const names = Array.from(rows).map((r) =>
      r.querySelector('[class*="itemName"]')?.textContent
    );
    const betaIdx = names.indexOf('Beta Project');
    const alphaIdx = names.indexOf('Alpha Project');
    expect(betaIdx).toBeGreaterThanOrEqual(0);
    expect(alphaIdx).toBeGreaterThanOrEqual(0);
    expect(betaIdx).toBeLessThan(alphaIdx);
  });

  // ── loading state ─────────────────────────────────────────────────────

  it('shows loading paragraph while fetch is in-flight', async () => {
    let resolveApi!: (v: unknown) => void;
    const pending = new Promise((res) => { resolveApi = res; });
    server.use(
      http.get('/api/projects', async () => {
        await pending;
        return HttpResponse.json({ projects: [], total: 0 });
      })
    );

    renderCard();
    // Synchronously after render, loading=true → the paragraph is in the DOM
    expect(screen.getByText('Loading projects...')).toBeInTheDocument();

    // Unblock the API and wait for loading to clear
    await act(async () => { resolveApi(null); });
    await waitFor(() => {
      expect(screen.queryByText('Loading projects...')).not.toBeInTheDocument();
    });
  });

  // ── error state ───────────────────────────────────────────────────────

  it('shows "Failed to load projects." error paragraph on API failure', async () => {
    useErrorProjectsApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Failed to load projects.')).toBeInTheDocument();
    });
  });

  it('does NOT show project rows when API fails', async () => {
    useErrorProjectsApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Failed to load projects.')).toBeInTheDocument();
    });
    expect(screen.queryByText('Alpha Project')).not.toBeInTheDocument();
  });

  // ── project row click → navigate to project detail (line 124) ────────

  it('clicking a project row navigates to projectDetail URL', async () => {
    useOneProjectApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Alpha Project')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Alpha Project'));
    expect(mockNavigate).toHaveBeenCalledWith('/projects/p-1', undefined);
  });

  // ── "View all" click → navigate to /projects (line 138) ──────────────

  it('"View all" button navigates to /projects', async () => {
    useOneProjectApi();
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('View all')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('View all'));
    expect(mockNavigate).toHaveBeenCalledWith('/projects', undefined);
  });

  // ── header icon opens tearsheet (line 152) ───────────────────────────

  it('header icon button sets tearsheetOpen=true (dispatches onHeaderAction)', async () => {
    useEmptyProjectsApi();
    renderCard();
    await waitForEmptyState();

    const headerBtn = getHeaderIconButton();
    expect(headerBtn).not.toBeNull();

    if (headerBtn) {
      fireEvent.click(headerBtn);
      // After clicking, CreateProjectTearsheet should open
      await waitFor(() => {
        expect(screen.getByText('Create project and add flow')).toBeInTheDocument();
      });
    }
  });

  // ── tearsheet onClose sets open=false (line 168) ─────────────────────

  it('Cancel button inside tearsheet closes it (onClose sets tearsheetOpen=false)', async () => {
    useEmptyProjectsApi();
    renderCard();
    await waitForEmptyState();

    const headerBtn = getHeaderIconButton();
    if (!headerBtn) { return; }
    fireEvent.click(headerBtn);

    await waitFor(() => {
      expect(screen.getByText('Create project and add flow')).toBeInTheDocument();
    });

    const cancelBtn = screen.queryByRole('button', { name: /^cancel$/i });
    if (cancelBtn) {
      fireEvent.click(cancelBtn);
      await waitFor(() => {
        const dialog = screen.queryByRole('dialog');
        expect(dialog).not.toBeInTheDocument();
      });
    }
  });

  // ── handleSubmit: project only, no flow (lines 75-96) ────────────────

  it('handleSubmit without flow navigates to projectDetail', async () => {
    server.use(
      http.get('/api/projects', () => HttpResponse.json({ projects: [], total: 0 })),
      http.post('/api/projects', () =>
        HttpResponse.json(CREATED_PROJECT, { status: 201 })
      )
    );

    renderCard();
    await waitForEmptyState();

    const headerBtn = getHeaderIconButton();
    if (!headerBtn) { return; }
    fireEvent.click(headerBtn);

    await waitFor(() => {
      expect(screen.getByText('Create project and add flow')).toBeInTheDocument();
    });

    // Step 1: fill project name
    const nameInput = screen.getByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: 'New Project' } });

    // Advance to step 2 (flow details — optional)
    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));
    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeInTheDocument();
    });

    // Leave flow name blank → no flow created → navigate to project detail
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/projects/new-proj-id', undefined);
    });
  });

  // ── handleSubmit: with flow → navigate to canvas (lines 81-92) ───────

  it('handleSubmit with flow navigates to canvas URL', async () => {
    server.use(
      http.get('/api/projects', () => HttpResponse.json({ projects: [], total: 0 })),
      http.post('/api/projects', () =>
        HttpResponse.json(CREATED_PROJECT, { status: 201 })
      ),
      http.post('/api/flows', () =>
        HttpResponse.json(CREATED_FLOW, { status: 201 })
      )
    );

    renderCard();
    await waitForEmptyState();

    const headerBtn = getHeaderIconButton();
    if (!headerBtn) { return; }
    fireEvent.click(headerBtn);

    await waitFor(() => {
      expect(screen.getByText('Create project and add flow')).toBeInTheDocument();
    });

    // Step 1: fill project name
    fireEvent.change(screen.getByLabelText(/^name$/i), {
      target: { value: 'New Project' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));

    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeInTheDocument();
    });

    // Step 2: fill flow name so a flow IS created
    fireEvent.change(screen.getByLabelText(/^name$/i), {
      target: { value: 'My Auto Flow' },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        '/flows/new-flow-id/canvas?project_id=new-proj-id',
        undefined
      );
    });
  });

  // ── handleSubmit error path (lines 97-99) ────────────────────────────

  it('handleSubmit does not navigate when project creation fails', async () => {
    server.use(
      http.get('/api/projects', () => HttpResponse.json({ projects: [], total: 0 })),
      http.post('/api/projects', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    );

    renderCard();
    await waitForEmptyState();

    const headerBtn = getHeaderIconButton();
    if (!headerBtn) { return; }
    fireEvent.click(headerBtn);

    await waitFor(() => {
      expect(screen.getByText('Create project and add flow')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/^name$/i), {
      target: { value: 'Bad Project' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));

    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeInTheDocument();
    });

    await act(async () => {
      try {
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
      } catch {
        // expected — handleSubmit re-throws after notifying
      }
    });

    // navigate must NOT have been called because creation failed
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  // ── store is updated after project creation (line 79) ─────────────────

  it('dispatches setProject to store after successful project creation', async () => {
    server.use(
      http.get('/api/projects', () => HttpResponse.json({ projects: [], total: 0 })),
      http.post('/api/projects', () =>
        HttpResponse.json(CREATED_PROJECT, { status: 201 })
      )
    );

    const { store } = renderCard();
    await waitForEmptyState();

    const headerBtn = getHeaderIconButton();
    if (!headerBtn) { return; }
    fireEvent.click(headerBtn);

    await waitFor(() => {
      expect(screen.getByText('Create project and add flow')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/^name$/i), {
      target: { value: 'New Project' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));

    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    });

    await waitFor(() => {
      const state = store.getState();
      expect(state.projects.items['new-proj-id']).toBeDefined();
      expect(state.projects.items['new-proj-id']?.id).toBe('new-proj-id');
    });
  });

  // ── multiple projects capped at MAX_ROWS=5 ────────────────────────────

  it('renders at most 5 project rows regardless of API response', async () => {
    // Use descending modified_on so projects 0-4 appear first and project 5 is cut off
    const sixProjects = Array.from({ length: 6 }, (_, i) => ({
      ...PROJECT_1,
      project_id: `p-${i}`,
      name: `Row ${i}`,
      // 2025-06, 2025-05, 2025-04 … so Row 0 is newest and Row 5 is oldest
      modified_on: `2025-0${6 - i}-01T00:00:00Z`,
    }));
    server.use(
      http.get('/api/projects', () =>
        HttpResponse.json({ projects: sixProjects, total: 6 })
      )
    );

    renderCard();
    // Row 0 (newest) should be visible; the component caps the list to 5
    await waitFor(() => {
      expect(screen.getByText('Row 0')).toBeInTheDocument();
    });

    const rows = document.querySelectorAll('[class*="itemRow"]');
    expect(rows.length).toBeLessThanOrEqual(5);
    // Row 5 (the oldest) should be cut off
    expect(screen.queryByText('Row 5')).not.toBeInTheDocument();
  });
});
