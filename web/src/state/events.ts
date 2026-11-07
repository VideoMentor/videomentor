// The app's one touch-event buffer, wired to the real API.
import { api } from '../lib/api';
import { EventBuffer } from '../lib/events';
import { storage } from './storage';

export const touches = new EventBuffer({
  storage,
  transport: async (events) => {
    await api.events(events);
  },
});
