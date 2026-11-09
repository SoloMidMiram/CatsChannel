async (page) => {
  // Synthetic only. All permitted responses are fulfilled by CDP.
  const origin = "http://127.0.0.1:1";
  const other = "http://127.0.0.1:2";
  const browser = page.context().browser();
  if (!browser) return { status: "BLOCKED", reason: "fresh_context_unavailable" };
  const context = await browser.newContext({ serviceWorkers: "block", acceptDownloads: false });
  const observed = [];
  const enforced = [];
  const childTargets = [];
  const failures = [];
  const held = [];
  // Static ASCII fixture bodies, encoded without Node or browser globals.
  function encode(text) {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let output = "";
    for (let i = 0; i < text.length; i += 3) {
      const a = text.charCodeAt(i), b = text.charCodeAt(i + 1) || 0, c = text.charCodeAt(i + 2) || 0;
      output += alphabet[a >> 2] + alphabet[((a & 3) << 4) | (b >> 4)];
      output += i + 1 < text.length ? alphabet[((b & 15) << 2) | (c >> 6)] : "=";
      output += i + 2 < text.length ? alphabet[c & 63] : "=";
    }
    return output;
  }
  let closing = false;
  let report;
  try {
    const tab = await context.newPage();
    context.on("page", () => childTargets.push("popup"));
    tab.on("frameattached", () => childTargets.push("frame"));
    context.on("request", request => observed.push(request.url()));
    const session = await context.newCDPSession(tab);
    const cap = 5;
    let admitted = 0;
    const csp = "sandbox allow-scripts allow-same-origin; frame-src 'none'; worker-src 'none'";
    const document = '<script src="/app.js"></script><img src="/thumbnail.png"><video preload="auto" src="/media.mp4"></video>';
    const app = `window.results = Promise.allSettled([
      fetch("/metadata").then(r => r.text()), fetch("/captions.vtt"),
      fetch("/redirect"), fetch("/cross")
    ]).then(async results => { await fetch("/overflow").catch(() => {}); return results; }); `;
    const fixtures = {
      [origin + "/"]: [200, "text/html", document],
      [origin + "/app.js"]: [200, "application/javascript", app],
      [origin + "/overflow"]: [200, "text/plain", "must not be admitted"],
      [origin + "/metadata"]: [200, "text/plain", "metadata-ok"],
      [origin + "/redirect"]: [302, "text/plain", "", origin + "/redirected.mp4"],
      [origin + "/cross"]: [302, "text/plain", "", other + "/forbidden"],
    };
    session.on("Fetch.requestPaused", async event => {
      const url = event.request.url;
      const entry = fixtures[url];
      const row = { url, action: "blocked", after_ceiling: admitted >= cap };
      enforced.push(row);
      try {
        if (url === origin + "/hold") {
          row.action = "held_for_cancellation";
          held.push(event.requestId);
        } else if (!entry || admitted >= cap) {
          await session.send("Fetch.failRequest", { requestId: event.requestId, errorReason: "BlockedByClient" });
        } else {
          admitted++;
          row.action = "fulfilled";
          const [responseCode, type, body, location] = entry;
          const responseHeaders = [{ name: "Content-Type", value: type }];
          if (location) responseHeaders.push({ name: "Location", value: location });
          if (url === origin + "/") responseHeaders.push({name:"Content-Security-Policy",value:csp});
          await session.send("Fetch.fulfillRequest", {
            requestId: event.requestId, responseCode, responseHeaders, body: encode(body)
          });
        }
      } catch {
        if (!closing) failures.push("interception_command_failed");
      }
    });
    await session.send("Fetch.enable", {patterns:[{urlPattern:"*",requestStage:"Request"}]});
    await tab.goto(origin + "/", { timeout: 5000 });
    const results = await tab.evaluate(() => Promise.race([
      window.results, new Promise(resolve => setTimeout(() => resolve(null), 2000))
    ]));
    const cookiesEmpty = (await context.cookies()).length === 0;
    const serviceWorkerCount = context.serviceWorkers().length;
    const popupRejected = await tab.evaluate(() => {
      const frame = document.createElement("iframe");
      frame.src = "/frame";
      document.body.append(frame);
      return window.open("/popup") === null;
    });
    await tab.evaluate(() => { fetch("/hold").catch(() => {}); });
    for (let i=0; i<20 && held.length===0; i++) await tab.evaluate(() => new Promise(resolve => setTimeout(resolve, 25)));
    const requiredBlocked = ["/thumbnail.png","/captions.vtt","/media.mp4","/redirected.mp4"]
      .every(path => enforced.some(row => row.url === origin + path && row.action === "blocked"));
    const crossBlocked = enforced.some(row => row.url === other + "/forbidden" && row.action === "blocked");
    const accounted = observed.every(url => observed.filter(x => x===url).length === enforced.filter(x => x.url===url).length);
    const ceilingBlocked = enforced.some(row => row.url === origin + "/overflow" && row.action === "blocked" && row.after_ceiling);
    const childNetworkRejected = !observed.some(url => [origin+"/frame",origin+"/popup"].includes(url));
    return report = {status:"synthetic_observation",ceilingBlocked,childNetworkRejected,eventStreamsMatch:accounted && observed.length === enforced.length,cookiesEmpty,serviceWorkerCount,metadataLoaded:results?.[0]?.value==="metadata-ok",requiredBlocked,crossBlocked,accounted,popupRejected,childTargets,heldBeforeClose:held.length,admitted,failures,observed,enforced};
  } catch {
    return report = {status:"BLOCKED",reason:"synthetic_controls_unavailable",observed,enforced};
  } finally {
    closing = true;
    await context.close();
    if (report) report.contextClosed = context.pages().length === 0;
  }
}
