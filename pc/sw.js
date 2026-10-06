// Jenna's service worker: shows phone notifications for messages she sends on her own
// (morning check-in, business alerts, follow-ups, reminders), even when the app is closed.
const TOKEN = new URL(self.location.href).searchParams.get("t") || "";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", event => {
  let d = { title: "Jenna", body: "New message" };
  try { d = event.data.json(); } catch (e) {}
  event.waitUntil(self.registration.showNotification(d.title || "Jenna", {
    body: d.body || "", icon: "/icon.png?t=" + TOKEN, badge: "/icon.png?t=" + TOKEN,
    tag: "jenna", renotify: true, vibrate: [120, 60, 120]
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) { if ("focus" in w) return w.focus(); }
    return self.clients.openWindow("/");
  })());
});
