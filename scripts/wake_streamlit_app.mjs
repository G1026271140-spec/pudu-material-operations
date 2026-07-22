import { spawn } from "node:child_process";
import { mkdir, appendFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const DEFAULT_URL = "https://pudu-material-inventory-ndgbxrpkkrzgkbapvhzvix.streamlit.app/";
const DEFAULT_EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const args = process.argv.slice(2);

function argument(name, fallback) {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
}

const appUrl = argument("--url", DEFAULT_URL);
const logPath = resolve(argument("--log", "work/streamlit-wake.log"));
const edgePath = argument("--edge", DEFAULT_EDGE);
const profilePath = resolve(argument("--profile", "work/streamlit-wake-edge-profile"));
const debugPort = Number(argument("--port", "9337"));
const timeoutMs = Number(argument("--timeout-ms", "150000"));

async function log(status, message, details = {}) {
  await mkdir(dirname(logPath), { recursive: true });
  const entry = {
    time: new Date().toISOString(),
    status,
    message,
    url: appUrl,
    ...details,
  };
  await appendFile(logPath, `${JSON.stringify(entry)}\n`, "utf8");
  process.stdout.write(`${entry.time} ${status}: ${message}\n`);
}

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function debugPages() {
  const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
  if (!response.ok) throw new Error(`Edge debugging endpoint returned ${response.status}`);
  return response.json();
}

async function waitForPage(deadline) {
  let lastError;
  const targetHost = new URL(appUrl).hostname;
  while (Date.now() < deadline) {
    try {
      const pages = await debugPages();
      const page = pages.find(
        (item) =>
          item.type === "page" &&
          item.webSocketDebuggerUrl &&
          String(item.url || "").includes(targetHost)
      );
      if (page) return page;
    } catch (error) {
      lastError = error;
    }
    await delay(500);
  }
  throw lastError || new Error("Timed out waiting for the Edge page");
}

function createCdpClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  const pending = new Map();
  let nextId = 1;

  const ready = new Promise((resolveReady, rejectReady) => {
    socket.addEventListener("open", resolveReady, { once: true });
    socket.addEventListener("error", () => rejectReady(new Error("CDP WebSocket failed")), {
      once: true,
    });
  });

  socket.addEventListener("message", async (event) => {
    const rawData =
      event.data instanceof Blob
        ? await event.data.text()
        : event.data instanceof ArrayBuffer
          ? Buffer.from(event.data).toString("utf8")
          : String(event.data);
    const message = JSON.parse(rawData);
    if (!message.id || !pending.has(message.id)) return;
    const { resolveMessage, rejectMessage } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) rejectMessage(new Error(message.error.message));
    else resolveMessage(message.result);
  });

  socket.addEventListener("close", () => {
    for (const { rejectMessage } of pending.values()) {
      rejectMessage(new Error("CDP WebSocket closed"));
    }
    pending.clear();
  });

  return {
    async send(method, params = {}) {
      await ready;
      const id = nextId++;
      const response = new Promise((resolveMessage, rejectMessage) => {
        pending.set(id, { resolveMessage, rejectMessage });
      });
      socket.send(JSON.stringify({ id, method, params }));
      return response;
    },
    close() {
      socket.close();
    },
  };
}

async function inspectAndWake(client) {
  const expression = `(() => {
    const text = document.body?.innerText || "";
    const title = document.title || "";
    const buttons = Array.from(document.querySelectorAll("button"));
    const wakeButton = buttons.find((button) =>
      /get this app back up|wake.*app|唤醒/i.test(button.innerText || button.textContent || "")
    );
    if (wakeButton) {
      wakeButton.click();
      return { clicked: true, ready: false, sleeping: true, title };
    }
    const ready = /营销物料管理系统|Marketing Materials System/.test(text + " " + title);
    const sleeping = /gone to sleep|Zzzz|due to inactivity/i.test(text);
    return { clicked: false, ready, sleeping, title };
  })()`;
  const result = await client.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  return result?.result?.value || {};
}

async function main() {
  const deadline = Date.now() + timeoutMs;
  await mkdir(profilePath, { recursive: true });
  const edge = spawn(
    edgePath,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--disable-default-apps",
      "--disable-extensions",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profilePath}`,
      appUrl,
    ],
    { stdio: "ignore", windowsHide: true }
  );

  let client;
  let clickedWake = false;
  let lastState = {};
  try {
    const page = await waitForPage(deadline);
    client = createCdpClient(page.webSocketDebuggerUrl);
    await client.send("Runtime.enable");
    while (Date.now() < deadline) {
      const state = await inspectAndWake(client);
      lastState = state;
      clickedWake = clickedWake || Boolean(state.clicked);
      if (state.ready) {
        await log("success", clickedWake ? "Streamlit app was woken and is ready" : "Streamlit app is already awake", {
          clickedWake,
          pageTitle: state.title || "",
        });
        return;
      }
      await delay(state.clicked ? 3000 : 1000);
    }
    throw new Error(
      `Timed out before the application became ready; last state: ${JSON.stringify(lastState)}`
    );
  } finally {
    if (client) {
      try {
        await client.send("Browser.close");
      } catch {
        // The browser may already be closing after navigation or timeout.
      }
      client.close();
    }
    edge.kill();
  }
}

try {
  await main();
} catch (error) {
  await log("error", error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
