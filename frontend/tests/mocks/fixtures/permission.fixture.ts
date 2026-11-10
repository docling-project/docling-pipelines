import { authStateFixture } from './store.fixture';
import type { RootState } from '@/store';

/** Username of the signed-in user in every {@link PERMISSION_SCENARIOS} entry. */
export const ME = 'me';

/**
 * Role/ownership matrix shared by the permission-gating tests.
 * `owner` is the `created_by` / `user_id` of the asset; `allowed` is the expected outcome
 * for modify actions (edit, delete, cancel). Create actions only depend on the role.
 */
export const PERMISSION_SCENARIOS = [
  { name: 'viewer', role: 'viewer', owner: ME, allowed: false, canCreate: false },
  { name: 'editor own', role: 'editor', owner: ME, allowed: true, canCreate: true },
  { name: 'editor foreign', role: 'editor', owner: 'someone-else', allowed: false, canCreate: true },
  { name: 'admin', role: 'admin', owner: 'someone-else', allowed: true, canCreate: true },
  { name: 'editor ownerless', role: 'editor', owner: null, allowed: true, canCreate: true },
] as const;

export type PermissionScenario = (typeof PERMISSION_SCENARIOS)[number];

/** Preloaded Redux state that signs in as `ME` holding `role`. */
export function authPreloadedState(role: PermissionScenario['role']): Partial<RootState> {
  return { auth: authStateFixture({ role, username: ME }) };
}
