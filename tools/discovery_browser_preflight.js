async (page) => {
  // Synthetic only. Every permitted response is fulfilled at interception.
  const origin = "http://127.0.0.1:1";
  const other = "http://127.0.0.2:2";
  const browser = page.context().browser();
  if (!browser) return { status: "BLOCKED", reason: "fresh_context_unavailable" };
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
  const html = [200, "text/html", "<title>synthetic</title>"];
  const cases = [
    { name: "redirects", script: `window.done = (async () => {
      await fetch("/deny").catch(() => {});
      await fetch("/cross").catch(() => {});
      return (await fetch("/allow")).text();
    })();`, fixtures: {
      [origin + "/deny"]: [302, "text/plain", "", origin + "/forbidden.mp4"],
      [origin + "/cross"]: [302, "text/plain", "", other + "/cross-forbidden.mp4"],
      [origin + "/allow"]: [302, "text/plain", "", origin + "/metadata"],
      [origin + "/metadata"]: [200, "text/plain", "metadata-ok"]
    }},
    { name: "resources", script: `window.done = Promise.allSettled(
      ["/thumbnail.png", "/captions.vtt", "/media.mp4"].map(path => fetch(path))); ` },
    { name: "admission_cap", admissionCap: 2, script: `window.done = (async () => {
      await fetch("/allowed"); await fetch("/overflow").catch(() => {});
    })();`, fixtures: {
      [origin + "/allowed"]: [200, "text/plain", "ok"],
      [origin + "/overflow"]: [200, "text/plain", "unexpected"]
    }},
    { name: "attempt_cap", attemptCap: 3, script: `window.done = (async () => {
      for (const path of ["/denied1", "/denied2", "/after-attempt-limit"]) {
        await fetch(path).catch(() => {});
      }
    })();` },
    { name: "child_targets", script: `
      for (const url of ["/frame", "${other}/cross-frame"]) {
        const frame = document.createElement("iframe");
        frame.src = url;
        document.body.append(frame);
      }
      window.open("/popup");
      window.done = new Promise(resolve => setTimeout(resolve, 500));
    `, fixtures: { [origin + "/frame"]: html, [other + "/cross-frame"]: html,
      [origin + "/popup"]: html }},
    { name: "cancellation", script: `window.done = new Promise(resolve => {
      fetch("/hold").catch(() => {}); setTimeout(resolve, 100);
    });` }
  ];
  const reports = [];
  for (const scenario of cases) {
    const report = {name:scenario.name, observed:[], decisions:[], failures:[],
      admitted:0, blocked:0, fulfilledBodyBytes:0, responseBytesObserved:0,
      observedResponsesCounted:0, observedResponsesUncounted:0, cancelled:0,
      childTargets:[], contextClosed:false, stoppedAtAttemptCap:false,
      attemptCap:scenario.attemptCap ?? 24, admissionCap:scenario.admissionCap ?? 12};
    reports.push(report);
    let context;
    let stopping = false;
    let pending;
    const body = '<!doctype html><body><script>' + scenario.script + '</script>';
    const fixtures = { [origin + "/"]: [200, "text/html", body], ...scenario.fixtures };
    try {
      context = await browser.newContext({serviceWorkers:"block",acceptDownloads:false});
      report.cookiesEmpty = (await context.cookies()).length === 0;
      const tab = await context.newPage();
      context.on("page", () => report.childTargets.push("popup"));
      tab.on("frameattached", () => report.childTargets.push("frame"));
      context.on("request", request => report.observed.push(request.url()));
      const sizes = [];
      context.on("requestfinished", request => {
        sizes.push(request.sizes().then(size => {
          report.responseBytesObserved += size.responseHeadersSize + size.responseBodySize;
          report.observedResponsesCounted++;
        }).catch(() => { report.observedResponsesUncounted++; }));
      });
      const session = await context.newCDPSession(tab);
      session.on("Fetch.requestPaused", async event => {
        const url = event.request.url;
        const row = {url, reason:"not_allowlisted", beforeAdmissionCap:report.admitted < report.admissionCap};
        report.decisions.push(row);
        try {
          if (stopping || report.decisions.length >= report.attemptCap) {
            row.reason = "attempt_cap";
            report.stoppedAtAttemptCap = true;
            report.blocked++;
            await session.send("Fetch.failRequest", {requestId:event.requestId,errorReason:"BlockedByClient"});
            if (!stopping) {
              stopping = true;
              await context.close();
            }
            return;
          }
          if (scenario.name === "cancellation" && url === origin + "/hold") {
            row.reason = "held";
            pending = {id:event.requestId,row};
            return;
          }
          const entry = fixtures[url];
          if (entry && row.beforeAdmissionCap) {
            const [responseCode, type, content, location] = entry;
            const responseHeaders = [{name:"Content-Type",value:type}];
            if (location) responseHeaders.push({name:"Location",value:location});
            row.reason = "fulfilled";
            report.admitted++;
            await session.send("Fetch.fulfillRequest", {
              requestId:event.requestId,responseCode,responseHeaders,body:encode(content)
            });
            report.fulfilledBodyBytes += content.length;
          } else {
            if (entry) row.reason = "admission_cap";
            report.blocked++;
            await session.send("Fetch.failRequest", {requestId:event.requestId,errorReason:"BlockedByClient"});
          }
        } catch {
          report.failures.push("interception_command_failed");
        }
      });
      await session.send("Fetch.enable", {patterns:[{urlPattern:"*",requestStage:"Request"}]});
      await tab.goto(origin + "/", {timeout:5000,waitUntil:"domcontentloaded"});
      report.scriptResult = await tab.evaluate(() => Promise.race([
        window.done, new Promise(resolve => setTimeout(() => resolve(null), 2000))
      ]));
      await Promise.all(sizes);
      if (pending) {
        await session.send("Fetch.failRequest", {requestId:pending.id,errorReason:"Aborted"});
        pending.row.reason = "cancelled";
        report.cancelled++;
        pending = null;
      }
      report.serviceWorkerCount = context.serviceWorkers().length;
    } catch {
      if (!report.stoppedAtAttemptCap) report.failures.push("synthetic_case_incomplete");
    } finally {
      if (context) {
        await context.close();
        report.contextClosed = context.pages().length === 0;
      }
    }
    report.pendingAtClose = pending ? 1 : 0;
    report.cdpAttempts = report.decisions.length;
    report.uncontrolledObserved = report.observed.filter((url,index) =>
      report.observed.slice(0,index+1).filter(x => x===url).length >
      report.decisions.filter(row => row.url===url).length);
    report.cdpOnly = report.decisions.filter((row,index) =>
      report.decisions.slice(0,index+1).filter(x => x.url===row.url).length >
      report.observed.filter(url => url===row.url).length).map(row => row.url);
  }
  const find = name => reports.find(r => r.name === name);
  const decision = (name,path,reason,spare=false) => find(name).decisions.some(row =>
    row.url.endsWith(path) && row.reason === reason && (!spare || row.beforeAdmissionCap));
  const targets = [origin+"/frame",other+"/cross-frame",origin+"/popup"];
  const children = find("child_targets");
  const childTargetCoverage = targets.every(url =>
    children.observed.includes(url) && children.decisions.some(row => row.url===url));
  const checks = {
    prohibitedRedirects:decision("redirects","/forbidden.mp4","not_allowlisted",true)
      && decision("redirects","/cross-forbidden.mp4","not_allowlisted",true),
    permittedRedirect:decision("redirects","/metadata","fulfilled",true)
      && find("redirects").scriptResult==="metadata-ok",
    resourceDenials:["/thumbnail.png","/captions.vtt","/media.mp4"].every(path =>
      decision("resources",path,"not_allowlisted",true)),
    admissionCap:decision("admission_cap","/overflow","admission_cap"),
    attemptCutoff:find("attempt_cap").stoppedAtAttemptCap
      && !find("attempt_cap").observed.some(url => url.endsWith("/after-attempt-limit")),
    strictAttemptCeiling:reports.every(r => r.cdpAttempts <= r.attemptCap),
    cancellation:find("cancellation").cancelled===1 && find("cancellation").pendingAtClose===0,
    childTargetCoverage,
    allContextsClosed:reports.every(r=>r.contextClosed),
    allDecisionsSucceeded:reports.every(r=>r.failures.length===0)
  };
  return {status:"synthetic_observation",liveQualification:"BLOCKED",checks,reports};
}
