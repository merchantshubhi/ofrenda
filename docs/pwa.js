if ("serviceWorker" in navigator) {
  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register(
        "./sw.js",
        { scope: "./" }
      );

      console.log(
        "Ofrenda service worker registered:",
        registration.scope
      );
    } catch (error) {
      console.error("Service worker registration failed:", error);
    }
  });
}