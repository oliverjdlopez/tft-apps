/** Preserve native Windows executable discovery while forwarding Linux env privately. */
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";
import * as utilities from "../utils.mjs";

test("WSL wrapper uses native PATH and service env/cwd travels through the pipe", async (t) => {
  let invocation;
  let specification;
  globalThis.suiteEnvironmentFixture = { ...utilities,
    ownedProcess(command, args, options) {
      invocation = { command, args, options };
      return { child: { stdin: { write(value) { specification = JSON.parse(value); } } } };
    },
  };
  const hooks = registerHooks({
    resolve(specifier, context, next) {
      if (specifier !== "./utils.mjs" || !context.parentURL?.endsWith("runtime.mjs?environment-fixture")) return next(specifier, context);
      return { shortCircuit: true, url: "data:text/javascript,export const {abortable,ownedProcess,processFailure,stopProcess,waitForHttp,waitForRecord,wslCommand,waitForIdentity,serviceEnvironment}=globalThis.suiteEnvironmentFixture" };
    },
  });
  t.after(() => { hooks.deregister(); delete globalThis.suiteEnvironmentFixture; });
  const { DesktopRuntime } = await import("../runtime.mjs?environment-fixture");
  const wsl = { root: "/home/dev/tft-apps", node: "/linux/node", distro: "Ubuntu", user: "dev",
    env: { PATH: "/linux/bin", SUITE_FIXTURE: "private value" } };
  const runtime = new DesktopRuntime(wsl.root, wsl.node, {}, wsl);
  runtime.spawn("/linux/python", ["literal $argument"], "Python backend");
  assert.equal(invocation.command, "wsl.exe");
  assert.equal(invocation.options.env, process.env);
  assert.equal(specification.env.PATH, "/linux/bin");
  assert.equal(specification.env.SUITE_FIXTURE, "private value");
  assert.equal(specification.cwd, "/home/dev/tft-apps/tft-chat");
  assert.deepEqual(specification.args, ["literal $argument"]);
});
