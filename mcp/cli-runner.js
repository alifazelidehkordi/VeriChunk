import { spawn } from "node:child_process";

export class ProcessTimeoutError extends Error {}
export class ProcessOutputLimitError extends Error {}
export class ProcessCancelledError extends Error {}

function terminate(proc) {
  if (!proc || proc.killed) return;
  try { proc.kill("SIGTERM"); } catch {}
  const timer = setTimeout(() => {
    if (proc.exitCode === null) {
      try { proc.kill("SIGKILL"); } catch {}
    }
  }, 250);
  timer.unref?.();
}

export function runProcess(command, args = [], options = {}) {
  const {
    cwd,
    env,
    input,
    timeoutMs = 120_000,
    maxOutputBytes = 8 * 1024 * 1024,
    signal,
  } = options;
  return new Promise((resolve, reject) => {
    let settled = false;
    let stdoutBytes = 0;
    let stderrBytes = 0;
    const stdout = [];
    const stderr = [];
    let proc;
    let timer;

    const cleanup = () => {
      if (timer) clearTimeout(timer);
      signal?.removeEventListener?.("abort", onAbort);
    };
    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      terminate(proc);
      reject(error);
    };
    const onAbort = () => fail(new ProcessCancelledError("CLI process was cancelled"));

    if (signal?.aborted) {
      reject(new ProcessCancelledError("CLI process was cancelled"));
      return;
    }

    try {
      proc = spawn(command, args, { cwd, env, stdio: ["pipe", "pipe", "pipe"] });
    } catch (error) {
      reject(error);
      return;
    }

    proc.on("error", (error) => fail(error));
    proc.stdin.on("error", (error) => {
      if (error?.code !== "EPIPE") fail(error);
    });
    proc.stdout.on("data", (chunk) => {
      stdoutBytes += chunk.length;
      if (stdoutBytes + stderrBytes > maxOutputBytes) {
        fail(new ProcessOutputLimitError(`CLI output exceeded ${maxOutputBytes} bytes`));
        return;
      }
      stdout.push(chunk);
    });
    proc.stderr.on("data", (chunk) => {
      stderrBytes += chunk.length;
      if (stdoutBytes + stderrBytes > maxOutputBytes) {
        fail(new ProcessOutputLimitError(`CLI output exceeded ${maxOutputBytes} bytes`));
        return;
      }
      stderr.push(chunk);
    });
    proc.on("close", (code, processSignal) => {
      if (settled) return;
      settled = true;
      cleanup();
      const out = Buffer.concat(stdout).toString("utf8").trim();
      const err = Buffer.concat(stderr).toString("utf8").trim();
      if (code !== 0) {
        reject(new Error(err || out || `CLI exited with ${code ?? processSignal}`));
        return;
      }
      resolve(out);
    });

    if (timeoutMs > 0) {
      timer = setTimeout(() => {
        fail(new ProcessTimeoutError(`CLI process exceeded ${timeoutMs} ms`));
      }, timeoutMs);
      timer.unref?.();
    }
    signal?.addEventListener?.("abort", onAbort, { once: true });

    if (input !== undefined) proc.stdin.end(input);
    else proc.stdin.end();
  });
}

export function parseJsonOutput(output) {
  const text = String(output ?? "").trim();
  if (!text) throw new Error("CLI returned empty output where JSON was required");
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`CLI returned non-JSON output: ${error.message}`);
  }
}
