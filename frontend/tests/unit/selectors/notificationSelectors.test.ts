import { describe, it, expect } from 'vitest';
import {
  selectActiveNotifications,
  selectNotificationHistory,
  selectNotificationUnreadCount,
  selectNotificationPreferences,
} from '@/selectors/notificationSelectors';
import type { RootState } from '@/store';
import { buildPreloadedState } from '../../mocks/fixtures/store.fixture';

function makeState(overrides: Partial<RootState['notifications']> = {}): RootState {
  return buildPreloadedState({
    notifications: {
      active: [],
      history: [],
      unreadCount: 0,
      preferences: { autoDismiss: true, dismissDelay: 5000 },
      ...overrides,
    },
  }) as RootState;
}

describe('notificationSelectors', () => {
  it('selectActiveNotifications returns active array', () => {
    const note = { id: 'n1', message: 'hello' } as never;
    const state = makeState({ active: [note] });
    expect(selectActiveNotifications(state)).toHaveLength(1);
  });

  it('selectNotificationHistory returns history array', () => {
    const note = { id: 'n2', message: 'past' } as never;
    const state = makeState({ history: [note] });
    expect(selectNotificationHistory(state)).toHaveLength(1);
  });

  it('selectNotificationUnreadCount returns unread count', () => {
    expect(selectNotificationUnreadCount(makeState({ unreadCount: 5 }))).toBe(5);
  });

  it('selectNotificationPreferences returns preferences object', () => {
    const prefs = { sound: true, desktop: false };
    const state = makeState({ preferences: prefs as never });
    expect(selectNotificationPreferences(state)).toEqual(prefs);
  });
});
