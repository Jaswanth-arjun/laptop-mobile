// Tiny observable store so the AI chat survives navigating between tabs
// (lives for the whole app session; cleared on page reload).

let messages = [];
const listeners = new Set();

function emit() {
  listeners.forEach((fn) => {
    try {
      fn(messages);
    } catch {}
  });
}

export const chatStore = {
  get: () => messages,
  add(message) {
    messages = [...messages, message];
    emit();
  },
  updateLast(patch) {
    if (!messages.length) return;
    messages = [...messages.slice(0, -1), { ...messages[messages.length - 1], ...patch }];
    emit();
  },
  clear() {
    messages = [];
    emit();
  },
  subscribe(fn) {
    listeners.add(fn);
    fn(messages);
    return () => listeners.delete(fn);
  },
};
